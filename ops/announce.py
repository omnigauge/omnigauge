#!/usr/bin/env python3
"""Post OmniGauge release announcements to X.

Three habits make a posting bot safe to leave installed, and this one keeps all
three: it is OFF unless explicitly switched on, a failure returns rather than
raises so it can never take down its caller, and the text is clamped before it
is sent rather than rejected after.

It deliberately does NOT live inside the installed tool. `install.sh` copies
only `omnigauge` and `providers/*.py`, so nothing here reaches a user's machine.
Somebody installing a usage meter did not ask for a tweet bot in it.

  ANNOUNCEMENTS ONLY — never post a reading.

Quota percentages are the operator's private consumption. A bot that tweets
"87% of weekly limit" is publishing personal data about whoever is running it.
This script has no access to the usage database on purpose.

Auth is OAuth 1.0a user context. A bearer token CANNOT post — bearer is
app-only and read-only for this endpoint. Four values are required, and the app
must be set to Read and Write in the developer portal BEFORE the access token
is generated; a token minted under Read-only stays read-only and 403s.

  OMNIGAUGE_X_API_KEY          consumer key
  OMNIGAUGE_X_API_SECRET       consumer secret
  OMNIGAUGE_X_ACCESS_TOKEN     access token
  OMNIGAUGE_X_ACCESS_SECRET    access token secret

Usage:
  announce.py release v0.2.0 --notes "Gemini provider, lifetime totals"
  announce.py provider gemini
  announce.py text "..."
  announce.py draft "the first release" --n 3
  ... add --post to actually send. Without it you get a dry run.

`draft` asks a model for candidate posts in the project's voice and PRINTS
them - it never sends. Pick one, edit it, then post it as `text ... --post`.
It uses OMNIGAUGE_DRAFT_BASE/_KEY/_MODEL when set, else OPENAI_API_KEY
against api.openai.com, else AI_GATEWAY_API_KEY against the Vercel AI
Gateway.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request

POST_URL = "https://api.x.com/2/tweets"
LIMIT = 280
_URL_RX = re.compile(r"https?://\S+")


def x_len(t):
    """Length as X counts it: every URL is 23 characters (t.co wrapping),
    whatever its real length. Counting raw len() refused legitimate posts -
    the repo link alone is 40 characters that X bills as 23."""
    return len(_URL_RX.sub("x" * 23, t))
REPO = "https://github.com/omnigauge/omnigauge"

ENV = ("OMNIGAUGE_X_API_KEY", "OMNIGAUGE_X_API_SECRET",
       "OMNIGAUGE_X_ACCESS_TOKEN", "OMNIGAUGE_X_ACCESS_SECRET")


def _q(s):
    """OAuth percent-encoding. Stricter than quote_plus: space is %20 and
    -._~ are the only unreserved punctuation. Getting this wrong yields a
    401 with no hint about which character broke the signature."""
    return urllib.parse.quote(str(s), safe="-._~")


def _oauth_params(creds, nonce=None, stamp=None):
    """The six oauth_* protocol params. nonce/stamp are injectable so the
    signing math can be asserted against the published test vector."""
    ck, cs, tok, ts = creds
    return {
        "oauth_consumer_key": ck,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": stamp or str(int(time.time())),
        "oauth_token": tok,
        "oauth_version": "1.0",
    }


def _base_string(method, url, params):
    """RFC 5849 signature base: METHOD & enc(url) & enc(sorted k=v pairs)."""
    norm = "&".join(f"{_q(k)}={_q(params[k])}" for k in sorted(params))
    return f"{method}&{_q(url)}&{_q(norm)}"


def _auth_header(method, url, creds, extra_params=None, nonce=None, stamp=None):
    # The JSON body is NOT part of the signature base for v2 — only oauth
    # params and any query/form params. Including the body is the other
    # common 401. extra_params exists for form-encoded endpoints and for the
    # documented test vector; the v2 JSON path passes none.
    if "?" in url:
        raise ValueError("query strings are not signed here - "
                         "pass query params via extra_params instead")
    ck, cs, tok, ts = creds
    p = _oauth_params(creds, nonce=nonce, stamp=stamp)
    base = _base_string(method, url, dict(p, **(extra_params or {})))
    key = f"{_q(cs)}&{_q(ts)}".encode()
    sig = base64.b64encode(hmac.new(key, base.encode(), hashlib.sha1).digest()).decode()
    p["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{_q(k)}="{_q(v)}"' for k, v in sorted(p.items()))


def post(text):
    """Send it. Returns the tweet id, or None — never raises at the caller."""
    creds = tuple(os.getenv(k, "").strip() for k in ENV)
    missing = [k for k, v in zip(ENV, creds) if not v]
    if missing:
        print(f"  not sent — missing: {', '.join(missing)}", file=sys.stderr)
        return None
    body = json.dumps({"text": text}).encode()
    req = urllib.request.Request(POST_URL, data=body, method="POST")
    req.add_header("Authorization", _auth_header("POST", POST_URL, creds))
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return (json.load(r).get("data") or {}).get("id")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        hint = ""
        if e.code == 403:
            hint = ("\n  403 usually means the access token was generated while "
                    "the app was Read-only. Set the app to Read and Write, then "
                    "REGENERATE the token — changing the permission alone does "
                    "not upgrade an existing one.")
        print(f"  not sent — HTTP {e.code}: {detail}{hint}", file=sys.stderr)
    except Exception as e:
        print(f"  not sent — {e}", file=sys.stderr)
    return None


VOICE = (
    "You write posts for @OmniGauge, an open-source terminal dashboard that "
    "shows plan quota, token volume, burn rate and reset time for Claude Code, "
    "Codex and Grok CLIs. Voice: plain, dry, precise, occasionally wry. No "
    "hype, no emoji, no hashtags, no exclamation marks. Facts you may use: it "
    "reads local files the CLIs already write; no API keys; no telemetry; it "
    "normalizes every vendor's counter to percent consumed (Codex reports "
    "percent remaining and gets inverted); it forecasts whether you run dry "
    "BEFORE the window resets; one Python file, stdlib only, MIT. "
    "Repo: https://github.com/omnigauge/omnigauge")


def _draft_endpoint():
    """Explicit env wins; else OpenAI direct; else the AI Gateway. Direct
    beats gateway on purpose: a funded OpenAI account outranks a gateway key
    that may be free-tier and rate-limited - which is exactly how the first
    draft ever attempted here died."""
    base = os.environ.get("OMNIGAUGE_DRAFT_BASE")
    key = os.environ.get("OMNIGAUGE_DRAFT_KEY")
    model = os.environ.get("OMNIGAUGE_DRAFT_MODEL")
    if not (base and key):
        if os.environ.get("OPENAI_API_KEY"):
            base, key = "https://api.openai.com/v1", os.environ["OPENAI_API_KEY"]
            model = model or "gpt-5.5"
        elif os.environ.get("AI_GATEWAY_API_KEY"):
            base, key = "https://ai-gateway.vercel.sh/v1", os.environ["AI_GATEWAY_API_KEY"]
            model = model or "openai/gpt-5.5"
    return base, key, model or "gpt-5.5"


def _candidates(text):
    """Split on --- lines, clamp to the X-counted limit, dedupe, strip
    wrapping quotes. A candidate over the limit is dropped rather than
    truncated - a cut-off post is worse than one fewer option - but the
    drop is COUNTED, because zero survivors must be loud, not silent."""
    out, dropped = [], 0
    for block in text.split("---"):
        t = block.strip().strip('"').strip()
        if not t or t in out:
            continue
        if x_len(t) > LIMIT:
            dropped += 1
            continue
        out.append(t)
    return out, dropped


def draft(topic, n=3):
    """Candidate posts from a model. Prints and returns them; NEVER sends."""
    base, key, model = _draft_endpoint()
    if not key:
        print("  no AI_GATEWAY_API_KEY or OPENAI_API_KEY in the environment",
              file=sys.stderr)
        return []
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": VOICE},
            {"role": "user", "content":
                f"Write {n} candidate posts about: {topic}. Each complete post "
                "under 270 characters including the repo link. Separate the "
                "candidates with a line containing only --- . No numbering, "
                "no surrounding quotes, no preamble."}],
    }).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body, method="POST")
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            text = json.load(r)["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        print(f"  draft failed - HTTP {e.code} from {model}: "
              f"{e.read().decode(errors='replace')[:300]}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  draft failed - {type(e).__name__}: {e}", file=sys.stderr)
        return []
    cands, dropped = _candidates(text)
    if dropped:
        print(f"  ({dropped} candidate(s) over {LIMIT} X-counted chars, dropped)",
              file=sys.stderr)
    if not cands:
        print(f"  model returned no usable candidates - raw reply began: "
              f"{text.strip()[:120]!r}", file=sys.stderr)
    return cands


def compose(a):
    if a.kind == "release":
        head = f"OmniGauge {a.name}"
        notes = f"\n\n{a.notes}" if a.notes else ""
        return f"{head}{notes}\n\n{REPO}/releases"
    if a.kind == "provider":
        return (f"OmniGauge now reads {a.name}.\n\n"
                f"One command for every AI plan you are burning through — "
                f"quota, tokens, and when it resets.\n\n{REPO}")
    return a.name


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("kind", choices=["release", "provider", "text", "draft"])
    ap.add_argument("name")
    ap.add_argument("--notes", default="")
    ap.add_argument("--n", type=int, default=3, help="draft: how many candidates")
    ap.add_argument("--post", action="store_true",
                    help="actually send it; without this you get a dry run")
    a = ap.parse_args()

    if a.kind == "draft":
        if a.post:
            print("  draft never posts. Pick one, then: announce.py text '...' --post",
                  file=sys.stderr)
        cands = draft(a.name, a.n)
        for i, c in enumerate(cands, 1):
            print(f"\n{'─'*60}\n[{i}]  ({x_len(c)}/{LIMIT} X-counted chars)\n{c}")
        print(f"\n{'─'*60}\n  {len(cands)} candidate(s). Post one with: "
              "announce.py text '<the text>' --post\n" if cands else "")
        return 0 if cands else 1

    text = compose(a)
    n = x_len(text)
    print(f"\n{'─'*60}\n{text}\n{'─'*60}\n  {n}/{LIMIT} characters as X counts them")
    if n > LIMIT:
        print("  too long — not sent", file=sys.stderr)
        return 1
    if not a.post:
        print("  dry run. add --post to send.\n")
        return 0
    tid = post(text)
    print(f"  posted — https://x.com/OmniGauge/status/{tid}\n" if tid else "")
    return 0 if tid else 1


if __name__ == "__main__":
    sys.exit(main())
