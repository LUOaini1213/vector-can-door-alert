"""Run `python -m door_alert demo` from the project directory."""

import argparse
from pathlib import Path
import re
import sys
from .scenarios import load_scenarios, run_scenario
from .reporting import write_reports

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    parser = argparse.ArgumentParser(description="Educational CAN door-alert simulation and assertion report")
    sub = parser.add_subparsers(dest="command",required=True)
    for name in ["demo","run"]:
        item=sub.add_parser(name)
        item.add_argument("--scenarios",type=Path,default=ROOT/"data/scenarios.json")
        item.add_argument("--output",type=Path,default=ROOT/"reports/demo")
    args=parser.parse_args(argv)
    try:
        scenarios=load_scenarios(args.scenarios)
        # IDs become output filenames; reject traversal or invalid Windows filenames.
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",s["id"]) for s in scenarios):
            raise ValueError("scenario IDs must contain safe ASCII letters, digits, underscores or hyphens")
        results=[run_scenario(s) for s in scenarios]
        report=write_reports(results,args.output,ROOT,scenario_path=args.scenarios)
    except (ValueError,OSError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        return 2
    for result in results:
        print(f"{'PASS' if result['passed'] else 'FAIL'} {result['id']} ({len(result['assertions'])} assertions)")
    summary=report["summary"]
    print(f"Scenarios: {summary['passed_scenarios']}/{summary['scenario_count']}; "
          f"assertions: {summary['passed_assertions']}/{summary['assertion_count']}")
    print(f"HTML report: {(args.output/'report.html').resolve()}")
    print("Execution: Python offline simulation. CANoe/CAPL compilation was not performed.")
    return 0 if all(r["passed"] for r in results) else 1
