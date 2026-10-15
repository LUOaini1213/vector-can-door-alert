"""Run independent fixtures, rebuild demo, cross-check ASC and publish evidence."""

from datetime import datetime, timezone
import importlib.metadata
import io
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from can_monitor.parser import read_asc
from can_monitor.queries import MonitorQueries
from can_monitor.reporting import write_report
from can_monitor.store import MonitorStore


def main():
    import can
    output = ROOT / "reports/log_monitor/2026-10-15"
    output.mkdir(parents=True, exist_ok=True)
    tests = subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "tests_monitor", "-v"],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    (output / "unit_tests.txt").write_text(tests.stdout + tests.stderr, encoding="utf-8")
    tests.check_returncode()
    count = int(re.search(r"Ran (\d+) tests?", tests.stderr).group(1))
    db = ROOT / "artifacts/monitor_verification.duckdb"
    build = subprocess.run([sys.executable, "-X", "utf8", "-m", "can_monitor", "demo", "--db", str(db), "--output", str(output)],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if build.returncode:
        print(build.stderr, file=sys.stderr); build.check_returncode()
    paths = sorted((ROOT / "reports/demo/traces").glob("SC*.asc")) + sorted((ROOT / "data/monitor").glob("MON*.asc"))
    traces = [read_asc(path, provenance="synthetic") for path in paths]
    compared = 0
    with MonitorQueries(db) as queries:
        published_before = queries.traces()
        for path, trace in zip(paths, traces):
            source_lines = path.read_text(encoding="utf-8-sig").splitlines()
            stored = queries.frames(trace["trace_id"])
            assert len(stored) == len(trace["frames"])
            for frame in stored:
                assert frame["raw_line"] == source_lines[frame["physical_line"] - 1]
            # Feed only structurally accepted records to the independent reader;
            # rejected lines are separately checked by hand-authored unit tests.
            excluded = {row["line_number"] for row in trace["rejected_lines"]}
            cleaned = "\n".join(line for number, line in enumerate(source_lines, 1) if number not in excluded) + "\n"
            with can.ASCReader(io.StringIO(cleaned), relative_timestamp=True) as reader:
                reference = list(reader)
            assert len(reference) == len(stored)
            for actual, expected in zip(reference, stored):
                assert round(actual.timestamp * 1_000_000) == expected["timestamp_us"]
                assert actual.arbitration_id == expected["can_id"]
                assert actual.channel + 1 == expected["channel"]
                assert actual.is_rx == (expected["direction"] == "Rx")
                assert actual.dlc == expected["dlc"]
                assert bytes(actual.data).hex(" ").upper() == expected["data_hex"]
                assert not actual.is_extended_id and not actual.is_fd
                compared += 1
    with MonitorStore(db) as store:
        repeated = [store.ingest(trace) for trace in traces]
        assert all(row["status"] == "skipped" for row in repeated)
    with MonitorQueries(db) as queries:
        assert queries.traces() == published_before
    ui = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/check_monitor_ui.py"), "--db", str(db)],
                        cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if ui.returncode:
        print(ui.stdout); print(ui.stderr, file=sys.stderr); ui.check_returncode()
    ui_evidence = json.loads(ui.stdout)
    assert ui_evidence["status"] == "passed"
    report = write_report(db, output)
    assert report["totals"]["traces"] == 17 and report["totals"]["frames"] == 1260
    evidence = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "database_scope": "Dedicated artifacts/monitor_verification.duckdb; user working database is not modified.",
        "monitor_unit_tests": count, "monitor_unit_tests_passed": True,
        "unit_fixture_scope": "Independently hand-authored synthetic ASC with hand-computed boundaries; not vehicle data.",
        "demo_totals": report["totals"], "all_trace_reconciliation_passed": True,
        "independent_asc_files": len(paths), "independent_asc_records_compared": compared,
        "independent_asc_scope": "python-can reference reader on accepted records; structurally rejected lines excluded from reference only.",
        "source_physical_lines_verified": compared, "identical_reimports_skipped": len(repeated),
        "published_traces_unchanged_on_skip": True, "ui_apptest": ui_evidence,
        "versions": {name: importlib.metadata.version(name) for name in ("duckdb", "streamlit", "python-can")},
        "source_code_sha256": report["source_code_sha256"],
        "hardware_and_canoe_validation": "not performed",
    }
    (output / "acceptance.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"monitor_unit_tests": count, "demo_totals": report["totals"],
                      "independent_asc_records": compared, "ui_check_count": ui_evidence["check_count"],
                      "all_trace_reconciliation": "passed"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
