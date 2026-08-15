"""Goose (aaif-goose, formerly Block) — agent provider.

Verified on a real install 2026-08-15: Goose keeps a SQLite database, not
transcripts - ~/.local/share/goose/sessions/sessions.db - and its
usage_ledger table is the vendor's own accounting: one row per usage event
with model, input/output/total/cache tokens, an epoch timestamp and a cost
estimate. The VALUES were proven real before this was written (3,098 in /
2 out from one live exchange) - the Cursor lesson is that field presence is
not data presence, and this source passed where Cursor failed.

The database is opened read-only WITHOUT immutable=1: Goose runs WAL mode,
and immutable cannot see rows still in the write-ahead log - which is where
the most recent usage always is.
"""
import glob
import os
import sqlite3

import omnigauge as og

NAME = "goose"
KIND = "agent"

CAPS = dict(
    tokens="obtained: usage_ledger, the vendor's own accounting",
    quota="unavailable: key-based; there is no plan window to read",
    reset="unavailable: no plan window, nothing resets",
    models="obtained: per ledger row, dated model ids",
    lifetime="obtained",
    spend="available: cost is recorded; the spend panel does not read it yet",
    burn="unavailable: no quota series to derive from",
)


def files():
    """The database IS the file - one path per install, only if present."""
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    candidates = [os.path.join(xdg, "goose", "sessions", "sessions.db"),
                  os.path.expanduser("~/Library/Application Support/Block/goose/"
                                     "data/sessions/sessions.db")]
    for pat in ("/mnt/*/Users/*/AppData/Local/Block/goose/data/sessions/sessions.db",
                "/mnt/*/Users/*/AppData/Roaming/Block/goose/data/sessions/sessions.db"):
        candidates += glob.glob(pat)
    for r in og.config_roots():
        candidates.append(os.path.join(r, ".local/share/goose/sessions/sessions.db"))
    return [p for p in candidates if os.path.exists(p)]


def scan(path, since=0):
    """Sum the ledger. created_timestamp is epoch seconds, so `since` filters
    per usage event - finer than most agent sources manage."""
    t = og.blank()
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        rows = con.execute(
            "SELECT model, input_tokens, output_tokens, total_tokens, "
            "cache_read_tokens, cache_write_tokens FROM usage_ledger "
            "WHERE created_timestamp >= ?", (int(since),)).fetchall()
    finally:
        con.close()
    for model, tin, tout, total, cr, cw in rows:
        t["msgs"] += 1
        t["tin"] += tin or 0
        t["tout"] += tout or 0
        t["total"] += total or 0
        t["cache_read"] += cr or 0
        t["cache_write"] += cw or 0
        og.add_model(t, model or "unknown", out=tout or 0, total=total or 0, msgs=1)
    return t
