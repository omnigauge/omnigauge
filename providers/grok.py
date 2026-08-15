"""Grok CLI — reference provider.

Mirrors the built-in and overrides it at load, exactly like claude.py. The
part worth copying: Grok's usage panel wraps unpredictably, so the parser
collapses the whole screen to one line before matching, where claude.py stays
line-based because Claude injects promo lines BETWEEN its rows. Pick the shape
that matches how your vendor's panel actually breaks.
"""
import glob
import io
import json
import os
import re

import omnigauge as og

NAME = "grok"
KIND = "agent"

CAPS = dict(tokens="obtained: session totals only", quota="obtained",
            reset="obtained", models="obtained: from the session summary",
            lifetime="obtained",
            spend="unavailable: subscription plans have no dollar balance",
            burn="obtained: derived from the quota series")


# ── presence ────────────────────────────────────────────────────────────────

def files():
    out = []
    for h in og.all_homes(".grok"):
        out += glob.glob(f"{h}/sessions/*/*/updates.jsonl")
    return out


# ── token counting ──────────────────────────────────────────────────────────

def scan(path, since=0):
    """totalTokens is cumulative per session; the maximum seen is the total.
    With `since`, the window gets the GROWTH of that cumulative, not the whole
    history of a session merely touched inside it. Untimestamped lines count
    toward the baseline: understating the window shows against LIFETIME,
    inflating it does not. The model comes from the session's summary.json."""
    t = og.blank()
    best, before, in_window = 0, 0, False
    model = None
    try:
        smry = os.path.join(os.path.dirname(path), "summary.json")
        if os.path.exists(smry):
            with io.open(smry, encoding="utf-8") as fh:
                model = json.load(fh).get("current_model_id")
    except (OSError, ValueError):
        pass
    for line in io.open(path, errors="replace"):
        if '"totalTokens"' not in line: continue
        try: d = json.loads(line)
        except ValueError: continue
        v = og._dig(d, "totalTokens")
        if not isinstance(v, int): continue
        best = max(best, v)
        ts = d.get("timestamp")
        if since:
            if isinstance(ts, (int, float)) and ts >= since: in_window = True
            else: before = max(before, v)
    got = (max(0, best - before) if in_window else 0) if since else best
    if got:
        t["msgs"], t["total"] = 1, got
        og.add_model(t, model or "unknown", total=got, msgs=1)
    return t


# ── plan quota ──────────────────────────────────────────────────────────────

QUOTA = dict(
    argv=["grok"],
    keys="/usage",
    ready=r"(❯|»|Enter:send|shortcuts)",
    done=r"Weekly limit",
    # model=None: any model label satisfies the week window — Grok names the
    # plan tier, not a model, and the tier string is not stable enough to pin.
    expect=[("week", None)],
    source="cli_usage",
)


def parse_quota(screen):
    rows, txt = [], re.sub(r"\s+", " ", screen)
    m = re.search(r"Weekly limit\s*\(([^)]*)\).*?(\d+)\s*%", txt)
    if m:
        r = re.search(r"Resets:\s*([A-Za-z0-9 ,:]{4,30})", txt)
        rows.append(dict(window="week", model=m.group(1).strip() or "all",
                         pct_used=float(m.group(2)), raw_value=f"{m.group(2)}%",
                         reset_at=r.group(1).strip() if r else None))
    return rows
