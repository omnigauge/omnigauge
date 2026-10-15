"""Codex call-count boundaries, in invented rollouts through both scanners."""
import json
import os
import sqlite3
import unittest

from datetime import datetime, timezone
import test_omnigauge as base

og, _TMP = base.og, base._TMP


class TestCodexCallsBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base.TestProviderConformance.setUpClass()
        cls.scanners = (og.scan_codex, base.TestProviderConformance.plug_codex.scan)

    def rollout(self, name, readings, legacy=False, pad=0, fork=False):
        path = os.path.join(_TMP, name + ".jsonl")
        with open(path, "w") as fh:
            fh.write(json.dumps({"type": "session_meta", "payload": {
                "id": name, "forked_from_id": "parent" if legacy or fork else None,
                "history_mode": "legacy" if legacy else "paginated"}}) + "\n")
            for second, total, own in readings:
                usage = lambda n: {"input_tokens": n, "output_tokens": 0,
                                   "cached_input_tokens": 0,
                                   "reasoning_output_tokens": 0, "total_tokens": n}
                stamp = datetime.fromtimestamp(100000 + second, timezone.utc).isoformat().replace("+00:00", "Z")
                fh.write(json.dumps({"timestamp": stamp, "pad": "x" * pad,
                    "type": "event_msg", "payload": {"type": "token_count", "info": {
                    "total_token_usage": usage(total), "last_token_usage": usage(own)}}}) + "\n")
        return path

    def test_a_forks_calls_still_count_after_its_counter_restarts(self):
        # V241-CLI-01: inherited totals are history, not a permanent minimum.
        p = self.rollout("fork-restart", [(0, 101000, 1000), (5, 103000, 2000),
                                           (10, 500, 500), (15, 1200, 700)], fork=True)
        for scan in self.scanners:
            for since, want in ((0, 4), (100010, 2), (100015, 1)):
                with self.subTest(scan=scan.__module__, since=since):
                    self.assertEqual(scan(p, since)["msgs"], want)

    def test_a_legacy_replay_inside_the_window_is_still_not_its_own_calls(self):
        # V241-CLI-02: a baseline in replayed history must not waive inheritance.
        # Legacy burst detection reads its producer's leading timestamp field.
        p = self.rollout("legacy-cut", [(0.1, 1000, 1000), (0.3, 2000, 1000),
                                         (0.5, 3000, 1000), (5, 3200, 200),
                                         (10, 3500, 300)], legacy=True)
        for scan in self.scanners:
            for since in (0, 100000.2, 100000.5):
                with self.subTest(scan=scan.__module__, since=since):
                    self.assertEqual(scan(p, since)["msgs"], 2)
                    self.assertEqual(scan(p, since)["total"], 500)
            with self.subTest(scan=scan.__module__, replay_only=True):
                replay = self.rollout("legacy-replay-only", [(0.1, 1000, 1000),
                    (0.3, 2000, 1000), (0.5, 3000, 1000)], legacy=True)
                self.assertEqual(scan(replay, 100000.2)["msgs"], 0)
                self.assertEqual(scan(replay, 100000.2)["total"], 0)
            self.assertEqual(scan(p, 100005)["msgs"], 2)
            self.assertEqual(scan(p, 100005.01)["msgs"], 1)

    def test_calls_before_the_tail_are_counted_in_lifetime_and_the_window(self):
        # V241-CLI-03: counts cannot be recovered from a final cumulative.
        p = self.rollout("long-calls", [(i, (i + 1) * 100, 100)
                                         for i in range(1600)] + [(1599, 160000, 100)], pad=1000)
        self.assertGreater(os.path.getsize(p), 1 << 20)
        for scan in self.scanners:
            for since, want in ((0, 1600), (99999, 1600), (100000, 1600),
                                (100800, 800), (100800.01, 799), (101600, 0)):
                with self.subTest(scan=scan.__module__, since=since):
                    self.assertEqual(scan(p, since)["msgs"], want)

    def test_epoch_five_call_counts_are_rederived_after_restart(self):
        # V241-CLI-03: unchanged files must not retain the old tail-only count.
        p = self.rollout("cached-calls", [(0, 100, 100), (5, 300, 200)])
        old_scanners = dict(og.SCANNERS)
        og.SCANNERS["codex"] = (lambda: [p], og.scan_codex)
        con = sqlite3.connect(":memory:")
        con.executescript(og.SCHEMA)
        for table, col, typ in og.MIGRATIONS:
            have = {r[1] for r in con.execute("PRAGMA table_info(" + table + ")")}
            if col not in have:
                con.execute("ALTER TABLE " + table + " ADD COLUMN " + col + " " + typ)
        try:
            og.memo_clear()
            self.assertEqual(og.lifetime_totals("codex", con)["msgs"], 2)
            con.execute("UPDATE filecache SET msgs=999, scan_epoch=5")
            con.commit()
            og.memo_clear()  # the next CLI process has no in-memory result
            self.assertEqual(og.lifetime_totals("codex", con)["msgs"], 2)
        finally:
            con.close()
            og.SCANNERS.clear(); og.SCANNERS.update(old_scanners)
            og.memo_clear()
