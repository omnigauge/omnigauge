# Providers

A provider teaches omnigauge about one source of usage. Adding one is a single file
in this directory — no core changes, no registration list to edit. Drop it in and
omnigauge finds it.

## The contract

```python
NAME     = "gemini"          # required · lowercase, becomes the CLI/agent label
KIND     = "agent"           # "agent" (a coding CLI) or "api" (a billed account)

def detect() -> bool:              # is this source present on this machine?
def files() -> list[str]:          # transcripts to count tokens from  (agent)
def scan(path, since=0) -> dict:   # parse ONE file -> token counts     (agent)

QUOTA = dict(                      # optional: how to read plan quota
    argv=["gemini"],               #   command to launch
    keys="/stats",                 #   what to type
    ready=r"…", done=r"…",         #   regexes: when to type, when it rendered
    expect=[("week", "all")],      #   windows that MUST parse, else PARTIAL
)
def parse_quota(screen) -> list[dict]:   # rendered screen -> quota rows

def api_usage(creds) -> dict:      # optional: billed spend/credits     (api)
```

Only what applies is needed. A tokens-only provider implements `detect`, `files`
and `scan`. A quota-only provider implements `detect`, `QUOTA` and `parse_quota`.

### `scan` returns

```python
dict(msgs=int, tin=int, tout=int, cache_read=int, cache_write=int,
     think=int, total=int, models={"model-name": dict(out=int, total=int, msgs=int)})
```

Use `omnigauge.blank()` for a zeroed dict and `omnigauge.add_model(t, name, ...)` to
attribute a model. Anything you leave at zero is simply not shown.

### `parse_quota` returns

```python
[dict(window="week", model="all", pct_used=94.0,
      raw_value="6% left", reset_at="23:04 on 19 Aug")]
```

**`pct_used` is always PERCENT CONSUMED.** If your vendor reports percent
*remaining* — Codex does — invert it here and put the vendor's original wording
in `raw_value`. omnigauge prints that string under the row so a reader can check the
conversion. Getting this backwards makes a nearly-exhausted account look healthy,
which is the single worst failure this tool can have.

## Rules that are not style preferences

**Fail loudly, never plausibly.** If parsing yields nothing, return `[]` and
omnigauge reports `NO QUOTA PARSED` and dumps the screen. If it yields *some* rows
but misses one you declared in `expect`, that is a `PARTIAL` and is treated as a
failure. A confident wrong number is worse than a missing one — a blanket
`except: continue` once hid a `NameError` on every Claude file and printed a
tidy row of zeros.

**Never invent a figure the vendor did not give you.** If a dollar balance is
only visible in a web console, report what the API does expose and say the rest
is console-only. omnigauge would rather show `—` than a number it cannot source.

**Prefer supported surfaces.** Reading a file the tool already writes, or driving
its own usage panel, will not break silently and does not depend on private
endpoints. Undocumented internal APIs are faster and are somebody else's
decision to make, not omnigauge's default.

**Assume nothing about the machine.** No hardcoded home directories, no assumed
usernames. On WSL a vendor may keep *two* stores — `~/.codex` and
`/mnt/c/Users/<someone>/.codex` — and searching one and declaring the other
absent is a real mistake that has already been made here. Use
`omnigauge.windows_homes()`.

**Cost is time.** `files()` and `scan()` run on every redraw. Codex rollouts
reach hundreds of megabytes and the wanted figure is the last line, so `scan`
reads from the tail — that took a redraw from 18s to 2s. If your source is
large, do the same.

## Worked example

`gemini.py` — a tokens-only provider, complete:

```python
import glob, io, json, os
import omnigauge

NAME, KIND = "gemini", "agent"

def detect():
    return bool(files())

def files():
    return glob.glob(os.path.expanduser("~/.gemini/sessions/*/*.json"))

def scan(path, since=0):
    t = omnigauge.blank()
    d = json.load(io.open(path, encoding="utf-8"))
    for turn in d.get("turns", []):
        u = turn.get("usage") or {}
        t["msgs"] += 1
        t["tin"]  += u.get("promptTokenCount", 0)
        t["tout"] += u.get("candidatesTokenCount", 0)
        t["total"]+= u.get("totalTokenCount", 0)
        omnigauge.add_model(t, d.get("model"), out=u.get("candidatesTokenCount", 0),
                         total=u.get("totalTokenCount", 0), msgs=1)
    return t
```

That is the whole thing. Drop it in `providers/`, run `omnigauge --doctor`, and it
appears.

## Submitting one

Include in the PR: which vendor and which files or command you read, a redacted
sample of the raw shape you parse, and a note on whether reading quota consumes
any of the user's allowance. That last one matters — for X it was verified
empirically that checking usage does *not* draw down the post cap, and that fact
belongs in the code, not in someone's memory.
