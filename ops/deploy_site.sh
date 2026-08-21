#!/usr/bin/env bash
# Deploy site/ to the origin box and verify it THROUGH THE DOMAIN.
#
# omnigauge.dev is nginx on John's origin box behind Cloudflare (one home; the Pages project is
# deleted so it cannot silently re-take the hostname). Nothing deploys on push: this script is the
# deploy, and release.yml fails loudly when the live site does not serve the released version.
#
#   ops/deploy_site.sh            # scp the four files, then verify
#   ops/deploy_site.sh --verify   # verify only: live / byte-identical to site/index.html, FACTS.version
#
# Target alias and path are the documented ones (site/README.md); override with ORIGIN and WEBROOT.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ORIGIN="${ORIGIN:-gcda-root}"
WEBROOT="${WEBROOT:-/var/www/omnigauge}"
FILES=(index.html robots.txt sitemap.xml llms.txt)

if [ "${1:-}" != "--verify" ]; then
  for f in "${FILES[@]}"; do test -f "$ROOT/site/$f" || { echo "missing site/$f"; exit 1; }; done
  python3 "$ROOT/ops/gen_legend.py" --verify
  scp -q "${FILES[@]/#/$ROOT/site/}" "$ORIGIN:$WEBROOT/"
  echo "copied ${FILES[*]} -> $ORIGIN:$WEBROOT/"
fi

# verification is the deploy's receipt, and it reads the domain, not the box
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
curl -fsS --max-time 20 -H 'Cache-Control: no-cache' https://omnigauge.dev/ -o "$tmp"
if cmp -s "$tmp" "$ROOT/site/index.html"; then echo "live / is byte-identical to site/index.html"; else echo "live / DIFFERS from site/index.html"; exit 1; fi
want="$(python3 -c "import re;print(re.search(r'^version\s*=\s*\"([^\"]+)\"',open('$ROOT/pyproject.toml').read(),re.M).group(1))")"
got="$(grep -o '"version":"[^"]*"' "$tmp" | head -1 | cut -d'"' -f4)"
[ "$got" = "$want" ] && echo "live FACTS.version $got = pyproject $want" || { echo "live FACTS.version '$got' != pyproject '$want'"; exit 1; }
for p in robots.txt sitemap.xml llms.txt; do code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://omnigauge.dev/$p")"; [ "$code" = 200 ] && echo "/$p 200" || { echo "/$p $code"; exit 1; }; done
