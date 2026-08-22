"""Aider - agent provider.

Verified on a real install 2026-08-15. Aider writes .aider.chat.history.md
into the PROJECT directory, not a home directory - which breaks the one-home
assumption every other agent provider gets to make. There is no registry of
projects, so this provider reads the roots you name:

    OMNIGAUGE_AIDER_DIRS=/path/one:/path/two

and searches each for .aider.chat.history.md, recursively. Unset means no
files - an honest absence on the board, never a guessed scan of your disk.

The numbers are the vendor's own: aider prints a per-exchange line into the
history file - "Tokens: 797 sent, 1 received. Cost: $0.00012 message" - with
k-suffixed figures on larger exchanges ("8.6k sent"). Sessions carry a local
timestamp header, so --since filters at session resolution.
"""
import glob
import io
import os
import re
import time

import omnigauge as og

NAME = "aider"
KIND = "agent"

CAPS = dict(
    tokens="obtained: aider's own token lines; roots via OMNIGAUGE_AIDER_DIRS",
    quota="unavailable: key-based; there is no plan window to read",
    reset="unavailable: no plan window, nothing resets",
    models="obtained: per session header, at session resolution",
    lifetime="obtained",
    spend="available: cost lines exist; the spend panel does not read them yet",
    burn="unavailable: no quota series to derive from",
)

_SESSION_RX = re.compile(r"^# aider chat started at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_MODEL_RX = re.compile(r"^> Model: (\S+)")
_TOKENS_RX = re.compile(r"Tokens:\s*([\d.,]+k?)\s*sent,\s*([\d.,]+k?)\s*received", re.I)


def files():
    roots = os.environ.get("OMNIGAUGE_AIDER_DIRS", "")
    out = []
    for root in filter(None, roots.split(os.pathsep)):
        root = os.path.expanduser(root)
        out += glob.glob(os.path.join(root, ".aider.chat.history.md"))
        out += glob.glob(os.path.join(root, "**", ".aider.chat.history.md"),
                         recursive=True)
    return sorted(set(out))


def _num(s):
    """'797' -> 797, '8.6k' -> 8600. Aider humanizes larger figures."""
    s = s.replace(",", "")
    if s.endswith("k"):
        return int(float(s[:-1]) * 1000)
    return int(float(s))


def scan(path, since=0):
    t = og.blank()
    model = None
    session_ok = True          # a file may predate the session-header format
    for line in io.open(path, errors="replace"):
        m = _SESSION_RX.match(line)
        if m:
            try:
                epoch = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
                session_ok = not since or epoch >= since
            except ValueError:
                session_ok = True   # unreadable stamp: include, never drop
            continue
        m = _MODEL_RX.match(line)
        if m:
            model = m.group(1)
            continue
        if not session_ok:
            continue
        m = _TOKENS_RX.search(line)
        if m:
            sent, received = _num(m.group(1)), _num(m.group(2))
            t["msgs"] += 1
            t["tin"] += sent
            t["tout"] += received
            t["total"] += sent + received
            og.add_model(t, model or "unknown", out=received,
                         total=sent + received, msgs=1)
    return t
