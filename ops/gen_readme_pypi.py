#!/usr/bin/env python3
"""Generate README.pypi.md from README.md - the copy PyPI renders.

PyPI's page cannot carry our font, and box-drawing glyphs from its fallback fonts
draw the board dashed and misaligned; GitHub draws the same text perfectly. So the
two get different READMEs from one source: GitHub keeps the text board, PyPI gets
assets/readme-board.png (a rendering of that exact text - ops/render_readme_board.py)
and no text board at all. Everything else is byte-identical.

    python3 ops/gen_readme_pypi.py            # write README.pypi.md
    python3 ops/gen_readme_pypi.py --verify   # exit 1 if README.pypi.md is stale

tests/test_packaging.py runs --verify, so the PyPI copy cannot drift from the source.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "README.md")
OUT = os.path.join(ROOT, "README.pypi.md")
IMG = "https://raw.githubusercontent.com/omnigauge/omnigauge/main/assets/readme-board.png"
BOARD = re.compile(r"```\n( *▐▌ OMNIGAUGE  one gauge, every provider.*?)\n```", re.S)


def render(src: str) -> str:
    m = BOARD.search(src)
    if not m:
        sys.exit("gen_readme_pypi: the board block was not found in README.md")
    img = (
        '<p align="center">\n'
        f'  <img src="{IMG}" width="100%" alt="the OmniGauge board: PLAN QUOTA, TOKEN VOLUME, WHAT IS DRIVING USAGE - sample data">\n'
        "</p>\n\n"
        "<sub>Sample data - a rendering of the board as the terminal draws it (assets/readme-board.png), not a screenshot of anyone's machine.</sub>"
    )
    head = "<!-- generated from README.md by ops/gen_readme_pypi.py - do not edit; PyPI cannot draw the text board -->\n"
    return head + src[: m.start()] + img + src[m.end():]


def main() -> None:
    src = open(SRC, encoding="utf-8").read()
    want = render(src)
    if "--verify" in sys.argv:
        have = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if have != want:
            print("README.pypi.md is stale - run ops/gen_readme_pypi.py")
            sys.exit(1)
        print("README.pypi.md matches README.md")
        return
    open(OUT, "w", encoding="utf-8").write(want)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
