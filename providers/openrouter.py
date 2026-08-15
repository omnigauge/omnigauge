"""OpenRouter — API spend provider.

One aggregator key fronts dozens of models, which makes this the best value
per unit of work in the spend panel. GET /api/v1/auth/key returns the current
key's own usage and limit (credit dollars) and works with the key you already
inference with; /credits exists but needs a management key, so it is not used
here.

Shape verified against openrouter.ai/docs 2026-08-15, then LIVE-verified the
same day: a real key authenticated and the panel showed its true $0.00.
Errors surface loudly in the panel, never as zeros.

Key: creds file `openrouter_api_key` or env OPENROUTER_API_KEY.
"""
import os

import omnigauge as og

NAME = "openrouter"
KIND = "api"

CAPS = dict(
    tokens="unavailable: the key endpoint reports credit dollars, not tokens",
    quota="obtained: usage against the key's credit limit, when one is set",
    reset="unavailable: credits deplete; there is no window to reset",
    models="unavailable: an aggregator; models are chosen per request",
    lifetime="obtained: usage is the key's lifetime credit spend",
    spend="obtained: credit dollars used, from the key's own endpoint",
    burn="unavailable: no series is kept for spend sources",
)


def _key(creds):
    return (creds or {}).get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY", "")


def detect():
    # no-arg per the contract; reads the creds file so a key stored
    # via --setup counts as configured, not just env
    return bool(_key(og.load_creds()))


def api_usage(creds):
    out = dict(source=NAME, spend_usd=None, used=None, cap=None, pct=None,
               unit="credits", err=None)
    key = _key(creds)
    if not key:
        out["err"] = "no key - set openrouter_api_key via omnigauge --setup"
        return out
    d, err = og._get("https://openrouter.ai/api/v1/auth/key", key)
    if err:
        out["err"] = err
        return out
    data = (d or {}).get("data") or {}
    usage, limit = data.get("usage"), data.get("limit")
    if isinstance(usage, (int, float)):
        out["spend_usd"] = round(float(usage), 4)
    if isinstance(limit, (int, float)) and limit:
        out["used"], out["cap"] = usage, limit
        out["pct"] = float(usage) / float(limit) * 100
    # limit null means uncapped - spend-only row, which the panel renders fine
    return out
