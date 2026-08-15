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
  ... add --post to actually send. Without it you get a dry run.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request

POST_URL = "https://api.x.com/2/tweets"
LIMIT = 280
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
    ap.add_argument("kind", choices=["release", "provider", "text"])
    ap.add_argument("name")
    ap.add_argument("--notes", default="")
    ap.add_argument("--post", action="store_true",
                    help="actually send it; without this you get a dry run")
    a = ap.parse_args()

    text = compose(a)
    n = len(text)
    print(f"\n{'─'*60}\n{text}\n{'─'*60}\n  {n}/{LIMIT} characters")
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
