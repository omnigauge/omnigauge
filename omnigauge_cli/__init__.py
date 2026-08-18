"""The pip/pipx entry for omnigauge.

omnigauge is one file, `omnigauge`, with no extension - that is the product and it
stays that way. This package exists only so `pipx install omnigauge` can put an
`omnigauge` command on your PATH: the wheel carries the file itself and the
provider mirrors beside it, at exactly the relative place the file already looks
for them (`providers/` next to itself), and this function runs the file as
__main__. Nothing is imported from it, nothing is wrapped, nothing is changed.
"""
import os
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "omnigauge")


def main() -> None:
    runpy.run_path(SCRIPT, run_name="__main__")
