"""DeepSeek — API spend provider.

GET /user/balance returns per-currency balances and whether the balance can
still pay for calls. There is no official CLI, so this is spend-panel only.

Shape verified against api-docs.deepseek.com 2026-08-15. Not yet exercised
with a live key - errors surface loudly in the panel, never as zeros.

Key: creds file `deepseek_api_key` or env DEEPSEEK_API_KEY.
"""
import os

import omnigauge as og

NAME = "deepseek"
KIND = "api"

CAPS = dict(
    tokens="unavailable: the balance endpoint reports money, not tokens",
    quota="unavailable: a prepaid balance, not a subscription window",
    reset="unavailable: balances deplete; there is no window to reset",
    models="unavailable: not broken out by the balance endpoint",
    lifetime="unavailable: only the current balance is exposed",
    spend="obtained: total balance in the account's currency",
    burn="unavailable: no series is kept for spend sources",
)


def _key(creds):
    return (creds or {}).get("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY", "")


def detect():
    # no-arg per the contract; reads the creds file so a key stored
    # via --setup counts as configured, not just env
    return bool(_key(og.load_creds()))


def api_usage(creds):
    out = dict(source=NAME, balance=None, currency=None, note=None, err=None)
    key = _key(creds)
    if not key:
        out["err"] = "no key - set deepseek_api_key via omnigauge --setup"
        return out
    d, err = og._get("https://api.deepseek.com/user/balance", key)
    if err:
        out["err"] = err
        return out
    infos = (d or {}).get("balance_infos") or []
    if not infos:
        out["err"] = "no balance_infos in reply"
        return out
    first = infos[0]
    try:
        out["balance"] = round(float(first.get("total_balance")), 2)
    except (TypeError, ValueError):
        out["err"] = f"unreadable total_balance: {first.get('total_balance')!r}"
        return out
    out["currency"] = first.get("currency")
    if d.get("is_available") is False:
        out["note"] = "balance too low for API calls"
    return out
