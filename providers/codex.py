"""OpenAI Codex - reference provider.

Mirrors the built-in and overrides it at load, exactly like claude.py. Two
things here are worth copying into any provider for a similar tool:

The scan reads from the END of the file. Codex rollouts reach hundreds of
megabytes and the wanted figure is the last cumulative total - scanning
forward made a redraw take ~18s across a large corpus; the tail read took it
to ~2s. If your source is large, do the same.

Codex reports percent REMAINING and this provider inverts it to percent
consumed, keeping the vendor's own wording in raw_value so the board can show
the conversion. Getting this backwards makes a nearly exhausted account look
healthy - the single worst failure this tool can have.
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
    """WSL keeps TWO stores - ~/.codex and the Windows-side install. Searching
    one and declaring the other absent is a mistake that has been made here."""
    out = []
    for h in og.all_homes(".codex"):
        out += glob.glob(f"{h}/sessions/**/*.jsonl", recursive=True)
    return out


# ── token counting ──────────────────────────────────────────────────────────

_FIELDS = (("tin", "input_tokens"), ("tout", "output_tokens"),
           ("cache_read", "cached_input_tokens"),
           ("think", "reasoning_output_tokens"), ("total", "total_tokens"))


def _once(seq):
    """Each event once: the gap walk's blocks overlap where a long line holds a
    block's offset, and a repeated, earlier cumulative read as a counter restart
    counted the whole cumulative again (Oct 12: 26.18B credited to a window, against
    a lifetime of 1.15B). Kept identical to the builtin's _codex_once."""
    seen, out = set(), []
    for ep, u in seq:
        key = (ep, json.dumps(u, sort_keys=True))
        if key in seen: continue
        seen.add(key)
        out.append((ep, u))
    return out


def _spend(seq, since, fields, inherited=None, hours=None):
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
    prev, fresh, first_ep = None, False, None
    for ep, u in seq:
        # V241-CLI-02: a cutoff inside the parent's replay is still replay.
        until = (inherited or {}).get("_replay_until")
        if ep is not None and until is not None and ep <= until:
            prev = u
            continue
        if ep is None or ep >= since:
            if prev is None:
                # No earlier reading to subtract, so this cumulative IS the spend
                # so far. That is the whole-file-inside-the-window case, and the
                # lifetime case where since is 0.
                fresh, first_ep = True, ep
                for k, f in fields:
                    acc[k] += u.get(f, 0)
                og.hour_add(hours, ep, **{k: u.get(f, 0) for k, f in fields})
            else:
                own = u.get("_own") if isinstance(u.get("_own"), dict) else None
                step = {}
                for k, f in fields:
                    c, p = u.get(f, 0), prev.get(f, 0)
                    # c < p means it restarted: then this call's own usage where the
                    # line records it (a restart can itself start from an inherited
                    # cumulative), else the new cumulative
                    step[k] = (own.get(f, 0) if own else c) if c < p else c - p
                    acc[k] += step[k]
                og.hour_add(hours, ep, **step)
        prev = u
    # A sum begun from a first reading holds what the rollout inherited from the
    # thread it was forked from (a paginated fork's first cumulative, a legacy
    # fork's replay), which that thread's own file counts: it comes off, unless
    # the sum never reached it (the counter restarted below it before then).
    tk = next((k for k, f in fields if f == "total_tokens"), None)
    if fresh and inherited and tk and acc[tk] >= inherited.get("total_tokens", 0):
        for k, f in fields:
            acc[k] = max(0, acc[k] - inherited.get(f, 0))
        # (in the hours, off the hour of that first reading, where it was put: kept identical to the builtin)
        h = (hours or {}).get(int(first_ep // 3600)) if first_ep is not None else None
        if h is not None:
            for k, f in fields:
                h[k] = max(0, h[k] - inherited.get(f, 0))
    return acc


def _calls(seq, since, inherited=None, hours=None):
    """Each changed cumulative is one model call in the window. A legacy
    fork's initial replay belongs to its parent, not to this thread."""
    # V241-CLI-01/02: inheritance is an initial replay, never a permanent
    # minimum. Paginated forks have no replay readings to exclude at all.
    legacy = "_replay_until" in (inherited or {})
    until = (inherited or {}).get("_replay_until")
    floor = (inherited or {}).get("total_tokens", 0) if legacy else 0
    n, prev = 0, None
    for ep, u in seq:
        c = u.get("total_tokens", 0)
        replay = legacy and ((ep is not None and until is not None and ep <= until)
                             or ((ep is None or until is None) and floor and c <= floor))
        if floor and c > floor: floor = 0
        if ((ep is None or ep >= since) and not replay
                and (prev is None or c != prev.get("total_tokens", 0))):
            n += 1
            og.hour_add(hours, ep, msgs=1)
        prev = u
    return n


def _call_events(path, size):
    """Stream the readings missing from a tail-only count, without holding
    a large transcript in memory. Lifetime results use the per-file cache."""
    # V241-CLI-03: a final cumulative holds tokens, not how many calls made it.
    with open(path, "rb", buffering=1 << 20) as fh:
        while fh.tell() < size:
            raw = fh.readline(size - fh.tell())
            if not raw: break
            if b'"total_token_usage"' in raw:
                yield from _events(raw.decode("utf-8", "replace"))


def _events(text):
    """(epoch, totals) for every token_count event in a text block."""
    out = []
    for line in text.splitlines():
        if '"total_token_usage"' not in line: continue
        try: d = json.loads(line)
        except ValueError: continue
        u = og._dig(d, "total_token_usage")
        if u:
            own = og._dig(d, "last_token_usage")
            if isinstance(u, dict) and isinstance(own, dict): u = dict(u, _own=own)
            out.append((og._epoch(d.get("timestamp", "")), u))
    return out


def _inherited(path, size, head=1 << 28):
    """What a rollout inherits from the thread it was forked from, which that thread's
    own file already counts: the cumulative just before this rollout's first call of
    its own, or None. A sub-agent's thread (session_meta forked_from_id) starts from
    its parent's history, and Codex has written that two ways. Paginated: the first
    usage line's cumulative already holds the parent's (Aug 2026: ~3.2B carried, ~80k
    the call's own), so the inherited part is that cumulative less the call's own
    usage. Legacy: the parent's history is replayed into the new file as it is made,
    usage lines and all (Aug 14: ~4,800 lines written in 3 s, 4,578 of them the
    parent's exact cumulatives), so the inherited part is the last cumulative of that
    burst, which ends at the first pause of over a second (the fork's own first call,
    its parent's whole history in context, takes longer). Summing each file's last
    cumulative counted 3.40T on Oct 12 where OpenAI's own page showed 91.7B. The first
    usage line can come megabytes in, a paginated fork's file holding its parent's
    history first (Jul 30-31 and Sep 5: 5-6MB in, 96B uncounted below 4MB), so the
    head is read up to 256MB, stopping at that line. Kept identical to the builtin's _codex_inherited."""
    try:
        # a large buffer: a Windows folder seen from WSL answers each read slowly, and
        # line by line through the default 8KB buffer ran ~40x slower (8 MB/s)
        with open(path, "rb", buffering=1 << 20) as fh:
            first = fh.readline()
            try: meta = json.loads(first).get("payload") or {}
            except (ValueError, AttributeError): meta = {}
            legacy = isinstance(meta, dict) and bool(meta.get("forked_from_id")) and meta.get("history_mode") == "legacy"
            last_raw, before, read = None, None, len(first)
            for raw in fh:
                read += len(raw)
                if legacy:
                    m = re.match(rb'\{"timestamp":\s*"([^"]+)"', raw)
                    ep = og._epoch(m.group(1).decode("utf-8", "replace")) if m else None
                    if ep is not None:
                        if before is not None and ep - before > 1.0: break
                        before = ep
                elif read > head:
                    return None
                if b'"total_token_usage"' not in raw: continue
                if legacy:
                    last_raw = raw    # read once the burst is over
                    continue
                ev = _events(raw.decode("utf-8", "replace"))
                if not ev: continue
                u = ev[-1][1]
                own = u.get("_own")
                if not isinstance(own, dict): return None
                t, o = u.get("total_tokens", 0), own.get("total_tokens", 0)
                if not isinstance(t, (int, float)) or not isinstance(o, (int, float)) or t <= o: return None
                return {f: u.get(f, 0) - own.get(f, 0) for _k, f in _FIELDS
                        if isinstance(u.get(f, 0), (int, float)) and isinstance(own.get(f, 0), (int, float))}
            ev = _events(last_raw.decode("utf-8", "replace")) if legacy and last_raw else None
            if not ev: return None
            last = ev[-1][1]
            return dict({f: last.get(f, 0) for _k, f in _FIELDS
                         if isinstance(last.get(f, 0), (int, float))}, _replay_until=ev[-1][0])
    except OSError:
        return None


def _block(fh, size, off, nbytes=1 << 18):
    """A line-aligned text block starting at off."""
    fh.seek(max(0, off))
    if off > 0: fh.readline()
    return fh.read(min(nbytes, size)).decode("utf-8", "replace")


def scan(path, since=0, hours=None):
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
                    # The gap between the located edge and the tail was never
                    # read - a counter restart hidden there was invisible to
                    # the step-sum. Walk ONLY that in-window stretch forward
                    # in 512KB steps: bounded by what the window holds, never
                    # the whole file. Kept identical to the builtin.
                    # Blocks are line-aligned, so a walk can overlap the
                    # tail by up to one block: stop the gap at the tail's
                    # FIRST stamped event, or those events count twice.
                    gap, first_tail = [], stamped[0][0]
                    off, tail_off = lo, size - (1 << 20)
                    while off < tail_off:
                        blk = _block(fh, size, off, (1 << 19))
                        if not blk: break
                        gap += [(ep, u) for ep, u in _events(blk)
                                if ep is not None and since <= ep < first_tail]
                        off += (1 << 19)
                    seq = [(since - 1, base)] + gap + stamped
    # Always step-sum. Falling back to `last - base` when no baseline was found
    # meant a rollout sitting entirely inside the window reported only its final
    # cumulative - the spend since its LAST restart, everything before it dropped.
    # Window and lifetime were wrong in the same direction, so the
    # window-cannot-exceed-lifetime invariant never noticed.
    inherited = _inherited(path, size)
    # The per-hour view (--days) needs every reading of the file (kept identical to the builtin): a tail's first
    # reading carries all the history before it, which would fall into one hour.
    full = None
    if hours is not None and not since:
        full = list(_call_events(path, size)) if size > (1 << 20) else events
    once = _once(full if full is not None else (seq if seq else events))
    for key, val in _spend(once, since, _FIELDS, inherited, hours).items():
        t[key] = val
    # Its messages are its model calls, as Claude's replies are (it was 1 a
    # file: a conversation counted as one message)
    # V241-CLI-03: when no window baseline was found, `once` can hold only
    # the tail. Count the missing prefix too; a zero count invents no reply.
    calls = once if full is not None else (_call_events(path, size) if seq is None and size > (1 << 20) else once)
    t["msgs"] = _calls(calls, since, inherited, hours)
    og.add_model(t, model or "unknown", out=t["tout"], total=t["total"], msgs=t["msgs"])
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
    """% LEFT natively - inverted to % USED here, vendor wording preserved."""
    rows = []
    for line in screen.splitlines():
        m = re.search(r"(.*?)Weekly limit:\s*\[[^\]]*\]\s*(\d+)%\s*left\s*\(resets\s+([^)]+)\)", line)
        if not m: continue
        label = re.sub(r"[│|]", "", m.group(1)).strip() or "all"
        left = float(m.group(2))
        rows.append(dict(window="week", model=label, pct_used=100.0 - left,
                         raw_value=f"{int(left)}% left", reset_at=m.group(3).strip()))
    return rows
