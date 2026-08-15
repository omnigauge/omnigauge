"""Rendered-output assertions for the omnigauge CLI.

The panel-width invariant has broken three times — twice as arithmetic, once as
font fallback — and every catch came from MEASURING rendered lines, never from
reading the code. These tests render and measure. stdlib only, like the tool.

Run:  python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Import the executable as a module. OMNIGAUGE_HOME and COLUMNS must be pinned
# BEFORE import: DATA and W are computed at module level.
_TMP = tempfile.mkdtemp(prefix="omnigauge-test-")
os.environ["OMNIGAUGE_HOME"] = os.path.join(_TMP, "data")
os.environ["COLUMNS"] = "100"
os.environ.pop("NO_COLOR", None)

import importlib.machinery
import importlib.util
_loader = importlib.machinery.SourceFileLoader("omnigauge", os.path.join(ROOT, "omnigauge"))
_spec = importlib.util.spec_from_loader("omnigauge", _loader)
og = importlib.util.module_from_spec(_spec)
sys.modules["omnigauge"] = og
_loader.exec_module(og)


def strip_ansi(s):
    return re.sub(r"\033\[[0-9;]*m", "", s)


def render_lines(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a, **kw)
    return [l for l in buf.getvalue().splitlines()]


def frame_widths(lines):
    """Visible width of every frame line (╭ │ ╰), ignoring blanks/loose lines."""
    out = []
    for l in lines:
        p = strip_ansi(l)
        if p.strip()[:1] in ("╭", "│", "╰"):
            out.append((len(p.rstrip("\n")), p))
    return out


class TestPanelWidths(unittest.TestCase):
    """Every frame line of a panel must be exactly the same visible width, and
    no wider than the terminal, at every terminal width the tool supports."""

    def setUp(self):
        og.S.on = True          # width math must survive ANSI codes

    def tearDown(self):
        og.W, og.IN = 100, 97

    def assert_frame(self, lines, W):
        widths = frame_widths(lines)
        self.assertTrue(widths, "no frame lines rendered")
        target = widths[0][0]
        for w, text in widths:
            self.assertEqual(w, target, f"ragged frame at W={W}:\n{text!r}")
            self.assertLessEqual(w, W, f"frame wider than terminal at W={W}:\n{text!r}")

    def panel(self, title, sub, rows, note):
        og.top(title, sub)
        for r in rows:
            og.mid(r)
        og.bot(note)

    def test_simple_panel_all_widths(self):
        for W in (80, 86, 100):
            og.W, og.IN = W, W - 3
            lines = render_lines(self.panel, "PLAN QUOTA", "normalized to % consumed",
                                 ["", "  hello", ""], "subscription windows")
            self.assert_frame(lines, W)

    def test_overlong_title_sub_and_row_are_clipped_not_overflowed(self):
        long = "X" * 200
        for W in (80, 100):
            og.W, og.IN = W, W - 3
            lines = render_lines(self.panel, long, long, ["  " + long], long)
            self.assert_frame(lines, W)

    def test_empty_and_edge_content(self):
        for W in (80, 100):
            og.W, og.IN = W, W - 3
            lines = render_lines(self.panel, "T", "", ["", " ", "  x" * 5], "")
            self.assert_frame(lines, W)

    def test_colored_content_width_equals_plain(self):
        og.W, og.IN = 100, 97
        s = og.s
        colored = f"  {s.crit}▸{s.r} {s.b}name{s.r}{s.gry}window{s.r}"
        lines = render_lines(self.panel, "T", "sub", [colored], "note")
        self.assert_frame(lines, 100)

    def test_quota_row_fits_default_80_column_terminal(self):
        """The board's widest row must fit IN=78 — a default terminal."""
        for W in (80, 100):
            og.W, og.IN = W, W - 3
            row = og.quota_row_text(
                agent="grok", model="x premium+", window="week", pct=97.4,
                rate=1.44, dry_in=5160, reset="Aug 19, 6pm (UTC)",
                at=int(time.time()) - 420)
            lines = render_lines(self.panel, "PLAN QUOTA", "normalized to % consumed",
                                 [row], "note")
            self.assert_frame(lines, W)

    def test_full_render_frame_integrity(self):
        """Integration: a real render() over a seeded DB, measured line by line."""
        con = og.db()
        con.execute("DELETE FROM snapshots")
        now = int(time.time())
        for pct, at in ((50.0, now - 3600), (90.0, now)):
            con.execute(
                "INSERT INTO snapshots(product,source,agent,window,model,usage_type,"
                "pct_used,raw_value,reset_at,collected_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("codex_plan", "cli_status", "codex", "week", "all", "plan_quota",
                 pct, f"{100-pct:.0f}% left", "Aug 20, 6pm", at))
        con.commit(); con.close()
        og.memo_clear()

        class A:  # minimal args
            since, brief, theme = "24h", True, "ink"
        for W in (80, 100):
            og.W, og.IN = W, W - 3
            lines = render_lines(og.render, A)
            self.assert_frame(lines, W)

    def test_no_fallback_risk_glyphs_in_panel_output(self):
        """Em dashes, curly quotes, arrows and non-CP437 partial blocks render at
        a different advance when a font lacks them — the defect that ragged three
        panels. None may appear in any frame line."""
        con = og.db(); con.execute("DELETE FROM snapshots")
        now = int(time.time())
        con.execute(
            "INSERT INTO snapshots(product,source,agent,window,model,usage_type,"
            "pct_used,raw_value,reset_at,collected_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("codex_plan", "cli_status", "codex", "week", "all", "plan_quota",
             97.0, "3% left", None, now))
        con.commit(); con.close(); og.memo_clear()

        class A:
            since, brief, theme = "24h", True, "ink"
        og.W, og.IN = 100, 97
        banned = set("—–‘’“”→▟▛▎▋▁▂▃▄▅▆▇")
        for l in render_lines(og.render, A):
            p = strip_ansi(l)
            if p.strip()[:1] in ("╭", "│", "╰"):
                hits = banned & set(p)
                self.assertFalse(hits, f"fallback-risk glyph {hits} in frame line:\n{p!r}")


class TestParsers(unittest.TestCase):
    CLAUDE = """\
  Settings

  Usage

  Current session
  ██████░░░░░░░░░░░░  5% used
  Resets 12:19am (UTC)

  Current week (all models)
  ████░░░░░░░░░░░░░░  24% used
  Resets Aug 19, 6pm (UTC)

  ✻ Weekly limits refresh every 7 days.

  Current week (Opus)
  ░░░░░░░░░░░░░░░░░░  0% used
  Resets Aug 19, 6pm (UTC)

  63% of your usage came from sessions active for 8+ hours
"""

    def test_claude_survives_injected_promo_line(self):
        rows = og.parse_claude(self.CLAUDE)
        got = {(r["window"], r["model"]): r for r in rows}
        self.assertIn(("session", "all"), got)
        self.assertIn(("week", "all"), got)
        self.assertIn(("week", "Opus"), got)
        self.assertEqual(got[("week", "all")]["pct_used"], 24.0)
        self.assertEqual(got[("week", "all")]["reset_at"], "Aug 19, 6pm (UTC)")
        # the 0% row must survive — 0 is a reading, not an absence
        self.assertEqual(got[("week", "Opus")]["pct_used"], 0.0)

    def test_claude_insights(self):
        self.assertEqual(og.claude_insights(self.CLAUDE),
                         ["63% of your usage came from sessions active for 8+ hours"])

    CODEX = """\
│  GPT-5.3-Codex Weekly limit: [████████████████░░░░] 3% left (resets 20:00 on 19 Aug)
   some interleaved status line the vendor added
│  GPT-5.3-Codex-Spark Weekly limit: [░░░░░░░░░░░░░░░░░░░░] 100% left (resets 06:00 on 22 Aug)
"""

    def test_codex_inversion_and_interleaved_line(self):
        rows = og.parse_codex(self.CODEX)
        self.assertEqual(len(rows), 2)
        by = {r["model"]: r for r in rows}
        self.assertEqual(by["GPT-5.3-Codex"]["pct_used"], 97.0)
        self.assertEqual(by["GPT-5.3-Codex"]["raw_value"], "3% left")
        self.assertEqual(by["GPT-5.3-Codex-Spark"]["pct_used"], 0.0)

    def test_codex_inversion_property(self):
        for left in (0, 1, 37, 99, 100):
            screen = f"│ X Weekly limit: [░] {left}% left (resets 20:00 on 19 Aug)"
            (r,) = og.parse_codex(screen)
            self.assertEqual(r["pct_used"], 100.0 - left)

    GROK = """\
   Weekly limit (X Premium+)

        ▓▓▓░░░░░░░   26%

   Resets: Aug 17, 12:49
"""

    def test_grok(self):
        (r,) = og.parse_grok(self.GROK)
        self.assertEqual(r["pct_used"], 26.0)
        self.assertEqual(r["model"], "X Premium+")
        self.assertTrue(r["reset_at"].startswith("Aug 17"))

    def test_empty_screens_yield_no_rows(self):
        for p in (og.parse_claude, og.parse_codex, og.parse_grok):
            self.assertEqual(p("Welcome!\n\nTry typing something.\n"), [])


class TestScrapeContract(unittest.TestCase):
    """PARTIAL-parse-is-failure, exercised at the refresh() level with a fake
    tmux — the real screen pipeline minus the terminal."""

    def setUp(self):
        con = og.db(); con.execute("DELETE FROM snapshots"); con.commit(); con.close()
        self._scrape, self._installed = og.tmux_scrape, og.installed
        og.installed = lambda a: True

    def tearDown(self):
        og.tmux_scrape, og.installed = self._scrape, self._installed

    def run_refresh(self, screen):
        og.tmux_scrape = lambda *a, **k: (screen, None)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            og.refresh(["claude"])
        con = og.db()
        rows = list(con.execute("SELECT window,model,pct_used FROM snapshots"))
        con.close()
        return buf.getvalue(), rows

    def test_full_parse_inserts_and_reports_ok(self):
        out, rows = self.run_refresh(TestParsers.CLAUDE)
        self.assertIn("ok", strip_ansi(out))
        self.assertEqual(len(rows), 3)

    def test_partial_parse_is_loud_and_stores_what_it_proved(self):
        screen = "\n".join(l for l in TestParsers.CLAUDE.splitlines()
                           if "week (all models)" not in l)
        out, rows = self.run_refresh(screen)
        plain = strip_ansi(out)
        self.assertIn("PARTIAL", plain)
        self.assertIn("('week', 'all')", plain)
        self.assertTrue(os.path.exists(os.path.join(og.DATA, "last-scrape-claude.txt")))

    def test_no_rows_stores_nothing_and_dumps_screen(self):
        out, rows = self.run_refresh("Welcome to Claude!\n❯ ")
        self.assertIn("NO QUOTA PARSED", strip_ansi(out))
        self.assertEqual(rows, [])


class TestDBMigration(unittest.TestCase):
    def test_old_schema_gains_models_column_and_keeps_rows(self):
        old = os.path.join(_TMP, "old-shape")
        os.makedirs(old, exist_ok=True)
        db = os.path.join(old, "usage.db")
        con = sqlite3.connect(db)
        con.execute("""CREATE TABLE filecache (
            path TEXT PRIMARY KEY, agent TEXT, mtime REAL, size INTEGER,
            tin INTEGER, tout INTEGER, cache_read INTEGER, cache_write INTEGER,
            think INTEGER, total INTEGER, msgs INTEGER, scanned_at INTEGER)""")
        con.execute("INSERT INTO filecache(path,agent,mtime,size,tin) VALUES(?,?,?,?,?)",
                    ("/x.jsonl", "claude", 1.0, 10, 42))
        con.commit(); con.close()

        prev_data, prev_db = og.DATA, og.DB
        try:
            og.DATA, og.DB = old, db
            con = og.db()
            cols = {r[1] for r in con.execute("PRAGMA table_info(filecache)")}
            self.assertIn("models", cols)
            self.assertEqual(con.execute("SELECT tin FROM filecache").fetchone()[0], 42)
            con.close()
            og.db().close()   # idempotent second open
        finally:
            og.DATA, og.DB = prev_data, prev_db


class TestSinceAndEpoch(unittest.TestCase):
    def test_epoch_parses_z_suffix(self):
        self.assertAlmostEqual(og._epoch("1970-01-01T00:01:00Z"), 60.0, places=1)

    def test_epoch_unparseable_is_none_not_zero(self):
        self.assertIsNone(og._epoch("not a timestamp"))
        self.assertIsNone(og._epoch(""))
        self.assertIsNone(og._epoch(None))

    def test_scan_claude_includes_lines_with_broken_timestamps(self):
        """A message with an unreadable timestamp still happened. Excluding it
        silently undercounts — the zeros-in-a-costume class."""
        p = os.path.join(_TMP, "t.jsonl")
        lines = [
            {"timestamp": "2026-08-15T10:00:00Z",
             "message": {"model": "m", "usage": {"input_tokens": 1, "output_tokens": 2}}},
            {"timestamp": "GARBAGE",
             "message": {"model": "m", "usage": {"input_tokens": 1, "output_tokens": 2}}},
        ]
        with open(p, "w") as fh:
            for l in lines:
                fh.write(json.dumps(l) + "\n")
        t = og.scan_claude(p, since=10)         # both are "after" since
        self.assertEqual(t["msgs"], 2)
        t = og.scan_claude(p, since=32503680000)  # year 3000: dated line filtered,
        self.assertEqual(t["msgs"], 1)            # undated line still included

    def test_since_today_is_local_midnight(self):
        class A: since = "today"
        midnight = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
        self.assertEqual(og.since_epoch(A.since), int(midnight))

    def test_since_windows(self):
        now = int(time.time())
        self.assertAlmostEqual(og.since_epoch("24h"), now - 86400, delta=2)
        self.assertAlmostEqual(og.since_epoch("7d"), now - 604800, delta=2)
        self.assertLess(og.since_epoch("all"), 0)


class TestCheckExitCodes(unittest.TestCase):
    """--check runs the installed interface: exit code IS the contract."""

    def run_check(self, seed, extra=()):
        home = tempfile.mkdtemp(prefix="omnigauge-check-")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "alerts.json"), "w") as fh:
            json.dump({"pct_used": 85, "dry_before_reset": True,
                       "notify": False, "webhook": ""}, fh)
        con = sqlite3.connect(os.path.join(home, "usage.db"))
        con.executescript(og.SCHEMA)
        now = int(time.time())
        for agent, window, pct, raw, reset, at in seed:
            con.execute(
                "INSERT INTO snapshots(product,source,agent,window,model,usage_type,"
                "pct_used,raw_value,reset_at,collected_at) VALUES(?,?,?,?,'all',"
                "'plan_quota',?,?,?,?)",
                (f"{agent}_plan", "cli", agent, window, pct, raw, reset, now + at))
        con.commit(); con.close()
        env = dict(os.environ, OMNIGAUGE_HOME=home)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "omnigauge"),
                            "--check", *extra], capture_output=True, text=True, env=env)
        return r

    def test_empty_db_exits_zero(self):
        r = self.run_check([])
        self.assertEqual(r.returncode, 0)
        self.assertIn("ok", r.stdout)

    def test_quiet_ok_prints_nothing(self):
        r = self.run_check([], extra=("--quiet",))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_threshold_crossing_exits_one(self):
        r = self.run_check([("codex", "week", 91.0, "9% left", None, 0)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("WARNING", r.stdout)

    def test_dry_before_reset_exits_two(self):
        seed = [("codex", "week", 50.0, "50% left", "Aug 20, 6pm", -3600),
                ("codex", "week", 90.0, "10% left", "Aug 20, 6pm", 0)]
        r = self.run_check(seed)
        self.assertEqual(r.returncode, 2)
        self.assertIn("CRITICAL", r.stdout)

    def test_healthy_reading_exits_zero(self):
        r = self.run_check([("claude", "week", 24.0, "24% used", "Aug 19, 6pm", 0)])
        self.assertEqual(r.returncode, 0)


class TestBurn(unittest.TestCase):
    def seed(self, series):
        con = og.db(); con.execute("DELETE FROM snapshots")
        for pct, at in series:
            con.execute(
                "INSERT INTO snapshots(product,source,agent,window,model,usage_type,"
                "pct_used,collected_at) VALUES('a_plan','cli','a','week','all',"
                "'plan_quota',?,?)", (pct, at))
        con.commit()
        return con

    def test_needs_two_readings_ten_minutes_apart(self):
        now = int(time.time())
        con = self.seed([(50, now - 300), (60, now)])
        self.assertIsNone(og.burn(con, "a", "week", "all", 60, now)["rate"])
        con.close()

    def test_reset_truncates_series(self):
        now = int(time.time())
        con = self.seed([(90, now - 7200), (5, now - 3600), (10, now)])
        b = og.burn(con, "a", "week", "all", 10, now)
        self.assertAlmostEqual(b["rate"], 5.0, places=1)   # 5→10 over 1h, not 90→10
        con.close()

    def test_flat_or_falling_says_nothing(self):
        now = int(time.time())
        con = self.seed([(50, now - 3600), (50, now)])
        self.assertIsNone(og.burn(con, "a", "week", "all", 50, now)["rate"])
        con.close()


class TestProviderConformance(unittest.TestCase):
    """providers/claude.py mirrors built-ins. Until one home wins, this test IS
    the drift lock: identical fixtures through both copies, identical answers."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "omnigauge_provider_claude", os.path.join(ROOT, "providers", "claude.py"))
        cls.plug = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.plug)

    def test_parse_quota_matches_builtin(self):
        self.assertEqual(self.plug.parse_quota(TestParsers.CLAUDE),
                         og.parse_claude(TestParsers.CLAUDE))

    def test_insights_match_builtin(self):
        self.assertEqual(self.plug.insights(TestParsers.CLAUDE),
                         og.claude_insights(TestParsers.CLAUDE))

    def test_quota_spec_matches_builtin(self):
        spec, builtin = self.plug.QUOTA, og.AGENTS["claude"]
        for k in ("argv", "keys", "ready", "done", "expect"):
            self.assertEqual(spec[k], builtin[k], f"drift in QUOTA[{k!r}]")

    def test_scan_matches_builtin_including_since(self):
        p = os.path.join(_TMP, "conf.jsonl")
        with open(p, "w") as fh:
            fh.write(json.dumps({"timestamp": "2026-08-15T10:00:00Z", "message": {
                "model": "m", "usage": {"input_tokens": 3, "output_tokens": 4,
                                        "cache_read_input_tokens": 5}}}) + "\n")
            fh.write(json.dumps({"timestamp": "GARBAGE", "message": {
                "model": "m", "usage": {"input_tokens": 1, "output_tokens": 1}}}) + "\n")
        for since in (0, 10, 32503680000):
            self.assertEqual(self.plug.scan(p, since), og.scan_claude(p, since),
                             f"drift in scan(since={since})")


class TestInstall(unittest.TestCase):
    def test_install_ships_the_right_files(self):
        dest = tempfile.mkdtemp(prefix="omnigauge-inst-")
        data = tempfile.mkdtemp(prefix="omnigauge-xdg-")
        env = dict(os.environ, XDG_DATA_HOME=data)
        r = subprocess.run(["bash", os.path.join(ROOT, "install.sh"), os.path.join(dest, "bin")],
                           capture_output=True, text=True, env=env, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        binp = os.path.join(dest, "bin", "omnigauge")
        self.assertTrue(os.path.exists(binp))
        with open(binp, "rb") as a, open(os.path.join(ROOT, "omnigauge"), "rb") as b:
            self.assertEqual(a.read(), b.read(), "installed binary differs from repo")
        self.assertTrue(os.path.exists(os.path.join(data, "omnigauge", "providers", "claude.py")))
        self.assertTrue(os.access(binp, os.X_OK))


if __name__ == "__main__":
    unittest.main()
