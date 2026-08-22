"""Moonshot / Kimi - API spend provider.

The lab behind Kimi. GET /v1/users/me/balance returns available, voucher and
cash balances; available <= 0 blocks inference, so that is the number shown.

Two independent platforms share this API shape: platform.kimi.ai
(api.moonshot.ai, the default here) and the Chinese platform.kimi.com
(api.moonshot.cn) - keys from one 401 on the other. Point MOONSHOT_BASE at
.cn if that is where your key lives. No currency is asserted because the
response does not state one and the two platforms bill differently.

Shape verified against platform.kimi.ai/docs 2026-08-15. Not yet exercised
with a live key - errors surface loudly in the panel, never as zeros.

Key: creds file `moonshot_api_key` or env MOONSHOT_API_KEY.
"""
import os

import omnigauge as og

NAME = "moonshot"
KIND = "api"

CAPS = dict(
    tokens="unavailable: the balance endpoint reports money, not tokens",
    quota="unavailable: a prepaid balance, not a subscription window",
    reset="unavailable: balances deplete; there is no window to reset",
    models="unavailable: not broken out by the balance endpoint",
    lifetime="unavailable: only the current balance is exposed",
    spend="obtained: available balance (voucher + cash)",
    burn="unavailable: no series is kept for spend sources",
)


def _key(creds):
    return (creds or {}).get("moonshot_api_key") or os.environ.get("MOONSHOT_API_KEY", "")


def detect():
    # no-arg per the contract; reads the creds file so a key stored
    # via --setup counts as configured, not just env
    return bool(_key(og.load_creds()))


def api_usage(creds):
    out = dict(source=NAME, balance=None, currency=None, note=None, err=None)
    key = _key(creds)
    if not key:
        out["err"] = "no key - set moonshot_api_key via omnigauge --setup"
        return out
    base = os.environ.get("MOONSHOT_BASE", "https://api.moonshot.ai")
    d, err = og._get(base + "/v1/users/me/balance", key)
    if err:
        out["err"] = err
        return out
    if not (d or {}).get("status") or (d or {}).get("code") != 0:
        out["err"] = f"unexpected reply: code={d.get('code')} status={d.get('status')}"
        return out
    data = d.get("data") or {}
    avail = data.get("available_balance")
    if not isinstance(avail, (int, float)):
        out["err"] = "no available_balance in reply"
        return out
    out["balance"] = round(float(avail), 2)
    if isinstance(data.get("cash_balance"), (int, float)) and data["cash_balance"] < 0:
        out["note"] = "cash balance is negative"
    return out
