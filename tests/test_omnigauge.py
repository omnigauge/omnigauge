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
    """Visible width of every frame line (╔ ║ ╚), ignoring blanks/loose lines.
    The frame wears the site's double-line dress now; the invariant is the
    same one that broke three times: every line of a panel measures alike."""
    out = []
    for l in lines:
        p = strip_ansi(l)
        if p.strip()[:1] in ("╔", "║", "╚"):
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
        """The board's widest row must fit IN=78 — a default terminal — and
        every wider tier (forecast at 97, MARGIN at 106, 24H trend at 114)
        must frame just as exactly."""
        for W in (80, 100, 106, 114, 140):
            og.W, og.IN = W, W - 3
            row = og.quota_row_text(
                agent="grok", model="x premium+", window="week", pct=97.4,
                rate=1.44, dry_in=5160, reset="Aug 19, 6pm (UTC)",
                at=int(time.time()) - 420, trend="░▒▓█▓█")
            lines = render_lines(self.panel, "PLAN QUOTA", "normalized to % consumed",
                                 [row], "note")
            self.assert_frame(lines, W)
            plain = strip_ansi(row)
            if W >= 106:
                self.assertIn("-", plain, "MARGIN missing at wide width")
            if W >= 114:
                self.assertIn("░▒▓█", plain, "trend strip missing at widest tier")

    def test_margin_is_a_signed_verdict(self):
        og.W, og.IN = 120, 117
        neg = strip_ansi(og.margin_text(3600, 7200))       # dry before reset
        pos = strip_ansi(og.margin_text(7200, 3600))       # reset before dry
        self.assertTrue(neg.strip().startswith("-"), neg)
        self.assertTrue(pos.strip().startswith("+"), pos)
        self.assertEqual(strip_ansi(og.margin_text(None, 3600)).strip(), "-")

    def test_trend_strip_from_snapshot_history(self):
        con = og.db()
        con.execute("DELETE FROM snapshots")
        now = int(time.time())
        for i, pct in enumerate((10.0, 20.0, 30.0, 60.0)):
            con.execute(
                "INSERT INTO snapshots(product,source,agent,window,model,usage_type,"
                "pct_used,raw_value,reset_at,collected_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("claude_plan", "cli", "claude", "week", "all", "plan_quota",
                 pct, f"{pct:.0f}% used", "Aug 30, 6pm", now - (3 - i) * 6 * 3600))
        con.commit()
        t = og.trend(con, "claude", "week", "all", now)
        self.assertIsNotNone(t)
        self.assertEqual(len(t), 6)
        self.assertEqual(t.strip()[0], "░", "lowest reading is the light cell")
        self.assertEqual(t.strip()[-1], "█", "highest reading is the full cell")
        self.assertIsNone(og.trend(con, "grok", "week", "x", now), "no data -> None")
        con.execute("DELETE FROM snapshots"); con.commit()

    def test_build_id_and_change_detection(self):
        b = og.build_id()
        self.assertEqual(len(b), 8)
        og._BUILD_AT_START = None
        self.assertFalse(og.binary_changed(), "arming call must report unchanged")
        self.assertFalse(og.binary_changed(), "same bytes -> unchanged")
        og._BUILD_AT_START = "deadbeef"
        self.assertTrue(og.binary_changed(), "different fingerprint -> changed")
        og._BUILD_AT_START = None

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
        for W in (80, 100, 106, 114, 140):
            og.W, og.IN = W, W - 3
            lines = render_lines(og.render, A)
            self.assert_frame(lines, W)
            plain = "\n".join(strip_ansi(l) for l in lines)
            if W >= 99:
                self.assertIn("THINK%", plain, f"THINK% missing at W={W}")

    def test_volume_table_fills_its_box(self):
        """Elastic columns: the volume header must reach the right border at
        every width - fixed widths stranded a wide frame's right third and
        clipped at a strict 80."""
        class A:
            since, brief, theme = "24h", True, "ink"
        for W in (80, 100):
            og.W, og.IN = W, W - 3
            for l in render_lines(og.render, A):
                p = strip_ansi(l)
                if "CACHE-RD" in p:
                    inner = p.strip()[1:-1]
                    self.assertEqual(len(inner), og.IN)
                    self.assertGreaterEqual(
                        len(inner.rstrip()), og.IN - 1,
                        f"header stops short of the border at W={W}: {inner!r}")
                    break
            else:
                self.fail(f"no volume header rendered at W={W}")

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
        # EVERY line, not just frame lines - checking only panels left five
        # survivors on the site, one inside a panel header. Same rule here.
        banned = set("—–‘’“”→▟▛▎▋▁▂▃▄▅▆▇")
        for l in render_lines(og.render, A):
            p = strip_ansi(l)
            hits = banned & set(p)
            self.assertFalse(hits, f"fallback-risk glyph {hits} in line:\n{p!r}")

    def test_no_fallback_glyphs_in_doctor_or_legend(self):
        banned = set("—–‘’“”→▟▛▎▋▁▂▃▄▅▆▇")
        env = dict(os.environ, OMNIGAUGE_HOME=tempfile.mkdtemp(prefix="og-doc-"))
        for flag in ("--doctor", "--providers"):
            r = subprocess.run([sys.executable, os.path.join(ROOT, "omnigauge"), flag],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            for l in r.stdout.splitlines():
                hits = banned & set(strip_ansi(l))
                self.assertFalse(hits, f"{flag}: glyph {hits} in line:\n{l!r}")


class TestCountdown(unittest.TestCase):
    """RESETS IN is a delta on every row. Session rows used to print a wall
    clock because a time-only reset ('3:19pm') fell out of the parser - and
    when it did parse, '3:19pm' read as 03:19 (HH:MM matched, meridian
    ignored), twelve hours off. That also disabled the dry-before-reset
    check for sessions, since no seconds meant no comparison."""

    def test_time_only_reset_is_a_forward_delta(self):
        s = og.countdown("3:19pm (America/Chicago)", _as_seconds=True)
        self.assertIsNotNone(s)
        self.assertGreater(s, 0)
        self.assertLessEqual(s, 86400, "next occurrence is within a day")

    def test_meridian_wins_over_hhmm(self):
        pm = og.countdown("3:19pm (X)", _as_seconds=True)
        am = og.countdown("3:19am (X)", _as_seconds=True)
        self.assertNotEqual(pm, am)
        # the two are exactly twelve hours apart on the clock face
        self.assertEqual((pm - am) % 86400, 12 * 3600)

    def test_every_vendor_format_yields_a_delta(self):
        for txt in ("Aug 19, 6pm (America/Chicago)", "23:04 on 19 Aug",
                    "August 17, 12:49", "12:19am (UTC)", "11:10pm (America/Chicago)"):
            self.assertIsNotNone(og.countdown(txt), f"no delta for {txt!r}")

    def test_garbage_still_refuses(self):
        self.assertIsNone(og.countdown("soon-ish"))
        self.assertIsNone(og.countdown(""))


class TestApiCache(unittest.TestCase):
    """The spend panel must never rate-limit itself out of its own data: a
    TTL keeps fetches rare, and a failed fetch serves the last good answer
    WITH ITS AGE. Only failure-with-no-history renders as an error."""

    def test_ttl_serves_without_calling_vendor(self):
        con = og.db()
        con.execute("DELETE FROM api_cache"); con.commit()
        calls = []
        def ok(): calls.append(1); return dict(spend_usd=1.0)
        def boom(): calls.append(1); return dict(err="HTTP 429")
        r1 = og.cached_api(con, "t1", ok)
        self.assertEqual(r1["spend_usd"], 1.0)
        r2 = og.cached_api(con, "t1", boom)      # within TTL: vendor not called
        self.assertEqual(len(calls), 1, "TTL hit still called the vendor")
        self.assertEqual(r2["spend_usd"], 1.0)
        self.assertIn("age", r2)

    def test_failed_fetch_serves_stale_with_age_and_reason(self):
        con = og.db()
        con.execute("DELETE FROM api_cache"); con.commit()
        og.cached_api(con, "t1", lambda: dict(used=874, cap=3_000_000,
                                              pct=0.03, unit="posts"))
        con.execute("UPDATE api_cache SET fetched_at=? WHERE name='t1'",
                    (og.NOW - og.API_TTL - 7200,))
        con.commit()
        r = og.cached_api(con, "t1", lambda: dict(err="HTTP 429"))
        self.assertEqual(r["used"], 874, "stale fetch lost the last good value")
        self.assertEqual(r["stale"], "HTTP 429")
        line = strip_ansi(og.api_row_text("x/a", "posts · cap", r))
        self.assertIn("874", line)
        self.assertIn("429", line)
        self.assertIn("old", line)

    def test_no_history_failure_stays_loud(self):
        con = og.db()
        con.execute("DELETE FROM api_cache"); con.commit()
        r = og.cached_api(con, "t-none", lambda: dict(err="HTTP 429"))
        self.assertEqual(r.get("err"), "HTTP 429")
        self.assertIn("429", strip_ansi(og.api_row_text("x/a", "posts · cap", r)))


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
        def load(name):
            spec = importlib.util.spec_from_file_location(
                f"omnigauge_provider_{name}",
                os.path.join(ROOT, "providers", f"{name}.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        cls.plug = load("claude")
        cls.plug_codex = load("codex")
        cls.plug_grok = load("grok")

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

    def test_codex_hostile_shapes_match_builtin(self):
        """The delta fixture above is a HEALTHY rollout, and both copies agreed
        on it while disagreeing completely on a counter that resets. A drift lock
        only locks the shapes it is given.

        These are the shapes that broke: a restart inside the window, a restart
        whose new run overtakes the old total, and a file with no parseable
        timestamp anywhere.
        """
        def ev(ts, tot):
            o = {"type": "token_count", "payload": {"info": {"total_token_usage": {
                "input_tokens": tot, "output_tokens": tot // 10,
                "total_tokens": tot + tot // 10}}}}
            if ts is not None:
                o["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                                               time.gmtime(ts))
            return json.dumps(o)

        now = time.time()
        since = now - 86400
        cases = {
            "reset_inside_window": (
                [ev(now - 3 * 86400, 1_000_000), ev(now - 2 * 86400, 5_000_000),
                 ev(now - 3600, 10_000), ev(now - 600, 150_000)], None),
            "reset_overtakes_old_total": (
                [ev(now - 30 * 86400, 5_000_000), ev(now - 3600, 10_000),
                 ev(now - 600, 8_000_000)], None),
            "no_timestamps_anywhere": (
                [ev(None, 1_000_000), ev(None, 5_000_000)], now - 30 * 86400),
        }
        for name, (lines, mtime) in cases.items():
            f = os.path.join(_TMP, f"codex-{name}.jsonl")
            with open(f, "w") as fh:
                fh.write("\n".join(lines) + "\n")
            if mtime is not None:
                os.utime(f, (mtime, mtime))
            a = og.scan_codex(f, since)
            b = self.plug_codex.scan(f, since)
            self.assertEqual(
                {k: a[k] for k, _ in og._CODEX_FIELDS},
                {k: b[k] for k, _ in og._CODEX_FIELDS},
                f"built-in and provider disagree on {name}")

    def test_codex_parse_and_spec_match_builtin(self):
        self.assertEqual(self.plug_codex.parse_quota(TestParsers.CODEX),
                         og.parse_codex(TestParsers.CODEX))
        for k in ("argv", "keys", "ready", "done", "expect"):
            self.assertEqual(self.plug_codex.QUOTA[k], og.AGENTS["codex"][k],
                             f"codex drift in QUOTA[{k!r}]")

    def test_grok_parse_and_spec_match_builtin(self):
        self.assertEqual(self.plug_grok.parse_quota(TestParsers.GROK),
                         og.parse_grok(TestParsers.GROK))
        for k in ("argv", "keys", "ready", "done", "expect"):
            self.assertEqual(self.plug_grok.QUOTA[k], og.AGENTS["grok"][k],
                             f"grok drift in QUOTA[{k!r}]")

    def test_codex_restart_hidden_in_the_bisect_gap_is_counted(self):
        """Assay's documented boundary: the edge lands outside the 1MB tail,
        so the events between it and the tail were never read - a counter
        restart in that gap was invisible. Build exactly that shape (>4MB of
        in-window events with a restart deep in the middle) and require the
        full spend through BOTH copies."""
        def ev(ts, tot):
            return json.dumps({"timestamp": ts, "pad": "x" * 200, "payload": {
                "info": {"total_token_usage": {
                    "input_tokens": tot, "cached_input_tokens": 0,
                    "output_tokens": 0, "reasoning_output_tokens": 0,
                    "total_tokens": tot}}}}) + "\n"
        p = os.path.join(_TMP, "codex-gap-restart.jsonl")
        with open(p, "w") as fh:
            fh.write('{"model":"gpt-gap"}\n')
            for i in range(6000):                       # before the cut: to 6000
                fh.write(ev(f"2026-08-10T{i//3600:02d}:{(i//60)%60:02d}:{i%60:02d}Z", i + 1))
            for i in range(9000):                       # in window: 6000 -> 15000
                fh.write(ev(f"2026-08-15T{i//3600:02d}:{(i//60)%60:02d}:{i%60:02d}Z", 6000 + i + 1))
            for i in range(9000):                       # RESTART deep in the gap: 1 -> 9000
                fh.write(ev(f"2026-08-15T{3+i//3600:02d}:{(i//60)%60:02d}:{i%60:02d}Z", i + 1))
        self.assertGreater(os.path.getsize(p), 4 << 20, "fixture must outgrow the tail")
        cut = og._epoch("2026-08-14T00:00:00Z")
        # spend inside the window = 9000 (first run's growth) + 9000 (the restart's run)
        for fn in (og.scan_codex, self.plug_codex.scan):
            r = fn(p, cut)
            self.assertEqual(r["total"], 18000,
                             f"restart in the bisect gap dropped in {fn.__module__}: {r['total']}")
        self.assertEqual(og.scan_codex(p, cut), self.plug_codex.scan(p, cut),
                         "gap-walk drift: builtin vs mirror")

    def test_codex_scan_since_is_a_window_delta(self):
        """A rollout touched inside the window contributes its GROWTH across
        the window edge, not its whole history - the old behaviour put 1.13B
        tokens accumulated over 25 days into a panel labelled '24h' because
        the file's mtime was recent."""
        def ev(ts, tin, tout, cr, think, tot):
            return json.dumps({"timestamp": ts, "type": "event_msg", "payload": {
                "type": "token_count", "info": {"total_token_usage": {
                    "input_tokens": tin, "cached_input_tokens": cr,
                    "cache_write_input_tokens": 0, "output_tokens": tout,
                    "reasoning_output_tokens": think, "total_tokens": tot}}}})
        p = os.path.join(_TMP, "codex-delta.jsonl")
        with open(p, "w") as fh:
            fh.write('{"model":"gpt-old"}\n')
            fh.write(ev("2026-08-10T00:00:00Z", 100, 10, 50, 5, 110) + "\n")
            fh.write('{"model":"gpt-new"}\n')
            fh.write(ev("2026-08-15T12:00:00Z", 130, 16, 70, 8, 146) + "\n")
        cut = og._epoch("2026-08-14T00:00:00Z")
        for fn in (og.scan_codex, self.plug_codex.scan):
            r = fn(p, cut)
            self.assertEqual(
                (r["tin"], r["tout"], r["cache_read"], r["think"], r["total"]),
                (30, 6, 20, 3, 36), f"window delta wrong in {fn.__module__}")
            self.assertIn("gpt-new", r["models"])
            self.assertEqual(fn(p, og._epoch("2026-08-15T13:00:00Z"))["msgs"],
                             0, f"untouched window not empty in {fn.__module__}")
            self.assertEqual(fn(p, 0)["total"], 146,
                             f"lifetime changed in {fn.__module__}")
        self.assertEqual(og.scan_codex(p, cut), self.plug_codex.scan(p, cut),
                         "codex since drift: builtin vs mirror")

    def test_grok_scan_since_is_a_window_delta(self):
        p = os.path.join(_TMP, "grok-delta", "sess", "updates.jsonl")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(json.dumps({"timestamp": 1000,
                                 "_meta": {"totalTokens": 500}}) + "\n")
            fh.write(json.dumps({"timestamp": 2000,
                                 "_meta": {"totalTokens": 800}}) + "\n")
        for fn in (og.scan_grok, self.plug_grok.scan):
            self.assertEqual(fn(p, 1500)["total"], 300,
                             f"growth wrong in {fn.__module__}")
            self.assertEqual(fn(p, 2500)["msgs"], 0,
                             f"untouched window not empty in {fn.__module__}")
            self.assertEqual(fn(p, 0)["total"], 800,
                             f"lifetime changed in {fn.__module__}")
        self.assertEqual(og.scan_grok(p, 1500), self.plug_grok.scan(p, 1500),
                         "grok since drift: builtin vs mirror")

    def test_configured_roots_extend_discovery_through_both_copies(self):
        """A removable dev drive is POINTED AT, not guessed: OMNIGAUGE_ROOTS
        adds HOME-like roots and discovery for every agent unions them - via
        the builtin AND the mirror that overrides it at load."""
        root = os.path.join(_TMP, "ssd-root")
        os.makedirs(os.path.join(root, ".claude", "projects", "-p"), exist_ok=True)
        os.makedirs(os.path.join(root, ".codex", "sessions", "2026"), exist_ok=True)
        os.makedirs(os.path.join(root, ".grok", "sessions", "a", "b"), exist_ok=True)
        cf = os.path.join(root, ".claude", "projects", "-p", "s.jsonl")
        xf = os.path.join(root, ".codex", "sessions", "2026", "r.jsonl")
        gf = os.path.join(root, ".grok", "sessions", "a", "b", "updates.jsonl")
        for p in (cf, xf, gf):
            with open(p, "w") as fh:
                fh.write("{}\n")
        old = os.environ.get("OMNIGAUGE_ROOTS")
        os.environ["OMNIGAUGE_ROOTS"] = root
        try:
            self.assertIn(cf, og.claude_files())
            self.assertIn(xf, og.codex_files())
            self.assertIn(gf, og.grok_files())
            self.assertEqual(sorted(og.claude_files()), sorted(self.plug.files()))
            self.assertEqual(sorted(og.codex_files()),
                             sorted(self.plug_codex.files()))
            self.assertEqual(sorted(og.grok_files()),
                             sorted(self.plug_grok.files()))
        finally:
            if old is None: os.environ.pop("OMNIGAUGE_ROOTS", None)
            else: os.environ["OMNIGAUGE_ROOTS"] = old

    def test_symlinked_root_does_not_double_count(self):
        """A root that reaches the same store through a symlink - or points
        back at the real home under another name - must not double the
        numbers. Dedup is by realpath, not by string."""
        base = os.path.join(_TMP, "link-home")
        os.makedirs(os.path.join(base, ".claude", "projects", "-p"),
                    exist_ok=True)
        f = os.path.join(base, ".claude", "projects", "-p", "one.jsonl")
        with open(f, "w") as fh:
            fh.write("{}\n")
        alias = os.path.join(_TMP, "link-alias")
        if not os.path.islink(alias):
            os.symlink(base, alias)
        old_h, old_r = os.environ["HOME"], os.environ.get("OMNIGAUGE_ROOTS")
        os.environ["HOME"] = base
        os.environ["OMNIGAUGE_ROOTS"] = alias
        try:
            found = og.claude_files()
            self.assertEqual(len(found), 1,
                             f"symlinked root double-counted: {found}")
        finally:
            os.environ["HOME"] = old_h
            if old_r is None: os.environ.pop("OMNIGAUGE_ROOTS", None)
            else: os.environ["OMNIGAUGE_ROOTS"] = old_r

    def test_unplugged_root_is_named_not_silent(self):
        gone = os.path.join(_TMP, "unplugged-ssd")
        old = os.environ.get("OMNIGAUGE_ROOTS")
        os.environ["OMNIGAUGE_ROOTS"] = gone
        try:
            self.assertIn(gone, og.missing_roots())
        finally:
            if old is None: os.environ.pop("OMNIGAUGE_ROOTS", None)
            else: os.environ["OMNIGAUGE_ROOTS"] = old

    def test_roots_file_comments_and_blanks(self):
        old_data = og.DATA
        og.DATA = os.path.join(_TMP, "roots-data")
        os.makedirs(og.DATA, exist_ok=True)
        with open(os.path.join(og.DATA, "roots"), "w") as fh:
            fh.write("# a comment\n\n/somewhere/drive\n")
        try:
            self.assertIn("/somewhere/drive", og.config_roots())
        finally:
            og.DATA = old_data

    def test_check_names_unplugged_root_in_cron_output(self):
        env = dict(os.environ,
                   OMNIGAUGE_HOME=os.path.join(_TMP, "chk-home"),
                   OMNIGAUGE_ROOTS=os.path.join(_TMP, "chk-not-there"))
        r = subprocess.run([sys.executable, os.path.join(ROOT, "omnigauge"),
                            "--check", "--quiet"],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertIn("NOTICE: configured root not mounted", r.stdout)
        self.assertEqual(r.returncode, 0,
                         "an unplugged drive is a notice, not an alarm")

    def test_claude_files_discovery_matches_builtin_and_descends(self):
        """The mirror OVERRIDES the built-in at load, so a discovery fix that
        lands in only one of them silently unfixes itself on the next install.
        That is exactly how subagent transcripts (project/<sess>/subagents/
        agent-*.jsonl) vanished from LIFETIME and BY MODEL while 64 tests
        stayed green: this class locked parsers and specs but never files().
        Identical trees through both copies, identical answers - and the
        nested file MUST be in them."""
        home = os.path.join(_TMP, "conf-home-claude")
        deep = os.path.join(home, ".claude", "projects", "-p", "sess",
                            "subagents")
        os.makedirs(deep, exist_ok=True)
        top = os.path.join(home, ".claude", "projects", "-p", "a.jsonl")
        sub = os.path.join(deep, "agent-x.jsonl")
        for p in (top, sub):
            with open(p, "w") as fh:
                fh.write("{}\n")
        old = os.environ["HOME"]
        os.environ["HOME"] = home
        try:
            builtin = sorted(og.claude_files())
            mirror = sorted(self.plug.files())
        finally:
            os.environ["HOME"] = old
        self.assertEqual(builtin, mirror,
                         "claude files() drift: builtin vs mirror")
        self.assertIn(sub, builtin, "subagent transcript not discovered")
        self.assertIn(top, builtin)

    def test_codex_and_grok_files_discovery_match_builtin(self):
        home = os.path.join(_TMP, "conf-home-cx")
        cx = os.path.join(home, ".codex", "sessions", "2026", "08")
        gk = os.path.join(home, ".grok", "sessions", "aa", "bb")
        os.makedirs(cx, exist_ok=True)
        os.makedirs(gk, exist_ok=True)
        cxf = os.path.join(cx, "rollout.jsonl")
        gkf = os.path.join(gk, "updates.jsonl")
        for p in (cxf, gkf):
            with open(p, "w") as fh:
                fh.write("{}\n")
        old = os.environ["HOME"]
        os.environ["HOME"] = home
        try:
            self.assertEqual(sorted(og.codex_files()),
                             sorted(self.plug_codex.files()),
                             "codex files() drift: builtin vs mirror")
            self.assertIn(cxf, og.codex_files(),
                          "nested codex rollout not discovered")
            self.assertEqual(sorted(og.grok_files()),
                             sorted(self.plug_grok.files()),
                             "grok files() drift: builtin vs mirror")
            self.assertIn(gkf, og.grok_files())
        finally:
            os.environ["HOME"] = old

    def test_codex_scan_matches_builtin_including_tail_path(self):
        small = os.path.join(_TMP, "codex-small.jsonl")
        with open(small, "w") as fh:
            fh.write('{"model":"gpt-x"}\n')
            fh.write(json.dumps({"info": {"total_token_usage": {
                "input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 3,
                "reasoning_output_tokens": 2, "total_tokens": 20}}}) + "\n")
            fh.write(json.dumps({"info": {"total_token_usage": {
                "input_tokens": 100, "output_tokens": 50, "cached_input_tokens": 30,
                "reasoning_output_tokens": 20, "total_tokens": 200}}}) + "\n")
        big = os.path.join(_TMP, "codex-big.jsonl")
        with open(big, "w") as fh:
            pad = json.dumps({"noise": "x" * 200})
            for _ in range(6000):                    # >1MB: forces the tail read
                fh.write(pad + "\n")
            fh.write('{"model":"gpt-y"}\n')
            fh.write(json.dumps({"info": {"total_token_usage": {
                "total_tokens": 777, "input_tokens": 7, "output_tokens": 7}}}) + "\n")
        for p in (small, big):
            self.assertEqual(self.plug_codex.scan(p, 0), og.scan_codex(p, 0), p)
        self.assertEqual(og.scan_codex(small, 0)["total"], 200)   # last total wins
        self.assertEqual(og.scan_codex(big, 0)["total"], 777)
        self.assertIn("gpt-y", og.scan_codex(big, 0)["models"])

    def test_grok_scan_matches_builtin(self):
        d = os.path.join(_TMP, "grok-sess")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "updates.jsonl")
        with open(p, "w") as fh:
            fh.write(json.dumps({"usage": {"totalTokens": 100}}) + "\n")
            fh.write(json.dumps({"usage": {"totalTokens": 4260}}) + "\n")
        with open(os.path.join(d, "summary.json"), "w") as fh:
            json.dump({"current_model_id": "grok-4"}, fh)
        self.assertEqual(self.plug_grok.scan(p, 0), og.scan_grok(p, 0))
        t = og.scan_grok(p, 0)
        self.assertEqual(t["total"], 4260)
        self.assertIn("grok-4", t["models"])


class TestContentPanels(unittest.TestCase):
    """The site mirrors these panels; here they obey the same laws as every
    other panel - measured frames at both widths, no fallback-risk glyphs."""

    BANNED = set("—–‘’“”→▟▛▎▋▁▂▃▄▅▆▇")

    def test_panels_measure_and_stay_ascii(self):
        og.S.on = True
        try:
            for fn in (og.why_panel, og.privacy_panel, og.donate_panel, og.about_panel):
                for W in (80, 100):
                    og.W, og.IN = W, W - 3
                    lines = render_lines(fn)
                    widths = frame_widths(lines)
                    self.assertTrue(widths, fn.__name__)
                    target = widths[0][0]
                    for w, t in widths:
                        self.assertEqual(w, target, f"{fn.__name__} ragged at W={W}:\n{t!r}")
                        self.assertLessEqual(w, W)
                    for l in lines:
                        hits = self.BANNED & set(strip_ansi(l))
                        self.assertFalse(hits, f"{fn.__name__}: {hits} in {l!r}")
        finally:
            og.W, og.IN = 100, 97


class TestCapabilities(unittest.TestCase):
    """The legend's honesty layer: every shipping source declares all seven
    capabilities in a legal state; mirrors match built-ins; a third-party
    provider appears in the legend automatically."""

    PROVIDER_FILES = ("claude", "codex", "grok", "openrouter", "moonshot",
                      "deepseek", "goose", "aider")

    @classmethod
    def setUpClass(cls):
        cls.mods = {}
        for name in cls.PROVIDER_FILES:
            spec = importlib.util.spec_from_file_location(
                f"caps_{name}", os.path.join(ROOT, "providers", f"{name}.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cls.mods[name] = mod

    def assert_caps_legal(self, caps, who):
        self.assertEqual(set(caps), set(og.CAPABILITIES), who)
        for c, v in caps.items():
            self.assertIn(og.cap_state(v), og.CAP_STATES, f"{who}/{c}: {v!r}")

    def test_every_shipping_provider_declares_legal_caps(self):
        for name, mod in self.mods.items():
            self.assert_caps_legal(mod.CAPS, name)

    def test_builtin_caps_legal(self):
        for name, caps in og.BUILTIN_CAPS.items():
            self.assert_caps_legal(caps, f"builtin:{name}")

    def test_mirror_caps_match_builtin(self):
        for name in ("claude", "codex", "grok"):
            self.assertEqual(self.mods[name].CAPS, og.BUILTIN_CAPS[name],
                             f"caps drift in {name}")

    def test_caps_notes_fit_the_reasons_panel(self):
        """Budget 58: the note prefix is 15 columns and the narrowest board
        is 76 inside - anything longer wraps, and a wrapped reason reads
        like a rendering bug. Shorten the note, don't widen the panel."""
        every = dict(og.BUILTIN_CAPS)
        every.update({n: m.CAPS for n, m in self.mods.items()})
        for who, caps in every.items():
            for c, v in caps.items():
                note = (v or "").partition(":")[2].strip()
                self.assertLessEqual(len(note), 58, f"{who}/{c}: {note!r}")

    def test_third_party_provider_appears_in_legend(self):
        import types
        fake = types.ModuleType("fakeprov")
        fake.KIND = "api"
        fake.CAPS = dict.fromkeys(og.CAPABILITIES, "unavailable: a test double")
        og.PROVIDERS["zzz-fake"] = fake
        try:
            names = [n for n, _, _ in og.legend_rows()]
            self.assertIn("zzz-fake", names)
            self.assertEqual(og.caps_for("zzz-fake"), fake.CAPS)
        finally:
            del og.PROVIDERS["zzz-fake"]

    def test_legend_renders_within_frame(self):
        og.S.on = True
        added = []
        for name, mod in self.mods.items():
            if name not in og.PROVIDERS:
                og.PROVIDERS[name] = mod; added.append(name)
        try:
            for W in (80, 100):
                og.W, og.IN = W, W - 3
                lines = render_lines(og.legend)
                widths = frame_widths(lines)
                self.assertTrue(widths)
                target = widths[0][0]
                for w, t in widths:
                    self.assertEqual(w, target, f"ragged legend at W={W}:\n{t!r}")
                    self.assertLessEqual(w, W, t)
        finally:
            for name in added:
                del og.PROVIDERS[name]
            og.W, og.IN = 100, 97


class TestApiProviders(unittest.TestCase):
    """Spend providers against fixture replies. Shapes were verified from the
    vendors' docs 2026-08-15; a live key exercises them later. What is
    asserted here: correct mapping, and errors that surface loudly."""

    @classmethod
    def setUpClass(cls):
        def load(name):
            spec = importlib.util.spec_from_file_location(
                f"api_{name}", os.path.join(ROOT, "providers", f"{name}.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        cls.orr, cls.moon, cls.dsk = load("openrouter"), load("moonshot"), load("deepseek")

    def with_reply(self, fn, reply, err=None):
        old = og._get
        og._get = lambda url, key, timeout=20: (reply, err)
        try:
            return fn()
        finally:
            og._get = old

    def test_openrouter_with_limit(self):
        r = self.with_reply(lambda: self.orr.api_usage({"openrouter_api_key": "k"}),
                            {"data": {"usage": 25.75, "limit": 100.5, "is_free_tier": False}})
        self.assertIsNone(r["err"])
        self.assertEqual(r["spend_usd"], 25.75)
        self.assertAlmostEqual(r["pct"], 25.62, places=1)
        self.assertEqual(r["unit"], "credits")

    def test_openrouter_uncapped_is_spend_only(self):
        r = self.with_reply(lambda: self.orr.api_usage({"openrouter_api_key": "k"}),
                            {"data": {"usage": 3.5, "limit": None}})
        self.assertEqual((r["spend_usd"], r["cap"], r["err"]), (3.5, None, None))

    def test_openrouter_error_surfaces(self):
        r = self.with_reply(lambda: self.orr.api_usage({"openrouter_api_key": "k"}),
                            None, err="HTTP 401")
        self.assertEqual(r["err"], "HTTP 401")

    def test_moonshot_ok_and_negative_cash_note(self):
        r = self.with_reply(lambda: self.moon.api_usage({"moonshot_api_key": "k"}),
                            {"code": 0, "status": True, "data": {
                                "available_balance": 49.58894,
                                "voucher_balance": 51.0, "cash_balance": -1.41}})
        self.assertIsNone(r["err"])
        self.assertEqual(r["balance"], 49.59)
        self.assertEqual(r["note"], "cash balance is negative")

    def test_moonshot_bad_code_is_error(self):
        r = self.with_reply(lambda: self.moon.api_usage({"moonshot_api_key": "k"}),
                            {"code": 7, "status": False})
        self.assertIn("code=7", r["err"])

    def test_deepseek_ok_with_currency(self):
        r = self.with_reply(lambda: self.dsk.api_usage({"deepseek_api_key": "k"}),
                            {"is_available": True, "balance_infos": [
                                {"currency": "CNY", "total_balance": "110.00"}]})
        self.assertEqual((r["balance"], r["currency"], r["err"]), (110.0, "CNY", None))

    def test_deepseek_depleted_carries_note(self):
        r = self.with_reply(lambda: self.dsk.api_usage({"deepseek_api_key": "k"}),
                            {"is_available": False, "balance_infos": [
                                {"currency": "USD", "total_balance": "0.00"}]})
        self.assertEqual(r["note"], "balance too low for API calls")

    def test_no_key_fails_closed(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "DEEPSEEK_API_KEY")}
        old = dict(os.environ)
        os.environ.clear(); os.environ.update(env)
        try:
            for mod in (self.orr, self.moon, self.dsk):
                r = mod.api_usage({})
                self.assertIn("no key", r["err"])
        finally:
            os.environ.clear(); os.environ.update(old)

    def test_collect_api_takes_any_x_label(self):
        """The two-slot X design predates operators with three accounts:
        any x_<label>_bearer in the creds file becomes a board row."""
        old_load, old_usage = og.load_creds, og.x_usage
        og.load_creds = lambda: {"x_acct1_bearer": "a", "x_acct3_bearer": "c",
                                 "x_empty_bearer": "", "not_a_bearer": "x"}
        og.x_usage = lambda token, label: dict(source="x", label=label, err=None)
        try:
            con = og.db()
            rows, _ = og.collect_api(con)
            con.close()
        finally:
            og.load_creds, og.x_usage = old_load, old_usage
        labels = [n for n, _, _ in rows]
        self.assertIn("x/acct1", labels)
        self.assertIn("x/acct3", labels)
        self.assertNotIn("x/empty", labels)

    def test_api_rows_render_within_frame(self):
        og.S.on = True
        rows = [
            ("openrouter", "credits", dict(spend_usd=25.75, used=25.75, cap=100.5,
                                           pct=25.62, unit="credits", err=None)),
            ("moonshot", "balance", dict(balance=49.59, currency=None,
                                         note="cash balance is negative", err=None)),
            ("deepseek", "balance", dict(balance=110.0, currency="CNY", note=None, err=None)),
            ("openai", "org · 30d", dict(spend_usd=12.34, requests=100, tokens=5_000_000, err=None)),
            ("x/acct1", "posts · cap", dict(err="HTTP 401 - needs a valid bearer")),
        ]
        for W in (80, 100):
            og.W, og.IN = W, W - 3
            texts = [og.api_row_text(n, w, r) for n, w, r in rows]
            lines = render_lines(lambda: (og.top("API SPEND & CREDITS", "x"),
                                          [og.mid(t) for t in texts], og.bot("y")))
            widths = frame_widths(lines)
            target = widths[0][0]
            for w, t in widths:
                self.assertEqual(w, target, f"ragged api panel at W={W}:\n{t!r}")
                self.assertLessEqual(w, W)
        og.W, og.IN = 100, 97


class TestVerifiedAgentProviders(unittest.TestCase):
    """goose and aider, against fixtures shaped exactly like the real files
    both were verified on (2026-08-15): a live Goose exchange recorded
    3,098/2 in usage_ledger; a live aider exchange printed 'Tokens: 797
    sent, 1 received.' into the project's history file."""

    @classmethod
    def setUpClass(cls):
        def load(name):
            spec = importlib.util.spec_from_file_location(
                f"agent_{name}", os.path.join(ROOT, "providers", f"{name}.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        cls.goose, cls.aider = load("goose"), load("aider")

    def make_goose_db(self):
        p = os.path.join(tempfile.mkdtemp(prefix="og-goose-"), "sessions.db")
        con = sqlite3.connect(p)
        con.execute("""CREATE TABLE usage_ledger (
            id INTEGER PRIMARY KEY, session_id TEXT, created_timestamp INTEGER,
            model TEXT, input_tokens INTEGER, output_tokens INTEGER,
            total_tokens INTEGER, cache_read_tokens INTEGER,
            cache_write_tokens INTEGER, cost REAL, cost_source TEXT,
            is_compaction INTEGER)""")
        rows = [("s1", 1786790743, "gpt-4o-mini-2024-07-18", 3098, 2, 3100, 0, None, 0.0004659, "estimated", 0),
                ("s1", 1786790800, "gpt-4o-mini-2024-07-18", 500, 50, 550, 100, None, 0.0001, "estimated", 0),
                ("s2", 1786700000, "gpt-5.5", 10, 5, 15, 0, 0, 0.0, "estimated", 0)]
        con.executemany("INSERT INTO usage_ledger(session_id,created_timestamp,model,"
                        "input_tokens,output_tokens,total_tokens,cache_read_tokens,"
                        "cache_write_tokens,cost,cost_source,is_compaction) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit(); con.close()
        return p

    def test_goose_sums_ledger(self):
        t = self.goose.scan(self.make_goose_db(), 0)
        self.assertEqual((t["msgs"], t["tin"], t["tout"], t["total"]),
                         (3, 3608, 57, 3665))
        self.assertEqual(t["models"]["gpt-4o-mini-2024-07-18"]["msgs"], 2)
        self.assertIn("gpt-5.5", t["models"])

    def test_goose_since_filters_per_event(self):
        t = self.goose.scan(self.make_goose_db(), 1786790750)
        self.assertEqual((t["msgs"], t["tin"], t["tout"]), (1, 500, 50))

    def test_goose_null_cache_write_counts_zero(self):
        t = self.goose.scan(self.make_goose_db(), 0)
        self.assertEqual(t["cache_write"], 0)

    AIDER = """\

# aider chat started at 2026-08-15 05:44:15

> Aider v0.86.2
> Model: gpt-4o-mini with whole edit format
> Added README.md to the chat.

#### Reply with the single word: ok

ok

> Tokens: 797 sent, 1 received. Cost: $0.00012 message, $0.00012 session.

# aider chat started at 2026-08-15 09:00:00

> Model: gpt-5.5 with diff edit format

#### bigger ask

done

> Tokens: 8.6k sent, 1,250 received. Cost: $0.02 message, $0.02 session.
"""

    def test_aider_parses_both_number_forms(self):
        p = os.path.join(_TMP, "aider-hist.md")
        with open(p, "w") as fh:
            fh.write(self.AIDER)
        t = self.aider.scan(p, 0)
        self.assertEqual(t["msgs"], 2)
        self.assertEqual(t["tin"], 797 + 8600)
        self.assertEqual(t["tout"], 1 + 1250)
        self.assertEqual(t["models"]["gpt-4o-mini"]["out"], 1)
        self.assertEqual(t["models"]["gpt-5.5"]["out"], 1250)

    def test_aider_since_gates_whole_sessions(self):
        p = os.path.join(_TMP, "aider-hist2.md")
        with open(p, "w") as fh:
            fh.write(self.AIDER)
        cut = time.mktime(time.strptime("2026-08-15 06:00:00", "%Y-%m-%d %H:%M:%S"))
        t = self.aider.scan(p, cut)
        self.assertEqual(t["msgs"], 1)
        self.assertEqual(t["tin"], 8600)

    def test_aider_files_empty_without_env(self):
        env = {k: v for k, v in os.environ.items() if k != "OMNIGAUGE_AIDER_DIRS"}
        old = dict(os.environ)
        os.environ.clear(); os.environ.update(env)
        try:
            self.assertEqual(self.aider.files(), [])
        finally:
            os.environ.clear(); os.environ.update(old)

    def test_aider_files_reads_named_roots(self):
        root = tempfile.mkdtemp(prefix="og-aider-")
        sub = os.path.join(root, "proj"); os.makedirs(sub)
        for d in (root, sub):
            with open(os.path.join(d, ".aider.chat.history.md"), "w") as fh:
                fh.write(self.AIDER)
        old = os.environ.get("OMNIGAUGE_AIDER_DIRS")
        os.environ["OMNIGAUGE_AIDER_DIRS"] = root
        try:
            self.assertEqual(len(self.aider.files()), 2)
        finally:
            if old is None:
                del os.environ["OMNIGAUGE_AIDER_DIRS"]
            else:
                os.environ["OMNIGAUGE_AIDER_DIRS"] = old


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


class TestWindowGateTrustsTheWrongClock(unittest.TestCase):
    """The window gate skips a file when its mtime predates the window.

    mtime is a proxy for "when was this last written", and the scanner reads the
    timestamp INSIDE the file. Those come from two different clocks and they can
    disagree — a restored backup, an rsync -a, a tar -x, a container with a
    skewed clock. When they disagree the file is skipped and its tokens vanish
    from the window with no error beside them.

    The tool holds the contradiction in its own hands: lifetime does not use the
    gate, so it reports the very messages the window just dropped.
    """

    def _corpus(self, home, minutes_ago=10):
        d = os.path.join(home, ".claude", "projects", "-p")
        os.makedirs(d, exist_ok=True)
        f = os.path.join(d, "s.jsonl")
        now = time.time()
        rows = []
        for i in range(5):
            ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                               time.gmtime(now - minutes_ago * 60 + i))
            rows.append(json.dumps({"timestamp": ts, "message": {
                "model": "claude-x",
                "usage": {"input_tokens": 100, "output_tokens": 200,
                          "cache_read_input_tokens": 50,
                          "cache_creation_input_tokens": 10}}}))
        with io.open(f, "w") as fh:
            fh.write("\n".join(rows) + "\n")
        return f

    def _window(self, home, data, since_s=86400):
        env = dict(os.environ, HOME=home, OMNIGAUGE_HOME=data)
        out = subprocess.run([sys.executable, os.path.join(ROOT, "omnigauge"),
                              "--json", "--lifetime", "--since", "24h"],
                             capture_output=True, text=True, env=env, timeout=120)
        d = json.loads(out.stdout)
        w = (d.get("window") or {}).get("claude") or {}
        l = (d.get("lifetime") or {}).get("claude") or {}
        return w, l

    def test_an_mtime_older_than_the_content_does_not_erase_the_window(self):
        tmp = tempfile.mkdtemp(prefix="og-clockskew-")
        home, data = os.path.join(tmp, "home"), os.path.join(tmp, "data")
        os.makedirs(home); os.makedirs(data)
        f = self._corpus(home)

        w, _ = self._window(home, data)
        self.assertEqual(w.get("msgs"), 5, "control: an honest mtime is counted")

        # The only change: the filesystem's idea of when this was written.
        # Not one byte of content differs.
        old = time.time() - 2 * 86400
        os.utime(f, (old, old))
        # Drop every cache so the second run cannot be answered from the first.
        # (The db is usage.db, not omnigauge.db — guessing the name made this a
        # no-op the first time and the test still passed, which is its own
        # lesson: a cleanup step that silently does nothing looks like one that
        # worked.)
        for name in os.listdir(data):
            if name.endswith((".db", ".db-wal", ".db-shm")):
                os.remove(os.path.join(data, name))

        w, l = self._window(home, data)
        self.assertEqual(
            w.get("msgs"), 5,
            "five messages timestamped ten minutes ago must appear in a 24h "
            "window regardless of what mtime claims; the scanner already reads "
            "the timestamp inside the file")
        self.assertEqual(
            (w.get("msgs") or 0) > 0, (l.get("msgs") or 0) > 0,
            "window and lifetime must not contradict each other silently")


class TestHumanPromotesAtTheRoundingBoundary(unittest.TestCase):
    """human() chose its unit from the raw value, then rounded to two decimals.

    999,999 is below 1e6, so it picked K and rounded 999.999 into "1000.00K".
    The board could show OUTPUT 1000.00M beside TOTAL 1.00B — the same magnitude
    in two notations, one row apart. The frame absorbed the extra characters, so
    this never broke a panel; it only ever made a reader look twice.
    """

    def test_a_value_that_rounds_to_a_thousand_takes_the_next_unit(self):
        for raw, want in ((999_999, "1.00M"), (999_999_999, "1.00B"),
                          (999_999_999_999, "1.00T")):
            self.assertEqual(og.human(raw), want,
                             f"{raw:,} rounds into the next unit")

    def test_values_below_the_boundary_are_untouched(self):
        self.assertEqual(og.human(999_000), "999.00K")
        self.assertEqual(og.human(1_000), "1.00K")
        self.assertEqual(og.human(999), "999")
        self.assertEqual(og.human(0), "0")

    def test_no_output_ever_reads_as_a_thousand_of_a_smaller_unit(self):
        for e in range(0, 16):
            for m in (1, 5, 9):
                v = m * 10 ** e
                for probe in (v - 1, v, v + 1):
                    if probe < 0:
                        continue
                    s = og.human(probe)
                    self.assertFalse(
                        s.startswith("1000."),
                        f"human({probe:,}) = {s} — a thousand of a unit is the "
                        f"next unit")


class TestCodexCumulativeIsNotMonotonic(unittest.TestCase):
    """The window value is `last - base` across the window edge.

    That is only the truth while the vendor's cumulative counter never goes
    backwards. When a rollout's counter resets — a new session reusing the file,
    a vendor-side restart — the arithmetic breaks in both directions, and the
    max(0, …) clamp turns the negative case into a confident zero.

    A file with no parseable timestamps at all cannot be placed in time. It must
    not donate its whole history to every window that happens to be asked for.
    """

    def _codex(self):
        sys.path.insert(0, os.path.join(ROOT, "providers"))
        import codex
        return codex

    def _ev(self, ts, tot):
        o = {"type": "token_count", "payload": {"info": {"total_token_usage": {
            "input_tokens": tot, "output_tokens": tot // 10,
            "total_tokens": tot + tot // 10}}}}
        if ts is not None:
            o["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))
        return json.dumps(o)

    def _scan(self, lines, since, mtime=None):
        d = tempfile.mkdtemp(prefix="og-codex-")
        f = os.path.join(d, "rollout.jsonl")
        with io.open(f, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        if mtime is not None:
            os.utime(f, (mtime, mtime))
        return self._codex().scan(f, since), f

    def test_a_reset_inside_the_window_is_not_reported_as_zero(self):
        now = time.time(); since = now - 86400
        r, _ = self._scan([self._ev(now - 3 * 86400, 1_000_000),
                           self._ev(now - 2 * 86400, 5_000_000),
                           self._ev(now - 3600, 10_000),
                           self._ev(now - 600, 150_000)], since)
        self.assertEqual(r["tin"], 150_000,
                         "the counter restarted at 10,000 and reached 150,000 "
                         "inside the window; that is what was spent")

    def test_a_reset_that_climbs_past_the_old_high_is_not_undercounted(self):
        now = time.time(); since = now - 86400
        r, _ = self._scan([self._ev(now - 30 * 86400, 5_000_000),
                           self._ev(now - 3600, 10_000),
                           self._ev(now - 600, 8_000_000)], since)
        self.assertEqual(r["tin"], 8_000_000,
                         "endpoint arithmetic hides a reset whose new run "
                         "overtakes the old total")

    def test_a_healthy_monotonic_rollout_is_unchanged(self):
        now = time.time(); since = now - 86400
        r, _ = self._scan([self._ev(now - 3 * 86400, 1_000_000),
                           self._ev(now - 600, 1_500_000)], since)
        self.assertEqual(r["tin"], 500_000)

    def test_an_unstamped_rollout_does_not_donate_its_history_to_the_window(self):
        now = time.time(); since = now - 86400
        old = now - 30 * 86400
        r, f = self._scan([self._ev(None, 1_000_000), self._ev(None, 5_000_000)],
                          since, mtime=old)
        self.assertEqual(
            r["tin"], 0,
            "no event in this file carries a timestamp, and the file has not "
            "been written for 30 days — the only evidence available says it "
            "contributed nothing to the last 24 hours")


class TestCacheToleranceHidesARewrite(unittest.TestCase):
    """The incremental cache revalidates on `abs(cached_mtime - mtime) < 1`.

    A whole second of tolerance means a file rewritten in place — same byte
    count, different contents, within a second of the last scan — is served from
    cache and the new numbers never appear. Append-only transcripts grow, so
    size usually saves us; a file rewritten atomically, restored, or rotated to a
    coincidentally equal length does not grow, and nothing else is checked.
    """

    def test_same_size_new_content_inside_the_tolerance_is_not_served_stale(self):
        data = tempfile.mkdtemp(prefix="og-cache-")
        home = tempfile.mkdtemp(prefix="og-cache-home-")
        d = os.path.join(home, ".claude", "projects", "-p")
        os.makedirs(d)
        f = os.path.join(d, "s.jsonl")

        def row(v):
            return json.dumps({"timestamp": "2026-08-15T10:00:00Z", "message": {
                "model": "m", "usage": {"input_tokens": v, "output_tokens": v}}})

        with io.open(f, "w") as fh:
            fh.write(row(100) + "\n")

        old_scanners = dict(og.SCANNERS)
        og.SCANNERS["claude"] = (lambda: [f], og.scan_claude)
        try:
            # og.db() applies MIGRATIONS; a bare executescript(SCHEMA) misses
            # any column added after the first release.
            con = sqlite3.connect(os.path.join(data, "t.db"))
            con.executescript(og.SCHEMA)
            for table, col, typ in og.MIGRATIONS:
                have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
                if col not in have:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            first = og.lifetime_totals("claude", con)
            self.assertEqual(first["tin"], 100)

            st = os.stat(f)
            with io.open(f, "w") as fh:
                fh.write(row(999) + "\n")          # identical length
            self.assertEqual(os.stat(f).st_size, st.st_size, "fixture must not grow")
            os.utime(f, (st.st_mtime + 0.4, st.st_mtime + 0.4))

            og.memo_clear()
            second = og.lifetime_totals("claude", con)
            self.assertEqual(
                second["tin"], 999,
                "the file says 999; a sub-second mtime move must not let the "
                "cache keep answering 100")
        finally:
            og.SCANNERS.clear(); og.SCANNERS.update(old_scanners)
            og.memo_clear()


class TestCodexResetUndercountsBothWindowAndLifetime(unittest.TestCase):
    """Step-summing only happened when a baseline existed.

    A rollout that sits entirely inside the window has no pre-window event, so
    there is no baseline and the value fell back to `last - 0` — the final
    cumulative. When the counter restarts, that final value is only the spend
    since the LAST restart, and everything before it is dropped.

    Window and lifetime were wrong in the same direction, which is exactly why
    the window-cannot-exceed-lifetime invariant never noticed.
    """

    def _codex(self):
        sys.path.insert(0, os.path.join(ROOT, "providers"))
        import codex
        return codex

    def _file(self, totals, now):
        d = tempfile.mkdtemp(prefix="og-reset-")
        f = os.path.join(d, "r.jsonl")
        rows = []
        for ago, tot in totals:
            rows.append(json.dumps({
                "type": "token_count",
                "payload": {"info": {"total_token_usage": {
                    "input_tokens": tot, "output_tokens": tot // 10,
                    "total_tokens": tot + tot // 10}}},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                                           time.gmtime(now - ago))}))
        with io.open(f, "w") as fh:
            fh.write("\n".join(rows) + "\n")
        return f

    def test_two_restarts_are_counted_not_collapsed_to_the_last_run(self):
        now = time.time()
        f = self._file([(7200, 5_000_000), (3600, 1_000_000), (600, 100_000)], now)
        for fn, label in ((self._codex().scan, "provider"), (og.scan_codex, "built-in")):
            w = fn(f, now - 86400)
            l = fn(f, 0)
            self.assertEqual(w["tin"], 6_100_000,
                             f"{label}: 5M then a restart to 1M then a restart "
                             f"to 100k is 6.1M spent, all of it inside the window")
            self.assertEqual(l["tin"], 6_100_000,
                             f"{label}: lifetime cannot be less than a window "
                             f"it contains")

    def test_a_monotonic_rollout_entirely_in_window_is_unchanged(self):
        now = time.time()
        f = self._file([(7200, 1_000_000), (600, 1_500_000)], now)
        for fn in (self._codex().scan, og.scan_codex):
            self.assertEqual(fn(f, now - 86400)["tin"], 1_500_000)
            self.assertEqual(fn(f, 0)["tin"], 1_500_000)


class TestCacheSurvivesAScannerChange(unittest.TestCase):
    """The cache is keyed on (mtime, size) — properties of the FILE.

    Nothing records which version of the scanner produced a cached row, so
    changing how a file is counted leaves every unchanged file answering with
    the old arithmetic. After the codex step-sum fix the board was still
    0.09% below an independent re-derivation, and would have stayed there until
    each file happened to be written again.

    A cached number must know which code made it.
    """

    def test_a_row_from_an_older_scanner_epoch_is_rescanned(self):
        data = tempfile.mkdtemp(prefix="og-epoch-")
        home = tempfile.mkdtemp(prefix="og-epoch-home-")
        d = os.path.join(home, ".claude", "projects", "-p")
        os.makedirs(d)
        f = os.path.join(d, "s.jsonl")
        with io.open(f, "w") as fh:
            fh.write(json.dumps({"timestamp": "2026-08-15T10:00:00Z", "message": {
                "model": "m", "usage": {"input_tokens": 42, "output_tokens": 0}}}) + "\n")

        old_scanners = dict(og.SCANNERS)
        og.SCANNERS["claude"] = (lambda: [f], og.scan_claude)
        try:
            con = sqlite3.connect(os.path.join(data, "t.db"))
            con.executescript(og.SCHEMA)
            for table, col, typ in og.MIGRATIONS:
                have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
                if col not in have:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

            self.assertEqual(og.lifetime_totals("claude", con)["tin"], 42)

            # Simulate a row left behind by an earlier version of the scanner:
            # the file is untouched, but the number in the cache is not what
            # today's code would produce.
            con.execute("UPDATE filecache SET tin=999999, scan_epoch=?",
                        (og.SCAN_EPOCH - 1,))
            con.commit()
            og.memo_clear()

            self.assertEqual(
                og.lifetime_totals("claude", con)["tin"], 42,
                "a row produced by a different scanner version must be "
                "re-derived, not trusted")
        finally:
            og.SCANNERS.clear(); og.SCANNERS.update(old_scanners)
            og.memo_clear()
