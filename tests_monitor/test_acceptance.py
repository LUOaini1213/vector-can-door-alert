"""Hand-calculated fixtures: no production encoder or stored report is an oracle.

ASC rows are intentionally tiny.  The timeout expectations below are computed
from the documented 300,000 us fresh interval, not by rerunning an implementation
of the monitor's state machine inside the tests.
"""

import csv
import hashlib
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from can_monitor.engine import RuleConfig, analyze_trace
from can_monitor.parser import read_asc
from can_monitor.queries import MonitorQueries
from can_monitor.reporting import write_report
from can_monitor.store import MonitorStore
import can_monitor.store as monitor_store_module


HEADER = (
    "date Thu Oct 15 12:00:00.000 2026\n"
    "base hex timestamps absolute\n"
    "internal events logged\n"
)
# Explicit wire bytes let these checks detect an encoder/decoder shared mistake.
SPEED_0 = "00 00 01 00 00 00 00 00"
SPEED_10 = "E8 03 01 00 00 00 00 00"
SPEED_20 = "D0 07 01 00 00 00 00 00"
SPEED_30 = "B8 0B 01 00 00 00 00 00"
SPEED_40_01 = "A1 0F 01 00 00 00 00 00"
SPEED_50 = "88 13 01 00 00 00 00 00"
SPEED_100 = "10 27 01 00 00 00 00 00"
SPEED_130 = "C8 32 01 00 00 00 00 00"
DOORS_CLOSED = "00 00 00 00 00 00 00 00"


def asc_row(us, can_id, payload, channel=1, direction="Rx"):
    """Only formats a line; all test signal payloads above are handwritten."""
    seconds, remainder = divmod(us, 1_000_000)
    dlc = len(payload.split())
    return (f"{seconds}.{remainder:06d} {channel} {can_id:X} {direction} "
            f"d {dlc} {payload}").rstrip()


def manual_trace(rows, trace_id="hand-timing"):
    """Build the parser contract directly to isolate timing tests from parsing."""
    frames = []
    for ordinal, (us, can_id, payload, *channel) in enumerate(rows, 1):
        channel = channel[0] if channel else 1
        line = asc_row(us, can_id, payload, channel)
        frames.append({
            "frame_no": ordinal, "line_number": ordinal + 3,
            "timestamp_us": us, "can_id": can_id, "channel": channel,
            "direction": "Rx", "dlc": len(payload.split()),
            "data_hex": payload, "raw_line": line,
        })
    source = (HEADER + "\n".join(frame["raw_line"] for frame in frames) + "\n").encode()
    return {
        "trace_id": trace_id, "source_name": "handwritten.asc",
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "provenance": "synthetic",
        "start_us": frames[0]["timestamp_us"],
        "end_us": frames[-1]["timestamp_us"],
        "frames": frames, "rejected_lines": [],
    }


def events_for(result, rule, can_id=None, channel=None):
    return [event for event in result["events"]
            if event["rule"] == rule
            and (can_id is None or event["can_id"] == can_id)
            and (channel is None or event["channel"] == channel)]


class AscParserAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "small.asc"

    def write(self, rows, header=HEADER, bom=False):
        content = (header + "\n".join(rows) + "\n").encode("utf-8")
        self.path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + content)
        return self.path

    def test_byte_hash_physical_lines_duplicates_and_unknown_ids_are_preserved(self):
        first = asc_row(0, 0x100, SPEED_10)
        self.write(["// an ordinary comment", first, first,
                    asc_row(1, 0x777, "AB CD", channel=2, direction="Tx")], bom=True)
        trace = read_asc(self.path, trace_id="parser-fixture", provenance="synthetic")
        self.assertEqual(trace["source_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(trace["source_name"], "small.asc")
        self.assertEqual(trace["provenance"], "synthetic")
        self.assertEqual([f["frame_no"] for f in trace["frames"]], [1, 2, 3])
        self.assertEqual([f["line_number"] for f in trace["frames"]], [5, 6, 7])
        self.assertEqual([f["timestamp_us"] for f in trace["frames"]], [0, 0, 1])
        self.assertEqual(trace["frames"][0]["raw_line"], first)
        self.assertEqual(trace["frames"][1]["data_hex"], SPEED_10)
        last = trace["frames"][2]
        self.assertEqual((last["can_id"], last["channel"], last["direction"], last["dlc"]),
                         (0x777, 2, "Tx", 2))
        self.assertEqual(trace["rejected_lines"], [])

    def test_bad_and_unsupported_candidate_rows_have_exact_source_references(self):
        bad_rows = [
            "0.010000 1 100 Rx d 3 00",  # claimed payload length differs
            "0.020000 1 800 Rx d 0",  # outside standard 11-bit identifiers
            "0.030000 1 100 Rx r 0",  # remote frame is not a data frame
            "0.040000 CANFD 1 Rx 100 0 0 8 8 00 00 00 00 00 00 00 00",
            "0.0500001 1 100 Rx d 0",  # cannot represent exact integer microseconds
            "-0.010000 1 100 Rx d 0",  # negative timestamp
        ]
        self.write([asc_row(0, 0x100, SPEED_10), *bad_rows,
                    asc_row(60_000, 0x101, DOORS_CLOSED)])
        trace = read_asc(self.path)
        self.assertEqual([f["line_number"] for f in trace["frames"]], [4, 11])
        self.assertEqual([r["line_number"] for r in trace["rejected_lines"]], list(range(5, 11)))
        self.assertEqual([r["raw_line"] for r in trace["rejected_lines"]], bad_rows)
        self.assertTrue(all(r["reason"] for r in trace["rejected_lines"]))

    def test_backwards_accepted_frame_is_a_trace_error(self):
        self.write([asc_row(20, 0x100, SPEED_10), asc_row(19, 0x101, DOORS_CLOSED)])
        with self.assertRaises(ValueError):
            read_asc(self.path)

    def test_extreme_timestamps_are_isolated_exactly_without_decimal_rounding_or_overflow(self):
        extreme_rows = [
            "60.0000000000000000000000000001 1 100 Rx d 0",
            "1e999999999 1 100 Rx d 0",
        ]
        self.write([asc_row(0, 0x100, SPEED_10), *extreme_rows,
                    asc_row(61_000_000, 0x101, DOORS_CLOSED)])
        trace = read_asc(self.path)
        self.assertEqual([f["timestamp_us"] for f in trace["frames"]], [0, 61_000_000])
        self.assertEqual([f["line_number"] for f in trace["frames"]], [4, 7])
        self.assertEqual([r["line_number"] for r in trace["rejected_lines"]], [5, 6])
        self.assertEqual([r["raw_line"] for r in trace["rejected_lines"]], extreme_rows)
        self.assertTrue(all(r["reason"] for r in trace["rejected_lines"]))

    def test_relative_header_missing_header_no_frames_and_unsafe_trace_id_fail(self):
        valid = [asc_row(0, 0x100, SPEED_10)]
        for header, rows in [
            (HEADER.replace("timestamps absolute", "timestamps relative"), valid),
            ("date Thu Oct 15 12:00:00 2026\n", valid),
            (HEADER, ["// no messages"]),
        ]:
            with self.subTest(header=header, rows=rows):
                self.write(rows, header=header)
                with self.assertRaises(ValueError):
                    read_asc(self.path)
        self.write(valid)
        for trace_id in ["../outside", "a' OR 1=1 --", "", "x" * 65]:
            with self.subTest(trace_id=trace_id), self.assertRaises(ValueError):
                read_asc(self.path, trace_id=trace_id)


class MonitorTimingAcceptance(unittest.TestCase):
    def test_fixed_dbc_decode_invalid_signals_and_unknown_frames(self):
        trace = manual_trace([
            (0, 0x100, SPEED_10),
            (0, 0x101, "05 00 00 00 00 00 00 00"),
            (0, 0x200, "01 00 03 00 00 00 00 00"),
            (0, 0x777, "AB CD"),
            (0, 0x100, "00"),
            (0, 0x100, "FF FF 01 00 00 00 00 00"),
        ])
        result = analyze_trace(trace)
        frames = result["frames"]
        self.assertEqual([f["decode_status"] for f in frames],
                         ["valid", "valid", "valid", "unknown", "invalid", "invalid"])
        self.assertEqual((frames[0]["speed_kmh"], frames[0]["ignition"]), (10.0, True))
        self.assertEqual(frames[1]["door_mask"], 5)
        self.assertEqual((frames[2]["warning"], frames[2]["data_fault"], frames[2]["reason_code"]),
                         (True, False, 3))
        self.assertEqual(frames[3]["raw_line"], trace["frames"][3]["raw_line"])
        self.assertEqual([e["frame_no"] for e in events_for(result, "SIGNAL_INVALID")], [5, 6])
        self.assertTrue(all(e["duration_us"] == 0 for e in result["events"]))

    def test_fresh_at_300_ms_and_first_timeout_at_next_microsecond(self):
        base = [(0, 0x100, SPEED_10), (0, 0x101, DOORS_CLOSED)]
        fresh = analyze_trace(manual_trace(base + [(300_000, 0x777, "00")]))
        self.assertEqual(events_for(fresh, "MESSAGE_TIMEOUT"), [])
        expired = analyze_trace(manual_trace(base + [(300_001, 0x777, "00")]))
        timeout = events_for(expired, "MESSAGE_TIMEOUT")
        self.assertEqual(len(timeout), 2)
        self.assertEqual({e["can_id"] for e in timeout}, {0x100, 0x101})
        for event in timeout:
            self.assertEqual((event["start_us"], event["end_us"], event["duration_us"]),
                             (300_001, 300_001, 0))
            self.assertTrue(event["open_at_end"])
            self.assertIsNone(event["recovery_frame_no"])

    def test_first_input_missing_uses_trace_start_grace_without_future_extrapolation(self):
        result = analyze_trace(manual_trace([
            (0, 0x100, SPEED_10), (500_000, 0x101, DOORS_CLOSED),
            (600_000, 0x777, "00"),
        ]))
        door, = events_for(result, "MESSAGE_TIMEOUT", 0x101)
        self.assertEqual((door["start_us"], door["end_us"], door["duration_us"]),
                         (300_001, 500_000, 199_999))
        self.assertIsNone(door["frame_no"])
        self.assertIsNone(door["previous_frame_no"])
        self.assertEqual(door["recovery_frame_no"], 2)
        self.assertFalse(door["open_at_end"])
        vehicle, = events_for(result, "MESSAGE_TIMEOUT", 0x100)
        self.assertEqual((vehicle["start_us"], vehicle["end_us"], vehicle["duration_us"]),
                         (300_001, 600_000, 299_999))
        self.assertTrue(vehicle["open_at_end"])
        short = analyze_trace(manual_trace([(0, 0x777, "00")]))
        self.assertEqual(short["events"], [])

    def test_invalid_frame_does_not_recover_or_refresh_a_timeout(self):
        result = analyze_trace(manual_trace([
            (0, 0x100, SPEED_10), (0, 0x101, DOORS_CLOSED),
            (400_000, 0x100, "00"), (500_000, 0x100, SPEED_20),
            (600_000, 0x777, "00"),
        ]))
        vehicle, = events_for(result, "MESSAGE_TIMEOUT", 0x100)
        self.assertEqual((vehicle["start_us"], vehicle["end_us"], vehicle["duration_us"]),
                         (300_001, 500_000, 199_999))
        self.assertEqual((vehicle["frame_no"], vehicle["previous_frame_no"],
                          vehicle["recovery_frame_no"]), (1, 1, 4))
        invalid, = events_for(result, "SIGNAL_INVALID")
        self.assertEqual((invalid["frame_no"], invalid["start_us"], invalid["end_us"]),
                         (3, 400_000, 400_000))

    def test_recovery_on_first_expired_microsecond_is_closed_zero_duration_event(self):
        result = analyze_trace(manual_trace([
            (0, 0x100, SPEED_10), (300_001, 0x100, SPEED_10),
        ]))
        event, = events_for(result, "MESSAGE_TIMEOUT", 0x100)
        self.assertEqual((event["start_us"], event["end_us"], event["duration_us"]),
                         (300_001, 300_001, 0))
        self.assertFalse(event["open_at_end"])
        self.assertEqual(event["recovery_frame_no"], 2)

    def test_channels_do_not_recover_or_supply_each_others_speed_baseline(self):
        result = analyze_trace(manual_trace([
            (0, 0x100, SPEED_0, 1), (0, 0x101, DOORS_CLOSED, 1),
            (100_000, 0x100, SPEED_100, 2),
            (500_000, 0x101, DOORS_CLOSED, 1),
            (600_000, 0x100, SPEED_0, 1),
        ]))
        self.assertEqual(events_for(result, "SPEED_JUMP"), [])
        vehicle, = events_for(result, "MESSAGE_TIMEOUT", 0x100)
        self.assertEqual((vehicle["channel"], vehicle["start_us"], vehicle["end_us"],
                          vehicle["recovery_frame_no"]), (1, 300_001, 600_000, 5))
        self.assertTrue(all(e["channel"] == 1 for e in events_for(result, "MESSAGE_TIMEOUT")))

    def test_speed_threshold_zero_dt_duplicates_gap_and_invalid_baseline(self):
        result = analyze_trace(manual_trace([
            (0, 0x100, SPEED_10),
            (100_000, 0x100, SPEED_20),  # exactly 100 km/h/s: no event
            (200_000, 0x100, SPEED_30),  # exactly 100 again
            (300_000, 0x100, SPEED_40_01),  # 100.1: event
            (300_000, 0x100, SPEED_40_01),  # identical duplicate: no event
            (300_000, 0x100, SPEED_50),  # changed with dt=0: point event
            (600_001, 0x100, SPEED_100),  # gap > 300 ms: restart baseline
            (700_001, 0x100, "00"),  # invalid must not replace baseline
            (800_001, 0x100, SPEED_130),  # 30 / .2 = 150: event
        ]))
        jumps = events_for(result, "SPEED_JUMP")
        self.assertEqual([(e["frame_no"], e["previous_frame_no"]) for e in jumps],
                         [(4, 3), (6, 5), (9, 7)])
        self.assertTrue(all(e["duration_us"] == 0 and e["detail"] for e in jumps))
        self.assertEqual(len(result["frames"]), 9)

    def test_timeout_signal_time_is_split_at_minute_boundary_without_double_counting(self):
        result = analyze_trace(manual_trace([
            (59_600_000, 0x100, SPEED_10),
            (59_600_000, 0x101, DOORS_CLOSED),
            (60_400_000, 0x777, "00"),
            (60_500_000, 0x100, SPEED_10),
        ]))
        rows = result["minute_stats"]
        self.assertEqual([r["minute_index"] for r in rows], [0, 1])
        self.assertEqual([r["frame_count"] for r in rows], [2, 2])
        self.assertEqual([r["event_start_count"] for r in rows], [2, 0])
        # Each ID is late for 99,999 us before minute 1 and 500,000 us after it.
        self.assertEqual([r["timeout_duration_us"] for r in rows], [199_998, 1_000_000])
        self.assertEqual(sum(r["timeout_duration_us"] for r in rows),
                         sum(e["duration_us"] for e in events_for(result, "MESSAGE_TIMEOUT")))
        self.assertEqual([r["speed_mean_kmh"] for r in rows], [10.0, 10.0])
        self.assertEqual([r["unknown_frame_count"] for r in rows], [0, 1])

    def test_full_minute_without_frames_still_receives_timeout_duration_and_no_speed(self):
        result = analyze_trace(manual_trace([
            (0, 0x100, SPEED_10), (0, 0x101, DOORS_CLOSED),
            (121_000_000, 0x777, "AB"),
        ]))
        rows = result["minute_stats"]
        self.assertEqual([r["minute_index"] for r in rows], [0, 1, 2])
        self.assertEqual([r["frame_count"] for r in rows], [2, 0, 1])
        # Two signals: [300001, 60000000), the full next minute, then 1 second.
        self.assertEqual([r["timeout_duration_us"] for r in rows],
                         [119_399_998, 120_000_000, 2_000_000])
        self.assertEqual([r["speed_mean_kmh"] for r in rows], [10.0, None, None])
        self.assertEqual([r["speed_max_kmh"] for r in rows], [10.0, None, None])

    def test_config_is_validated_and_event_ids_are_deterministic(self):
        for kwargs in [
            {"timeout_ms": 0}, {"timeout_ms": -1}, {"timeout_ms": math.nan},
            {"timeout_ms": math.inf}, {"max_acceleration_kmh_s": 0},
            {"max_acceleration_kmh_s": math.nan},
            {"expected_channels": (0,)}, {"expected_channels": (1, 1)},
            {"expected_channels": (True,)}, {"expected_channels": (1.5,)},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RuleConfig(**kwargs)
        trace = manual_trace([(0, 0x100, SPEED_10), (400_000, 0x100, SPEED_20)])
        result = analyze_trace(trace)
        repeated = analyze_trace(trace)
        self.assertEqual(result["events"], repeated["events"])
        self.assertEqual(len({e["event_id"] for e in result["events"]}), len(result["events"]))
        for event in result["events"]:
            self.assertEqual(event["duration_us"], event["end_us"] - event["start_us"])


class StoreAndQueryAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "monitor.duckdb"

    def parsed(self, trace_id, rows, extra_lines=()):
        path = self.root / f"{trace_id}.asc"
        path.write_text(HEADER + "\n".join(rows) + "\n" + "\n".join(extra_lines), encoding="utf-8")
        return read_asc(path, trace_id=trace_id, provenance="synthetic")

    @staticmethod
    def snapshot(store):
        return {table: store.con.execute(f"SELECT * FROM mon.{table} ORDER BY ALL").fetchall()
                for table in ["traces", "frames", "rejected_lines", "events", "minute_stats"]}

    def test_same_trace_skips_changed_trace_replaces_and_other_trace_is_preserved(self):
        initial = [asc_row(0, 0x100, SPEED_10), asc_row(0, 0x101, DOORS_CLOSED)]
        alpha = self.parsed("alpha", initial)
        beta = self.parsed("beta", initial)
        with MonitorStore(self.db) as store:
            first = store.ingest(alpha)
            store.ingest(beta)
            before = self.snapshot(store)
            skipped = store.ingest(alpha)
            self.assertEqual(skipped["status"], "skipped")
            self.assertEqual(skipped["fingerprint"], first["fingerprint"])
            self.assertEqual(self.snapshot(store), before)
            replacement = self.parsed("alpha", [asc_row(0, 0x100, SPEED_20),
                                               asc_row(0, 0x101, DOORS_CLOSED),
                                               asc_row(100_000, 0x777, "AB")])
            loaded = store.ingest(replacement)
            self.assertEqual((loaded["status"], loaded["frame_count"]), ("loaded", 3))
            self.assertNotEqual(loaded["fingerprint"], first["fingerprint"])
            self.assertEqual(store.con.execute("SELECT trace_id, count(*) FROM mon.frames GROUP BY trace_id ORDER BY trace_id").fetchall(),
                             [("alpha", 3), ("beta", 2)])
            self.assertEqual(store.con.execute("SELECT trace_id, speed_kmh FROM mon.frames WHERE can_id=256 ORDER BY trace_id").fetchall(),
                             [("alpha", 20.0), ("beta", 10.0)])
            self.assertEqual(store.con.execute("SELECT count(*) FROM mon.runs WHERE status='SKIPPED'").fetchone()[0], 1)

    def test_after_delete_failure_rolls_back_all_published_tables_but_keeps_failed_audit(self):
        first = self.parsed("rollback", [asc_row(0, 0x100, SPEED_10),
                                         asc_row(400_000, 0x101, DOORS_CLOSED)])
        with MonitorStore(self.db) as store:
            store.ingest(first)
            before = self.snapshot(store)
            changed = self.parsed("rollback", [asc_row(0, 0x100, SPEED_20)])
            with self.assertRaises(RuntimeError):
                store.ingest(changed, failpoint="after_delete")
            self.assertEqual(self.snapshot(store), before)
            statuses = [row[0] for row in store.con.execute("SELECT status FROM mon.runs").fetchall()]
            self.assertEqual(sorted(statuses), ["COMPLETED", "FAILED"])
            failed = store.con.execute("SELECT trace_id, message, finished_at FROM mon.runs WHERE status='FAILED'").fetchone()
            self.assertEqual(failed[0], "rollback")
            self.assertTrue(failed[1])
            self.assertIsNotNone(failed[2])

    def test_config_change_replaces_instead_of_skipping_then_uses_new_fingerprint(self):
        trace = self.parsed("config-change", [asc_row(0, 0x100, SPEED_10),
                                              asc_row(100_000, 0x100, SPEED_20)])
        with MonitorStore(self.db) as store:
            first = store.ingest(trace)
            new_config = RuleConfig(max_acceleration_kmh_s=50)
            changed = store.ingest(trace, config=new_config)
            self.assertEqual(changed["status"], "loaded")
            self.assertNotEqual(changed["fingerprint"], first["fingerprint"])
            self.assertEqual(store.con.execute("SELECT count(*) FROM mon.events WHERE rule='SPEED_JUMP'").fetchone()[0], 1)
            self.assertEqual(store.ingest(trace, config=new_config)["status"], "skipped")

    def test_model_dbc_bytes_change_invalidates_fingerprint_in_isolated_copy(self):
        model_root = self.root / "isolated-model"
        project_root = Path(__file__).resolve().parents[1]
        # The required model dependencies come from the public contract; changing
        # only this temporary DBC must be enough to invalidate the source cache.
        for relative in monitor_store_module.MODEL_FILES:
            target = model_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(project_root / relative, target)
        trace = self.parsed("model-change", [asc_row(0, 0x100, SPEED_10)])
        with patch.object(monitor_store_module, "ROOT", model_root):
            with MonitorStore(self.db) as store:
                first = store.ingest(trace)
                self.assertEqual(store.ingest(trace)["status"], "skipped")
                dbc = model_root / "data/body_control.dbc"
                dbc.write_bytes(dbc.read_bytes() + b'\nCM_ "acceptance: isolated byte change";\n')
                changed = store.ingest(trace)
                self.assertEqual(changed["status"], "loaded")
                self.assertNotEqual(changed["fingerprint"], first["fingerprint"])
                self.assertEqual(store.con.execute("SELECT count(*) FROM mon.frames").fetchone()[0], 1)

    def test_queries_retain_raw_line_and_include_explicit_distant_recovery_anchor(self):
        trace = self.parsed("context", [
            asc_row(0, 0x100, SPEED_10), asc_row(0, 0x101, DOORS_CLOSED),
            asc_row(400_000, 0x100, "00"), asc_row(1_000_000, 0x777, "AB"),
            asc_row(2_000_000, 0x100, SPEED_20), asc_row(2_000_000, 0x101, DOORS_CLOSED),
        ], extra_lines=["2.100000 1 100 Rx d 3 00"])
        with MonitorStore(self.db) as store:
            summary = store.ingest(trace)
            self.assertEqual(summary["rejected_line_count"], 1)
        with MonitorQueries(self.db) as query:
            self.assertEqual([t["trace_id"] for t in query.traces()], ["context"])
            self.assertEqual([f["frame_no"] for f in query.frames("context", 0, 0)], [1, 2])
            events = query.events("context", rule="MESSAGE_TIMEOUT")
            vehicle, = [event for event in events if event["can_id"] == 0x100]
            self.assertEqual((vehicle["frame_no"], vehicle["recovery_frame_no"]), (1, 5))
            context = query.context("context", vehicle["event_id"], before_us=100_000, after_us=100_000)
            self.assertEqual([f["frame_no"] for f in context], [1, 3, 5])
            self.assertEqual([f["physical_line"] for f in context], [4, 6, 8])
            self.assertEqual([f["raw_line"] for f in context],
                             [trace["frames"][i]["raw_line"] for i in [0, 2, 4]])
            self.assertEqual(query.events("context", rule="MESSAGE_TIMEOUT", start_us=300_000, end_us=300_000), [])
            self.assertEqual(len(query.events("context", rule="MESSAGE_TIMEOUT", start_us=2_000_000, end_us=2_000_000)), 2)
            rejected, = query.rejected_lines("context")
            self.assertEqual((rejected["line_number"], rejected["raw_line"]),
                             (10, "2.100000 1 100 Rx d 3 00"))
            self.assertEqual(sum(row["frame_count"] for row in query.minute_stats("context")), 6)
            with self.assertRaises(Exception):
                query.con.execute("DELETE FROM mon.frames")

    def test_report_refresh_clears_old_csv_rows_and_uses_actual_current_provenance(self):
        output = self.root / "shared-output"
        first_trace = self.parsed("MON-REPORT", [
            asc_row(0, 0x100, SPEED_10),
            asc_row(400_000, 0x101, DOORS_CLOSED),
        ], extra_lines=["0.500000 1 100 Rx d 3 00"])
        with MonitorStore(self.db) as store:
            store.ingest(first_trace)
        first_report = write_report(self.db, output)
        self.assertGreater(first_report["totals"]["events"], 0)
        self.assertEqual(first_report["totals"]["rejected_lines"], 1)
        for name in ("events", "rejected_lines"):
            with (output / f"{name}.csv").open(encoding="utf-8-sig", newline="") as stream:
                self.assertGreater(len(list(csv.DictReader(stream))), 0)

        # A different, small user-supplied database replaces the same report
        # directory. Its empty exports must not retain the previous demo rows.
        custom_path = self.root / "custom.asc"
        custom_path.write_text(HEADER + asc_row(0, 0x100, SPEED_10) + "\n", encoding="utf-8")
        custom_trace = read_asc(custom_path, trace_id="USER_CUSTOM")
        clean_db = self.root / "custom.duckdb"
        with MonitorStore(clean_db) as store:
            store.ingest(custom_trace)
        refreshed = write_report(clean_db, output)
        self.assertEqual((refreshed["totals"]["traces"], refreshed["totals"]["frames"],
                          refreshed["totals"]["events"], refreshed["totals"]["rejected_lines"]),
                         (1, 1, 0, 0))
        self.assertEqual(refreshed["traces"][0]["provenance"], "user-provided-unverified")
        for name in ("events", "rejected_lines"):
            with (output / f"{name}.csv").open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(list(csv.DictReader(stream)), [])
        html = (output / "report.html").read_text(encoding="utf-8")
        self.assertIn("USER_CUSTOM", html)
        self.assertIn("user-provided-unverified", html)
        self.assertNotIn("16 份仿真日志", html)
        self.assertNotIn("一份新编写的监控边界样例", html)


if __name__ == "__main__":
    unittest.main()
