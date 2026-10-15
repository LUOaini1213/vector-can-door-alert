"""Build and inspect a local monitor database; UI never writes to this database."""

import argparse
import json
from pathlib import Path
import sys

import duckdb
from .engine import RuleConfig
from .parser import read_asc
from .store import MonitorStore

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline classic CAN log analysis")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "ingest", "report"):
        command = commands.add_parser(name)
        command.add_argument("--db", type=Path, default=ROOT / "artifacts/log_monitor.duckdb")
        command.add_argument("--output", type=Path, default=ROOT / "reports/log_monitor/latest")
        if name != "report":
            command.add_argument("--timeout-ms", type=float, default=300)
            command.add_argument("--max-acceleration", type=float, default=100)
        if name == "ingest":
            command.add_argument("path", type=Path)
            command.add_argument("--trace-id")
    args = parser.parse_args(argv)
    try:
        results = []
        if args.command != "report":
            config = RuleConfig(timeout_ms=args.timeout_ms, max_acceleration_kmh_s=args.max_acceleration)
            if args.command == "demo":
                paths = sorted((ROOT / "reports/demo/traces").glob("SC*.asc"))
                paths += sorted((ROOT / "data/monitor").glob("MON*.asc"))
                if len(paths) < 17:
                    raise ValueError("demo needs the existing 16 ASC traces and monitor fixture; run python -m door_alert demo first")
                traces = [read_asc(p, provenance="synthetic") for p in paths]
            else:
                traces = [read_asc(args.path, trace_id=args.trace_id)]
            args.db.parent.mkdir(parents=True, exist_ok=True)
            with MonitorStore(args.db) as store:
                results = [store.ingest(trace, config=config) for trace in traces]
        if not args.db.is_file():
            raise ValueError("database not found; run python -m can_monitor demo first")
        from .reporting import write_report
        report = write_report(args.db, args.output)
    except (ValueError, OSError, UnicodeError, duckdb.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"imports": results, "totals": report["totals"],
                      "report": str((args.output / "report.html").resolve())}, ensure_ascii=False, indent=2))
    return 0
