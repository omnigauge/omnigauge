"""OpenAI Codex — reference provider.

Mirrors the built-in and overrides it at load, exactly like claude.py. Two
things here are worth copying into any provider for a similar tool:

The scan reads from the END of the file. Codex rollouts reach hundreds of
megabytes and the wanted figure is the last cumulative total — scanning
forward made a redraw take ~18s across a large corpus; the tail read took it
to ~2s. If your source is large, do the same.

Codex reports percent REMAINING and this provider inverts it to percent
consumed, keeping the vendor's own wording in raw_value so the board can show
the conversion. Getting this backwards makes a nearly exhausted account look
healthy — the single worst failure this tool can have.
"""
import glob
import io
import os
import json
import re

import omnigauge as og

NAME = "codex"
KIND = "agent"

CAPS = dict(tokens="obtained: last cumulative total per rollout",
            quota="obtained: percent remaining, inverted", reset="obtained",
            models="obtained: attributed to the last model in the file",
            lifetime="obtained",
            spend="unavailable: subscription plans have no dollar balance",
            burn="obtained: derived from the quota series")


# ── presence ────────────────────────────────────────────────────────────────

def files():
    """WSL keeps TWO stores — ~/.codex and the Windows-side install. Searching
    one and declaring the other absent is a mistake that has been made here."""
    out = glob.glob(os.path.expanduser("~/.codex/sessions/**/*.jsonl"), recursive=True)
    for h in og.windows_homes(".codex"):
        out += glob.glob(f"{h}/sessions/**/*.jsonl", recursive=True)
    return out


# ── token counting ──────────────────────────────────────────────────────────

_FIELDS = (("tin", "input_tokens"), ("tout", "output_tokens"),
           ("cache_read", "cached_input_tokens"),
           ("think", "reasoning_output_tokens"), ("total", "total_tokens"))


def _events(text):
    """(epoch, totals) for every token_count event in a text block."""
    out = []
    for line in text.splitlines():
        if '"total_token_usage"' not in line: continue
        try: d = json.loads(line)
        except ValueError: continue
        u = og._dig(d, "total_token_usage")
        if u: out.append((og._epoch(d.get("timestamp", "")), u))
    return out


def _block(fh, size, off, nbytes=1 << 18):
    """A line-aligned text block starting at off."""
    fh.seek(max(0, off))
    if off > 0: fh.readline()
    return fh.read(min(nbytes, size)).decode("utf-8", "replace")


def scan(path, since=0):
    """Last cumulative total per rollout. input_tokens counts context re-sent
    each turn, so it runs far above the vendor's own 'tokens used'.

    With `since`, the value is the DELTA of that cumulative across the window
    edge - a rollout merely touched inside the window no longer donates its
    whole history to it. Rollout logs are append-only and chronological, so
    the edge is found by bisecting byte offsets: a handful of 256KB probes
    even on a multi-GB file. Events without parseable timestamps attribute
    the whole cumulative, as before: overstating is visible, dropping is
    not."""
    t = og.blank()
    try: size = os.path.getsize(path)
    except OSError: return t
    tail = og.tail_chunk(path)
    events = _events(tail)
    if not events and size > (1 << 20):
        try: whole = io.open(path, errors="replace").read()
        except OSError: return t
        tail, events = whole, _events(whole)
    if not events:
        return t
    model = None
    mm = re.findall(r'"model":"([^"]+)"', tail)
    if mm: model = mm[-1]          # rollouts can span models; attribute to the last
    last = events[-1][1]
    base = None
    if since:
        stamped = [(ep, u) for ep, u in events if ep is not None]
        if stamped and not any(ep >= since for ep, _ in stamped):
            return t               # tail is authoritative: nothing in the window
        pre = [u for ep, u in stamped if ep < since]
        if pre:
            base = pre[-1]         # window edge sits inside the tail
        elif stamped and size > (1 << 20):
            with open(path, "rb") as fh:
                lo, hi = 0, size
                while hi - lo > (1 << 18):
                    mid = (lo + hi) // 2
                    ev = _events(_block(fh, size, mid))
                    ts = next((ep for ep, _ in ev if ep is not None), None)
                    if ts is None or ts >= since: hi = mid
                    else: lo = mid
                ev = _events(_block(fh, size, lo, (1 << 19)))
                pre = [u for ep, u in ev if ep is not None and ep < since]
                if pre: base = pre[-1]
    t["msgs"] = 1
    for key, field in _FIELDS:
        t[key] = max(0, last.get(field, 0) - (base.get(field, 0) if base else 0))
    og.add_model(t, model or "unknown", out=t["tout"], total=t["total"], msgs=1)
    return t


# ── plan quota ──────────────────────────────────────────────────────────────

QUOTA = dict(
    argv=["codex"],
    keys="/status",
    ready=r"(»|Explain this codebase|/model to change)",
    done=r"Weekly limit:",
    expect=[("week", "all")],
    source="cli_status",
)


def parse_quota(screen):
    """% LEFT natively — inverted to % USED here, vendor wording preserved."""
    rows = []
    for line in screen.splitlines():
        m = re.search(r"(.*?)Weekly limit:\s*\[[^\]]*\]\s*(\d+)%\s*left\s*\(resets\s+([^)]+)\)", line)
        if not m: continue
        label = re.sub(r"[│|]", "", m.group(1)).strip() or "all"
        left = float(m.group(2))
        rows.append(dict(window="week", model=label, pct_used=100.0 - left,
                         raw_value=f"{int(left)}% left", reset_at=m.group(3).strip()))
    return rows
