#!/usr/bin/env python3
"""Render the README's board block to assets/readme-board.png.

Registries and browsers do not share our font, and box-drawing glyphs from a
fallback face draw the frame dashed and uneven (PyPI showed exactly that). So the
README shows a rendering of the block - JetBrains Mono, the site's ink palette -
and keeps the text itself under <details>. Run after editing the block:

    python3 ops/render_readme_board.py

Needs Pillow and a JetBrains Mono TTF (path below or $JBMONO_TTF). The palette
is the site's; the colour rules mirror the CLI's: rose past 90%, healthy hueless.
"""
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.environ.get("JBMONO_TTF") or next(
    (p for p in (
        os.path.expanduser("~/.local/share/fonts/JetBrainsMono-Regular.ttf"),
        "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
        "/usr/share/fonts/TTF/JetBrainsMono-Regular.ttf",
    ) if os.path.exists(p)),
    "JetBrainsMono-Regular.ttf",
)
FIELD, WHITE, GRAY, DIM = (9, 18, 40), (219, 227, 242), (138, 152, 182), (118, 134, 170)
RED, GREEN, CYAN, EDGE = (196, 112, 112), (110, 168, 136), (90, 166, 201), (34, 52, 95)
FRAME = set("╭╮╰╯│─━┈")


def block():
    s = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    m = re.search(r"<summary>the same board as text</summary>\n\n```\n(.*?)\n```", s, re.S)
    if not m:
        sys.exit("README: board block not found under <details>")
    return m.group(1).split("\n")


def colour(line, ch):
    st = line.strip()
    if st.startswith("▲"):
        return RED
    if ch in FRAME:
        return EDGE if ch in "│╭╮╰╯─" else DIM
    if st.startswith("▐▌"):
        return WHITE
    if st.startswith("╭"):
        return GRAY
    if st.startswith("╰") or st.startswith("vendor said") or ("AGENT" in st and ("WINDOW" in st or "FILES" in st)):
        return DIM
    if "codex            week" in line:  # the row past 90%
        return RED if ch == "█" else EDGE if ch == "·" else WHITE
    return {"█": GRAY, "·": EDGE, "○": DIM, "●": GREEN, "▸": CYAN}.get(ch, WHITE)


def main():
    lines = block()
    S = 2
    fs = 15 * S
    font = ImageFont.truetype(FONT, fs)
    cw, lh = font.getlength("M"), int(fs * 1.42)
    cols = max(len(l) for l in lines)
    padx, pady = int(cw * 2), lh
    im = Image.new("RGB", (int(cols * cw + padx * 2), len(lines) * lh + pady * 2), FIELD)
    d = ImageDraw.Draw(im)
    for r, line in enumerate(lines):
        for i, ch in enumerate(line):
            if ch != " ":
                d.text((padx + i * cw, pady + r * lh), ch, font=font, fill=colour(line, ch))
    out = os.path.join(ROOT, "assets", "readme-board.png")
    im.save(out, optimize=True)
    print(f"wrote {out} {im.size[0]}x{im.size[1]}")


if __name__ == "__main__":
    main()
