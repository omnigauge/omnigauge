"""Invented per-day histories; no provider or real session is contacted."""
import json
import os
import sqlite3
import time
import tracemalloc
import unittest

import test_omnigauge as base

og, _TMP = base.og, base._TMP


class TestDaysBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base.TestProviderConformance.setUpClass()
        cls.codex = (og.scan_codex, base.TestProviderConformance.plug_codex.scan)
        cls.claude = (og.scan_claude, base.TestProviderConformance.plug.scan)

    def setUp(self):
        self.saved, self.zone = dict(og.SCANNERS), os.environ.get("TZ")
        og.SCANNERS.clear(); og.memo_clear()
        self.con = sqlite3.connect(":memory:"); self.con.executescript(og.SCHEMA)
        for table, col, typ in og.MIGRATIONS:
            have = {r[1] for r in self.con.execute("PRAGMA table_info(" + table + ")")}
            if col not in have: self.con.execute("ALTER TABLE " + table + " ADD COLUMN " + col + " " + typ)

    def tearDown(self):
        self.con.close(); og.SCANNERS.clear(); og.SCANNERS.update(self.saved); og.memo_clear()
        if self.zone is None: os.environ.pop("TZ", None)
        else: os.environ["TZ"] = self.zone
        time.tzset()

    def zone_at(self, name):
        os.environ["TZ"] = name; time.tzset(); og.memo_clear()

    def claude_file(self, name, stamps):
        p = os.path.join(_TMP, name + ".jsonl")
        with open(p, "w") as fh:
            for stamp, amount in stamps:
                fh.write(json.dumps({"timestamp": stamp, "message": {"model": "made-up", "usage": {
                    "input_tokens": amount, "output_tokens": 0}}}) + "\n")
        return p

    def report(self, p, scan, now):
        og.SCANNERS["claude"] = (lambda: [p], scan)
        return og.days_report(self.con, now=og._epoch(now))["agents"]["claude"]

    def test_off_hour_midnights_keep_readings_on_their_local_day(self):
        # V250-CLI-02: an hour straddles midnight in half/quarter-hour zones.
        for zone, before, after in (("Asia/Kolkata", "2026-10-14T18:29:59Z", "2026-10-14T18:30:00Z"),
                                    ("Asia/Kathmandu", "2026-10-14T18:14:59Z", "2026-10-14T18:15:00Z"),
                                    ("Australia/Eucla", "2026-10-14T15:14:59Z", "2026-10-14T15:15:00Z")):
            self.zone_at(zone)
            p = self.claude_file(zone.replace("/", "-"), [(before, 10), (after, 20)])
            for scan in self.claude:
                with self.subTest(zone=zone, scan=scan.__module__):
                    og.memo_clear()
                    a = self.report(p, scan, "2026-10-15T12:00:00Z")
                    self.assertEqual(a["days"], [["2026-10-14", 10, 0, 1], ["2026-10-15", 20, 0, 1]])
                    self.assertEqual((a["today"]["total"], a["yesterday"]["total"], a["lifetime"]["total"]), (20, 10, 30))

    def test_short_and_long_clock_change_days_use_calendar_dates(self):
        self.zone_at("America/Chicago")
        for name, stamps, now, want in (
            ("spring", [("2026-03-08T06:00:00Z", 1), ("2026-03-09T04:59:59Z", 2), ("2026-03-09T05:00:00Z", 4)],
             "2026-03-09T12:00:00Z", [["2026-03-08", 3, 0, 2], ["2026-03-09", 4, 0, 1]]),
            ("fall", [("2026-11-01T05:00:00Z", 1), ("2026-11-02T05:59:59Z", 2), ("2026-11-02T06:00:00Z", 4)],
             "2026-11-02T12:00:00Z", [["2026-11-01", 3, 0, 2], ["2026-11-02", 4, 0, 1]])):
            p = self.claude_file(name, stamps)
            for scan in self.claude:
                with self.subTest(day=name, scan=scan.__module__):
                    og.memo_clear(); self.assertEqual(self.report(p, scan, now)["days"], want)

    def test_removed_or_unreadable_files_do_not_supply_cached_days(self):
        # V250-CLI-03: the day sum and whole-file sum use the same readable set.
        self.zone_at("UTC")
        kept = self.claude_file("kept-day", [("2026-10-15T12:00:00Z", 10)])
        gone = self.claude_file("gone-day", [("2026-10-14T12:00:00Z", 90)])
        paths = [kept, gone]
        og.SCANNERS["claude"] = (lambda: list(paths), og.scan_claude)
        self.assertEqual(og.days_report(self.con, now=og._epoch("2026-10-15T14:00:00Z"))["agents"]["claude"]["lifetime"]["total"], 100)
        os.unlink(gone); og.memo_clear()
        a = og.days_report(self.con, now=og._epoch("2026-10-15T14:00:00Z"))["agents"]["claude"]
        self.assertEqual(a["days"], [["2026-10-15", 10, 0, 1]])
        self.assertEqual((a["lifetime"]["total"], a["untimed"]), (10, 0))
        paths[:] = [kept]; og.memo_clear()
        self.assertEqual(og.days_report(self.con, now=og._epoch("2026-10-15T14:00:00Z"))["agents"]["claude"]["lifetime"]["total"], 10)

    def test_hours_whole_pass_does_not_keep_all_codex_readings_in_memory(self):
        # V250-CLI-01: memory follows the time buckets, not the reading count.
        p = os.path.join(_TMP, "many-hours.jsonl")
        with open(p, "w") as fh:
            fh.write(json.dumps({"type": "session_meta", "payload": {"id": "invented"}}) + "\n")
            for n in range(16000):
                stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1800000000 + n))
                u = {"input_tokens": n + 1, "output_tokens": 0, "cached_input_tokens": 0,
                     "reasoning_output_tokens": 0, "total_tokens": n + 1}
                fh.write(json.dumps({"timestamp": stamp, "type": "event_msg", "payload": {"type": "token_count", "info": {
                    "total_token_usage": u, "last_token_usage": dict(u, input_tokens=1, total_tokens=1)}}}) + "\n")
        self.assertGreater(os.path.getsize(p), 1 << 20)
        for scan in self.codex:
            with self.subTest(scan=scan.__module__):
                hours = getattr(og, "Hours", dict)(); tracemalloc.start()
                try: result = scan(p, 0, hours=hours); peak = tracemalloc.get_traced_memory()[1]
                finally: tracemalloc.stop()
                self.assertEqual((result["total"], result["msgs"]), (16000, 16000))
                self.assertEqual(sum(v["total"] for v in hours.values()), 16000)
                self.assertLess(peak, 12 << 20, "whole-file readings must be folded without a list and per-event set")

    def test_empty_database_is_a_complete_empty_report(self):
        self.zone_at("UTC")
        self.assertEqual(og.days_report(self.con, now=1800000000)["agents"], {})

    def test_fork_restart_and_untimed_minutes_conserve_every_field(self):
        # V250-CLI-02: subtract inheritance from its minute as well as its hour.
        fields = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_output_tokens", "total_tokens")
        stamps = ["2026-10-14T18:29:00Z", "2026-10-14T18:31:00Z", "2026-10-14T19:01:00Z"]
        readings = [((1000, 200, 100, 50, 1200), (100, 20, 10, 5, 120)),
                    ((1100, 240, 110, 60, 1340), (100, 40, 10, 10, 140)),
                    ((40, 20, 4, 10, 60), (40, 20, 4, 10, 60))]
        p = os.path.join(_TMP, "minutes-fork-restart.jsonl")
        with open(p, "w") as fh:
            fh.write(json.dumps({"type": "session_meta", "payload": {"id": "invented", "forked_from_id": "parent"}}) + "\n")
            for stamp, (total, own) in zip(stamps, readings):
                fh.write(json.dumps({"timestamp": stamp, "type": "event_msg", "payload": {"type": "token_count", "info": {
                    "total_token_usage": dict(zip(fields, total)), "last_token_usage": dict(zip(fields, own))}}}) + "\n")
        for scan in self.codex:
            for since in (0, og._epoch(stamps[1])):
                with self.subTest(scan=scan.__module__, since=since):
                    hours = og.Hours(); t = scan(p, since, hours=hours)
                    for k in og.HOUR_FIELDS:
                        self.assertEqual(sum(h[k] for h in hours.values()), t[k], k)
                        self.assertEqual(sum(h[k] for h in hours.minutes.values()), t[k], k)
                    if not since:
                        self.assertEqual(hours.minutes[int(og._epoch(stamps[0]) // 60)]["total"], 120)
                        self.assertEqual(t["total"], 320)
        untimed = self.claude_file("untimed-hours", [("not-a-time", 7), (stamps[1], 11)])
        for scan in self.claude:
            hours = og.Hours(); t = scan(untimed, hours=hours)
            self.assertEqual(t["total"], 18)
            self.assertEqual(sum(v["total"] for v in hours.minutes.values()), 11)

    def test_epoch_seven_is_rebuilt_and_prune_removes_both_bucket_tables(self):
        # V250-CLI-02/03: unchanged old cache rows cannot preserve coarse days.
        self.zone_at("UTC")
        p = self.claude_file("old-cache-hours", [("2026-10-15T12:31:00Z", 10)])
        og.SCANNERS["claude"] = (lambda: [p], og.scan_claude)
        og.lifetime_totals("claude", self.con)
        self.con.execute("UPDATE filecache SET scan_epoch=7, total=999")
        self.con.execute("DELETE FROM fileminutes")
        self.con.commit(); og.memo_clear()
        self.assertEqual(og.lifetime_totals("claude", self.con)["total"], 10)
        self.assertEqual(self.con.execute("SELECT sum(total) FROM fileminutes").fetchone()[0], 10)
        self.assertGreater(og.SCAN_EPOCH, 7)
        # The invented file lives in TMPDIR, outside the private HOME/config roots.
        self.assertEqual(og.prune_filecache(self.con), 1)
        self.assertEqual(self.con.execute("SELECT count(*) FROM filecache").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT count(*) FROM filehours").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT count(*) FROM fileminutes").fetchone()[0], 0)

    def test_lifetime_totals_match_hours_through_a_restart_before_the_tail(self):
        # V250-CLI-04: asking for hours must not change a file's lifetime spend.
        p = os.path.join(_TMP, "early-restart-hours.jsonl")
        with open(p, "w") as fh:
            fh.write(json.dumps({"type": "session_meta", "payload": {"id": "invented"}}) + "\n")
            for n, total in enumerate((10000, 100, 200, 300, 400, 500)):
                fh.write(json.dumps({"type": "response_item", "payload": {"text": "x" * 300000}}) + "\n")
                u = {"input_tokens": total, "output_tokens": 0, "cached_input_tokens": 0,
                     "reasoning_output_tokens": 0, "total_tokens": total}
                own = dict(u, input_tokens=10000 if not n else 100, total_tokens=10000 if not n else 100)
                fh.write(json.dumps({"timestamp": "2026-10-15T12:%02d:00Z" % n, "type": "event_msg",
                    "payload": {"type": "token_count", "info": {"total_token_usage": u, "last_token_usage": own}}}) + "\n")
        self.assertGreater(os.path.getsize(p), 1 << 20)
        for scan in self.codex:
            with self.subTest(scan=scan.__module__):
                hours = getattr(og, "Hours", dict)(); with_hours = scan(p, hours=hours); plain = scan(p)
                self.assertEqual(with_hours["total"], 10500)
                self.assertEqual(plain, with_hours)
