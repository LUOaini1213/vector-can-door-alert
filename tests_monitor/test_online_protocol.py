"""Regression fixtures for external ASC interoperability and bounded analysis."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import can
import duckdb

from can_monitor.cli import main
from can_monitor.engine import analyze_trace
from can_monitor.limits import MAX_TRACE_SPAN_US, check_trace_span
from can_monitor.parser import read_asc


SPEED_10 = "E8 03 01 00 00 00 00 00"
DOORS_CLOSED = "00 00 00 00 00 00 00 00"


class ExternalAscRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "external.asc"

    def test_unchanged_python_can_writer_output_has_no_false_rejections(self):
        # Exercise the installed independent writer, without rewriting its
        # spacing, trigger-block date, measurement metadata or record text.
        with can.ASCWriter(self.path) as writer:
            writer.on_message_received(can.Message(
                timestamp=0, arbitration_id=0x100, is_extended_id=False,
                channel=0, data=bytes.fromhex(SPEED_10)))
            writer.on_message_received(can.Message(
                timestamp=0.1, arbitration_id=0x101, is_extended_id=False,
                channel=0, is_rx=False, data=bytes(8)))
        snapshot = self.path.read_bytes()
        trace = read_asc(self.path)
        self.assertEqual(trace["source_sha256"], hashlib.sha256(snapshot).hexdigest())
        self.assertEqual(trace["rejected_lines"], [])
        self.assertEqual([(row["timestamp_us"], row["can_id"], row["channel"], row["direction"])
                          for row in trace["frames"]],
                         [(0, 0x100, 1, "Rx"), (100_000, 0x101, 1, "Tx")])
        physical_lines = snapshot.decode("utf-8").splitlines()
        for frame in trace["frames"]:
            self.assertEqual(frame["raw_line"], physical_lines[frame["line_number"] - 1])

    def test_header_whitespace_is_flexible_but_bad_records_stay_isolated(self):
        bad = "0.000001 1 100 Rx d 8 E8 03"
        good = f"0.000000 1 100 Rx d 8 {SPEED_10}"
        for header in ["base hex  timestamps absolute", "BASE\tHEX\tTIMESTAMPS\tABSOLUTE"]:
            with self.subTest(header=header):
                self.path.write_text(header + "\n" + good + "\n" + bad + "\n", encoding="utf-8")
                trace = read_asc(self.path)
                self.assertEqual(len(trace["frames"]), 1)
                self.assertEqual(trace["rejected_lines"], [
                    {"line_number": 3, "raw_line": bad, "reason": "DLC_MISMATCH"}])
        for header in ["base\thex timestamps relative", "base dec timestamps absolute", "base"]:
            with self.subTest(header=header):
                self.path.write_text(header + "\n" + good + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "only base hex timestamps absolute"):
                    read_asc(self.path)

    def test_parser_rejects_extreme_span_without_constructing_minute_rows(self):
        self.path.write_text(
            "base hex timestamps absolute\n"
            f"0.000000 1 100 Rx d 8 {SPEED_10}\n"
            "9000000000000.000000 1 777 Rx d 0\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "24 hours"):
            read_asc(self.path)

    def test_span_boundary_and_invalid_types_are_explicit(self):
        check_trace_span(1_000_000, 1_000_000 + MAX_TRACE_SPAN_US)
        check_trace_span(0, 0)
        for start, end in [(0, MAX_TRACE_SPAN_US + 1), (True, 1), (0, True),
                           (-1, 0), (2, 1), (0.0, 1), (0, "1")]:
            with self.subTest(start=start, end=end), self.assertRaisesRegex(ValueError, "24 hours"):
                check_trace_span(start, end)

    def test_direct_analysis_api_checks_span_before_minute_expansion(self):
        self.path.write_text(
            "base hex timestamps absolute\n"
            f"0.000000 1 100 Rx d 8 {SPEED_10}\n", encoding="utf-8")
        trace = read_asc(self.path)
        trace["end_us"] = MAX_TRACE_SPAN_US + 1
        with patch("can_monitor.engine._minute_stats") as summarize:
            with self.assertRaisesRegex(ValueError, "24 hours"):
                analyze_trace(trace)
            summarize.assert_not_called()


class MonitorCliRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "channel2.asc"
        rows = ["base hex timestamps absolute"]
        for timestamp in ["0.000000", "0.100000", "0.400000"]:
            rows += [f"{timestamp} 2 100 Rx d 8 {SPEED_10}",
                     f"{timestamp} 2 101 Rx d 8 {DOORS_CLOSED}"]
        self.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        self.db = self.root / "monitor.duckdb"
        self.args = ["ingest", str(self.path), "--trace-id", "CH2", "--db", str(self.db),
                     "--output", str(self.root / "report"), "--expected-channel", "2"]

    def run_cli(self, args):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = main(args)
        self.assertEqual(status, 0, error.getvalue())
        return json.loads(output.getvalue())

    def test_cli_channel_two_has_no_phantom_channel_one_timeout(self):
        result = self.run_cli(self.args)
        self.assertEqual(result["imports"][0]["status"], "loaded")
        with duckdb.connect(str(self.db), read_only=True) as con:
            config = json.loads(con.execute("SELECT config_json FROM mon.traces").fetchone()[0])
            self.assertEqual(config["expected_channels"], [2])
            self.assertEqual(con.execute("SELECT count(*) FROM mon.events").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT DISTINCT channel FROM mon.frames").fetchall(), [(2,)])

    def test_repeatable_channel_option_keeps_explicit_monitoring_scope(self):
        self.run_cli(self.args + ["--expected-channel", "1"])
        with duckdb.connect(str(self.db), read_only=True) as con:
            config = json.loads(con.execute("SELECT config_json FROM mon.traces").fetchone()[0])
            self.assertEqual(config["expected_channels"], [1, 2])
            # Channel 1 was explicitly requested, so its missing-signal events
            # are intentional. Channel 2 samples remain fresh at the boundary.
            self.assertEqual(con.execute("SELECT DISTINCT channel FROM mon.events").fetchall(), [(1,)])

    def test_force_reaches_real_store_and_rebuilds_an_identical_source(self):
        self.assertEqual(self.run_cli(self.args)["imports"][0]["status"], "loaded")
        self.assertEqual(self.run_cli(self.args)["imports"][0]["status"], "skipped")
        self.assertEqual(self.run_cli(self.args + ["--force"])["imports"][0]["status"], "loaded")
        with duckdb.connect(str(self.db), read_only=True) as con:
            statuses = dict(con.execute("SELECT status,count(*) FROM mon.runs GROUP BY status").fetchall())
            self.assertEqual(statuses, {"COMPLETED": 2, "SKIPPED": 1})
            self.assertEqual(con.execute("SELECT count(*) FROM mon.frames").fetchone()[0], 6)


if __name__ == "__main__":
    unittest.main()
