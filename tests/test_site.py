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


class TestLegendHonesty(unittest.TestCase):
    """The site's LEGEND block is generated from providers/; this is the test
    the feature's honesty depends on - without it the static page's copy
    becomes a lie within two releases."""

    def test_site_legend_matches_providers(self):
        r = subprocess.run([os.sys.executable, os.path.join(ROOT, "ops", "gen_legend.py"),
                            "--verify"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"\n{r.stdout}\n{r.stderr}")

    def test_no_hand_typed_facts_survive_in_prose(self):
        """The undefended half of the page went wrong: five copies of '1,600
        lines' outlived the file growing to 2,700+, a dialect table named a
        vendor that does not ship, prose said three sources while the legend
        beside it said ten. --verify (above) proves the FACTS block is fresh;
        this proves the prose READS it instead of typing numbers again. Any
        literal 'N lines' / 'N,NNN lines' in the page or README that is not
        the derived value is a stale claim in waiting."""
        import re, json
        html = open(SITE, encoding="utf-8").read()
        m = re.search(r"/\*FACTS-DATA\*/var FACTS=(.*?);/\*END-FACTS-DATA\*/", html)
        self.assertIsNotNone(m, "FACTS block missing")
        facts = json.loads(m.group(1))
        # the JS must reference the derived value, never a typed line count
        typed = re.findall(r"\b\d[\d,]{2,} lines\b", html)
        self.assertEqual(typed, [], f"hand-typed line counts in site: {typed}")
        self.assertIn("factLines()", html)
        # no vendor named that does not ship
        shipped = set(facts["agents"]) | set(facts["apis"]) | set(facts["negatives"])
        for ghost in ("gemini",):
            self.assertNotIn(ghost, shipped)
            self.assertNotRegex(html, r"\['" + ghost + r"'", f"{ghost} named as a vendor in the site")
        # README carries the same derived numbers (markdown cannot read JS, so
        # the numbers are written by the generator and checked here)
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        for line in re.findall(r"\b(\d[\d,]*) lines\b", readme):
            self.assertEqual(int(line.replace(",", "")), facts["lines"],
                             f"README says {line} lines; the file has {facts['lines']}")
        self.assertNotIn("Claude Code, OpenAI Codex and Grok CLI usage", readme,
                         "README names three sources; the legend ships " + str(facts["sources"]))


if __name__ == "__main__":
    unittest.main()
