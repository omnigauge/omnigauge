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


# ── presence ────────────────────────────────────────────────────────────────

def files():
    """WSL keeps TWO stores — ~/.codex and the Windows-side install. Searching
    one and declaring the other absent is a mistake that has been made here."""
    out = glob.glob(os.path.expanduser("~/.codex/sessions/**/*.jsonl"), recursive=True)
    for h in og.windows_homes(".codex"):
        out += glob.glob(f"{h}/sessions/**/*.jsonl", recursive=True)
    return out


# ── token counting ──────────────────────────────────────────────────────────

def scan(path, since=0):
    """Last cumulative total per rollout. input_tokens counts context re-sent
    each turn, so it runs far above the vendor's own 'tokens used'. Falls back
    to a full scan only when the tail holds no total at all."""
    t = og.blank()
    last = None
    model = None
    for text in (og.tail_chunk(path), None):
        if text is None:
            if last: break
            try: text = io.open(path, errors="replace").read()
            except OSError: break
        for line in text.splitlines():
            if '"total_token_usage"' not in line: continue
            try: d = json.loads(line)
            except ValueError: continue
            u = og._dig(d, "total_token_usage")
            if u: last = u
        if last:
            mm = re.findall(r'"model":"([^"]+)"', text)
            if mm: model = mm[-1]      # rollouts can span models; attribute to the last
            break
    if last:
        t["msgs"] = 1
        t["tin"] = last.get("input_tokens", 0)
        t["tout"] = last.get("output_tokens", 0)
        t["cache_read"] = last.get("cached_input_tokens", 0)
        t["think"] = last.get("reasoning_output_tokens", 0)
        t["total"] = last.get("total_tokens", 0)
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
