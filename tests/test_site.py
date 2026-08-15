"""The site's deploy gate, runnable anywhere node exists.

Two checks, both earned: node --check caught nothing the day a typographic
sweep closed a string early and shipped a blank page (it would have); and the
width harness measures real rendered rows because the 78-column invariant has
never once been broken in a way reading the code caught.

A missing node is a SKIP, loudly - a check that cannot run is not a negative
result.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site", "index.html")


@unittest.skipUnless(shutil.which("node"), "node not installed - site checks DID NOT RUN")
class TestSite(unittest.TestCase):
    def test_script_parses(self):
        js = re.search(r"<script>([\s\S]*)</script>", open(SITE).read()).group(1)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(js)
        r = subprocess.run(["node", "--check", fh.name], capture_output=True, text=True)
        os.unlink(fh.name)
        self.assertEqual(r.returncode, 0, f"syntax error in site script:\n{r.stderr}")

    def test_rendered_rows_measure_78(self):
        r = subprocess.run(["node", os.path.join(ROOT, "tests", "site_harness.js"), SITE],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"\n{r.stdout}\n{r.stderr}")
        self.assertIn("OK:", r.stdout)


if __name__ == "__main__":
    unittest.main()
