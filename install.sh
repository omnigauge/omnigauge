#!/usr/bin/env bash
# omnigauge installer — copies the script onto your PATH. No sudo, no daemon.
set -euo pipefail
DEST="${1:-$HOME/.local/bin}"
mkdir -p "$DEST"
install -m755 "$(dirname "$0")/omnigauge" "$DEST/omnigauge"
echo "installed: $DEST/omnigauge"
command -v tmux >/dev/null || echo "note: tmux not found — quota scraping needs it (token counts work without)"
case ":$PATH:" in *":$DEST:"*) ;; *) echo "note: $DEST is not on PATH";; esac
echo "next:  omnigauge --refresh"
