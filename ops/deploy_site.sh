#!/usr/bin/env bash
# omnigauge.dev is nginx on John's origin box behind Cloudflare, and since 2026-08-21 its document
# root IS a checkout of this repository (/var/www/omnigauge-src/site); a cron on the box pulls
# main every five minutes. So a push to main is the deploy, and this script is the RECEIPT:
#
#   ops/deploy_site.sh            # verify through the domain: / byte-identical to site/index.html,
#                                 # FACTS.version = pyproject, robots/sitemap/llms 200, unknown path 404
#   ops/deploy_site.sh --pull     # ask the box to pull now instead of waiting for the cron, then verify
#
# release.yml runs the same version check after every release and fails loudly if the site lags.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ORIGIN="${ORIGIN:-gcda-root}"
CHECKOUT="${CHECKOUT:-/var/www/omnigauge-src}"

if [ "${1:-}" = "--pull" ]; then
  ssh "$ORIGIN" "git -C $CHECKOUT pull -q --ff-only && git -C $CHECKOUT log --oneline -1"
fi

tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
curl -fsS --max-time 20 -H 'Cache-Control: no-cache' https://omnigauge.dev/ -o "$tmp"
if cmp -s "$tmp" "$ROOT/site/index.html"; then echo "live / is byte-identical to site/index.html"; else echo "live / DIFFERS from site/index.html (the box has not pulled this commit yet?)"; exit 1; fi
want="$(python3 -c "import re;print(re.search(r'^version\s*=\s*\"([^\"]+)\"',open('$ROOT/pyproject.toml').read(),re.M).group(1))")"
got="$(grep -o '"version":"[^"]*"' "$tmp" | head -1 | cut -d'"' -f4)"
[ "$got" = "$want" ] && echo "live FACTS.version $got = pyproject $want" || { echo "live FACTS.version '$got' != pyproject '$want'"; exit 1; }
for p in robots.txt sitemap.xml llms.txt; do code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://omnigauge.dev/$p")"; [ "$code" = 200 ] && echo "/$p 200" || { echo "/$p $code"; exit 1; }; done
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://omnigauge.dev/no-such-path")"; [ "$code" = 404 ] && echo "/no-such-path 404" || { echo "/no-such-path $code (expected 404)"; exit 1; }
