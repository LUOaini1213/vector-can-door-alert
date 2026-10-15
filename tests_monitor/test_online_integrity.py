"""Handwritten ASC and manually calculated minute oracles for reconciliation."""

import json
from pathlib import Path
import tempfile
import unittest

from can_monitor.integrity import checks_pass, validate_trace
from can_monitor.parser import read_asc
from can_monitor.reporting import write_report
from can_monitor.store import MonitorStore


ASC = """date Thu Oct 15 12:00:00.000 2026
base hex timestamps absolute
internal events logged
59.600000 1 100 Rx d 8 E8 03 01 00 00 00 00 00
59.600000 1 101 Rx d 8 00 00 00 00 00 00 00 00
59.700000 1 100 Rx d 8 D0 07 01 00 00 00 00 00
59.800000 1 100 Rx d 1 00
60.100000 1 777 Rx d 1 AA
60.500000 1 100 Rx d 8 B8 0B 01 00 00 00 00 00
"""


class OnlineIntegrityAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = self.root / "handwritten.asc"
        source.write_text(ASC, encoding="utf-8")
        self.trace = read_asc(source, trace_id="integrity", provenance="synthetic")
        self.other = read_asc(source, trace_id="other", provenance="synthetic")
        self.db = self.root / "monitor.duckdb"

    def snapshot(self, store, trace_id):
        return {table: store.con.execute(
            f"SELECT * FROM mon.{table} WHERE trace_id=? ORDER BY ALL", [trace_id]).fetchall()
            for table in ("traces", "frames", "events", "rejected_lines", "minute_stats")}

    def test_sql_reconciliation_matches_hand_calculated_two_minute_oracle(self):
        with MonitorStore(self.db) as store:
            store.ingest(self.trace)
            rows = store.con.execute(
                "SELECT minute_index,frame_count,invalid_frame_count,unknown_frame_count,"
                "event_start_count,timeout_duration_us,speed_mean_kmh,speed_max_kmh "
                "FROM mon.minute_stats ORDER BY minute_index").fetchall()
            # Door timeout starts at 59.900001 and has 99,999 us in minute 0.
            # In minute 1, door + vehicle timeout = 500,000 + 499,999 us.
            self.assertEqual(rows, [
                (0, 4, 1, 0, 2, 99_999, 15.0, 20.0),
                (1, 2, 0, 1, 1, 999_999, 30.0, 30.0),
            ])
            self.assertTrue(checks_pass(validate_trace(store.con, "integrity")))
            self.assertEqual(store.ingest(self.trace)["status"], "skipped")

    def test_missing_frame_is_rebuilt_on_identical_import_and_other_trace_is_preserved(self):
        with MonitorStore(self.db) as store:
            store.ingest(self.trace)
            store.ingest(self.other)
            original = self.snapshot(store, "integrity")
            other = self.snapshot(store, "other")
            store.con.execute("DELETE FROM mon.frames WHERE trace_id='integrity' AND frame_no=2")
            self.assertFalse(checks_pass(validate_trace(store.con, "integrity")))
            result = store.ingest(self.trace)
            self.assertEqual((result["status"], result["frame_count"]), ("loaded", 6))
            self.assertEqual(self.snapshot(store, "integrity"), original)
            self.assertEqual(self.snapshot(store, "other"), other)

    def test_changed_speed_fails_report_and_identical_import_repairs_aggregates(self):
        with MonitorStore(self.db) as store:
            store.ingest(self.trace)
            store.con.execute("UPDATE mon.frames SET speed_kmh=9999 "
                              "WHERE trace_id='integrity' AND frame_no=1")
        output = self.root / "report"
        with self.assertRaisesRegex(ValueError, "reconciliation failed"):
            write_report(self.db, output)
        checks = json.loads((output / "report.json").read_text(encoding="utf-8"))["reconciliation"][0]
        self.assertTrue(checks["frame_count_balanced"])
        self.assertFalse(checks["minute_metrics_balanced"])
        with MonitorStore(self.db) as store:
            self.assertEqual(store.ingest(self.trace)["status"], "loaded")
            self.assertEqual(store.con.execute("SELECT speed_kmh FROM mon.frames "
                                              "WHERE frame_no=1").fetchone()[0], 10.0)
        repaired = write_report(self.db, output)
        self.assertTrue(checks_pass(repaired["reconciliation"][0]))
        self.assertIn("does not authenticate", repaired["reconciliation_scope"])

    def test_wrong_minute_allocation_is_detected_even_when_total_duration_balances(self):
        with MonitorStore(self.db) as store:
            store.ingest(self.trace)
            store.con.execute("UPDATE mon.minute_stats SET timeout_duration_us=timeout_duration_us "
                              "+ CASE WHEN minute_index=0 THEN 1 ELSE -1 END")
            checks = validate_trace(store.con, "integrity")
            self.assertTrue(checks["timeout_duration_balanced"])
            self.assertFalse(checks["minute_metrics_balanced"])
            self.assertEqual(store.ingest(self.trace)["status"], "loaded")
            self.assertTrue(checks_pass(validate_trace(store.con, "integrity")))

    def test_each_minute_metric_is_independently_checked(self):
        with MonitorStore(self.db) as store:
            for column in ("frame_count", "invalid_frame_count", "unknown_frame_count",
                           "event_start_count", "speed_mean_kmh", "speed_max_kmh"):
                with self.subTest(column=column):
                    store.ingest(self.trace, force=True)
                    # Fixed test identifiers; no external value is SQL syntax.
                    store.con.execute(f"UPDATE mon.minute_stats SET {column}={column}+1 "
                                      "WHERE trace_id='integrity' AND minute_index=0")
                    self.assertFalse(validate_trace(store.con, "integrity")["minute_metrics_balanced"])

    def test_force_rebuild_is_explicit_boolean_and_preserves_other_trace(self):
        with MonitorStore(self.db) as store:
            store.ingest(self.trace)
            store.ingest(self.other)
            original = self.snapshot(store, "integrity")
            other = self.snapshot(store, "other")
            self.assertEqual(store.ingest(self.trace)["status"], "skipped")
            self.assertEqual(store.ingest(self.trace, force=True)["status"], "loaded")
            self.assertEqual(self.snapshot(store, "integrity"), original)
            self.assertEqual(self.snapshot(store, "other"), other)
            completed = store.con.execute("SELECT count(*) FROM mon.runs "
                                          "WHERE trace_id='integrity' AND status='COMPLETED'").fetchone()[0]
            self.assertEqual(completed, 2)
            for value in (0, 1, "true", None):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "force must be a bool"):
                    store.ingest(self.trace, force=value)

    def test_damaged_extreme_bounds_fail_without_unbounded_minute_expansion(self):
        with MonitorStore(self.db) as store:
            store.ingest(self.trace)
            store.con.execute("UPDATE mon.traces SET end_us=9000000000000000000")
            self.assertFalse(checks_pass(validate_trace(store.con, "integrity")))
            self.assertEqual(store.ingest(self.trace)["status"], "loaded")
            self.assertTrue(checks_pass(validate_trace(store.con, "integrity")))


if __name__ == "__main__":
    unittest.main()
