"""No em-dashes and no en-dashes anywhere a reader meets OmniGauge.

A standing rule from the operator: that punctuation reads as machine-written. The CLI's
panels, the site, the READMEs, the changelog, the providers and the comments beside them are
all meant to be read, so the whole tracked tree is scanned. Two things are allowed to carry
the glyphs: the site harness's own banned-glyph regex (it exists to refuse them) and base64
data lines (fonts), which nobody reads as text.
"""
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
EM, EN = "\u2014", "\u2013"
QUOTED = re.compile(r"""["'][\u2014\u2013]["']""")
GLYPHLIST = re.compile(r"""set\("[^"]*[\u2014\u2013]""")   # a test's own banned-glyph list


def test_no_em_or_en_dash_anywhere_a_reader_meets_it():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    hits = []
    for f in files:
        p = ROOT / f
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            # sanctioned: the harness regex, a quoted single glyph (a banned-list member in a test),
            # and base64 data lines (fonts) that nobody reads as text
            if "const banned" in line or "base64," in line or QUOTED.search(line) or GLYPHLIST.search(line):
                continue
            if EM in line or EN in line:
                hits.append(f"{f}:{n}: {line.strip()[:100]}")
    assert not hits, "em/en-dash found:\n" + "\n".join(hits)
