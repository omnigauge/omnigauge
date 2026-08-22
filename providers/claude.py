"""Claude Code - reference provider.

This is the implementation to copy. It exercises every part of the contract:
token counting from transcripts, per-model attribution, quota scraped from the
CLI's own panel, and a declared set of windows that must parse.

See providers/README.md for the contract itself.
"""
import glob
import io
import json
import os
import re

import omnigauge as og

NAME = "claude"
KIND = "agent"

CAPS = dict(tokens="obtained", quota="obtained", reset="obtained",
            models="obtained", lifetime="obtained",
            spend="unavailable: subscription plans have no dollar balance",
            burn="obtained: derived from the quota series")


# ── presence ────────────────────────────────────────────────────────────────

def detect():
    return bool(files()) or og.installed("claude")


def files():
    """Claude encodes the project path with BOTH '/' and '_' collapsed to '-',
    so ~/work/my_app becomes -home-you-work-my-app. Getting that wrong yields an
    empty directory rather than an error, which reads as "no usage" - a silent
    wrong answer, the worst kind.

    Recursive, because transcripts do not all sit one level down: subagent runs
    write project/<session>/subagents/agent-*.jsonl, and the one-level glob this
    mirror used to carry silently dropped 39 files, ~1,500 messages and every
    haiku token while the built-in had already been fixed - the mirror OVERRIDES
    the built-in at load, so the two must change together. Windows homes for the
    same reason codex scans them."""
    out = []
    for h in og.all_homes(".claude"):
        out += glob.glob(f"{h}/projects/**/*.jsonl", recursive=True)
    return out


# ── token counting ──────────────────────────────────────────────────────────

def scan(path, since=0):
    t = og.blank()
    for line in io.open(path, errors="replace"):
        if '"usage"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        msg = d.get("message") or {}
        u = msg.get("usage")
        if not isinstance(u, dict):
            continue
        # Record the newest timestamp regardless of the window. The core uses it
        # to decide whether skipping this file on mtime is provably safe - mtime
        # is a claim about when the file was written, this is a fact about what
        # is in it, and a restore or a skewed clock makes them disagree.
        ep = og._epoch(d.get("timestamp", ""))
        if ep is not None and ep > (t.get("last_ts") or 0):
            t["last_ts"] = ep
        if since and ep is not None and ep < since:
            continue
        t["msgs"] += 1
        t["tin"] += u.get("input_tokens", 0)
        t["tout"] += u.get("output_tokens", 0)
        t["cache_read"] += u.get("cache_read_input_tokens", 0)
        t["cache_write"] += u.get("cache_creation_input_tokens", 0)
        t["think"] += (u.get("output_tokens_details") or {}).get("thinking_tokens", 0)
        # total = in + out + cache_read, the same formula the board and the
        # per-model rows use - and the builtin now caches. Mirror must match.
        t["total"] += (u.get("input_tokens", 0) + u.get("output_tokens", 0)
                       + u.get("cache_read_input_tokens", 0))
        og.add_model(
            t, msg.get("model"),
            out=u.get("output_tokens", 0),
            total=(u.get("output_tokens", 0) + u.get("cache_read_input_tokens", 0)
                   + u.get("input_tokens", 0)),
            msgs=1,
        )
    return t


# ── plan quota ──────────────────────────────────────────────────────────────

QUOTA = dict(
    argv=["claude"],
    keys="/usage",
    # Wait for a prompt marker before typing. A fixed sleep broke the day Claude
    # shipped a slower splash screen: the keystrokes landed before the input box
    # was live and the scrape returned a welcome screen.
    ready=r"(Try \"|❯|>\s*$|for shortcuts)",
    done=r"Current (week|session)",
    # Windows that MUST parse. Missing one is a PARTIAL, treated as failure -
    # plausible rows with the headline absent are worse than no rows at all.
    expect=[("week", "all"), ("session", "all")],
)


def parse_quota(screen):
    """Claude reports PERCENT USED, so no inversion is needed here. Codex
    reports percent REMAINING and inverts in its own provider.

    Line-based on purpose. A single collapsed-whitespace regex silently dropped
    the weekly row - the headline number - because Claude injects a promo line
    between the reset line and the next heading, and the pattern's lookahead
    expected a heading there.
    """
    rows, pend = [], None
    for raw in screen.splitlines():
        line = raw.strip()
        m = re.match(r"Current (session|week)\s*(?:\(([^)]*)\))?\s*$", line, re.I)
        if m:
            if pend and pend["pct_used"] is not None:
                rows.append(pend)
            model = (m.group(2) or "all").strip()
            if model.lower() in ("all models", ""):
                model = "all"
            pend = dict(window=m.group(1).lower(), model=model,
                        pct_used=None, raw_value=None, reset_at=None)
            continue
        if pend is None:
            continue
        m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*used", line, re.I)
        if m and pend["pct_used"] is None:
            pend["pct_used"] = float(m.group(1))
            pend["raw_value"] = f"{m.group(1)}% used"
            continue
        m = re.match(r"Resets\s+(.+?)\s*$", line, re.I)
        if m and pend["reset_at"] is None:
            pend["reset_at"] = m.group(1).strip()
    if pend and pend["pct_used"] is not None:
        rows.append(pend)
    return rows


def insights(screen):
    """Claude volunteers why the week is high. It is genuinely actionable, so
    it is kept and shown rather than discarded."""
    return [l.strip() for l in screen.splitlines()
            if re.match(r"\d+% of your usage", l.strip(), re.I)]


# ── where to launch it ──────────────────────────────────────────────────────

def scrape_cwd():
    """Launching Claude somewhere it has not seen raises a blocking
    workspace-trust dialog which swallows the keystrokes. omnigauge will NOT
    auto-accept that - trusting a folder is a real security decision and it
    persists. Reuse a directory the CLI has demonstrably run in, taken from its
    own session registry."""
    best, newest = None, 0
    for f in glob.glob(os.path.expanduser("~/.claude/sessions/*.json")):
        try:
            with io.open(f, encoding="utf-8") as fh:
                d = json.load(fh)
            cwd, st = d.get("cwd"), os.path.getmtime(f)
            if cwd and os.path.isdir(cwd) and st > newest:
                best, newest = cwd, st
        except (OSError, ValueError):
            continue
    return best or os.getcwd()
