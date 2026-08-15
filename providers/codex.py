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
    out = []
    for h in og.all_homes(".codex"):
        out += glob.glob(f"{h}/sessions/**/*.jsonl", recursive=True)
    return out


# ── token counting ──────────────────────────────────────────────────────────

_FIELDS = (("tin", "input_tokens"), ("tout", "output_tokens"),
           ("cache_read", "cached_input_tokens"),
           ("think", "reasoning_output_tokens"), ("total", "total_tokens"))


def _spend(seq, since, fields):
    """What was actually spent from `since` onward, given (epoch, totals) events.

    The cumulative counter is differenced STEP BY STEP rather than end to end,
    because it does not only climb. A rollout reused by a new session, or a
    vendor-side restart, sends it backwards; when that happens the new value is
    itself the spend since the restart.

    Endpoint arithmetic broke in both directions. A reset inside the window gave
    last < base, which max(0, ...) turned into a confident zero. A reset whose
    new run overtook the old total gave a positive difference that silently
    omitted everything before the restart.
    """
    acc = {k: 0 for k, _ in fields}
    prev = None
    for ep, u in seq:
        if prev is not None and (ep is None or ep >= since):
            for k, f in fields:
                c, p = u.get(f, 0), prev.get(f, 0)
                acc[k] += c if c < p else c - p      # c < p means it restarted
        prev = u
    return acc


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
    # Newest stamped event in this file, recorded whatever the window is. The
    # core needs a FACT about the contents to justify skipping the file on mtime;
    # mtime is only a claim about when it was written, and a restore or a skewed
    # clock makes the two disagree.
    _st = [ep for ep, _ in events if ep is not None]
    if _st:
        t["last_ts"] = max(_st)
    model = None
    mm = re.findall(r'"model":"([^"]+)"', tail)
    if mm: model = mm[-1]          # rollouts can span models; attribute to the last
    last = events[-1][1]
    base = None
    seq = None
    if since:
        stamped = [(ep, u) for ep, u in events if ep is not None]
        if not stamped:
            # Nothing in this file can be placed in time. Attributing its whole
            # cumulative to every window that asks is a wrong number wearing a
            # right one's clothes; mtime is the only evidence left, so use it.
            try:
                if os.path.getmtime(path) < since:
                    return t
            except OSError:
                return t
        if stamped and not any(ep >= since for ep, _ in stamped):
            return t               # tail is authoritative: nothing in the window
        pre = [u for ep, u in stamped if ep < since]
        if pre:
            base = pre[-1]         # window edge sits inside the tail
            seq = stamped          # and every in-window event is here too
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
                if pre:
                    base = pre[-1]
                    # The edge sits outside the tail, so the events between it
                    # and the tail were never read. Step-summing what we DO have
                    # still catches a restart visible in the tail; one hidden in
                    # the unread gap is beyond what a bisect can see.
                    seq = [(since - 1, base)] + stamped
    t["msgs"] = 1
    if since and seq:
        for key, val in _spend(seq, since, _FIELDS).items():
            t[key] = val
    else:
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
