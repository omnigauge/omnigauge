#!/usr/bin/env bash
# omnigauge installer — copies the script and its providers. No sudo, no daemon.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$HOME/.local/bin}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/omnigauge"

mkdir -p "$DEST" "$DATA/providers"
install -m755 "$SRC/omnigauge" "$DEST/omnigauge"

# Providers must land somewhere the INSTALLED binary looks. It searches next to
# itself and in the data dir; ~/.local/bin/providers would be wrong to create,
# so the data dir is the install target.
if compgen -G "$SRC/providers/*.py" >/dev/null; then
  install -m644 "$SRC"/providers/*.py "$DATA/providers/"
  echo "providers: $(ls -1 "$DATA/providers"/*.py 2>/dev/null | wc -l) installed to $DATA/providers"
fi

echo "installed: $DEST/omnigauge"
command -v tmux >/dev/null || echo "note: tmux not found — quota scraping needs it (token counts work without)"
case ":$PATH:" in *":$DEST:"*) ;; *) echo "note: $DEST is not on PATH";; esac
echo "next:  omnigauge --doctor"
