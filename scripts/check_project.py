"""Standard-library checks: unit tests, real CLI report, and four killed mutants."""

import json
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from door_alert import controller
from door_alert.scenarios import load_scenarios, run_scenario


def main():
    units=subprocess.run([sys.executable,"-X","utf8","-m","unittest","discover","-s","tests","-v"],cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
    print(units.stdout,end="");print(units.stderr,end="",file=sys.stderr)
    units.check_returncode()
    match=re.search(r"Ran (\d+) tests? in",units.stderr)
    if not match:raise AssertionError("unit-test count was not recorded")
    subprocess.run([sys.executable,"-X","utf8","-m","door_alert","demo","--output","reports/demo"],cwd=ROOT,check=True)
    scenarios=load_scenarios(ROOT/"data/scenarios.json")
    mutants=[("DEBOUNCE_MS",190),("ON_SPEED_RAW",501),("OFF_SPEED_RAW",299),("FRESHNESS_MS",299)]
    evidence=[]
    for attribute,value in mutants:
        with patch.object(controller,attribute,value):
            results=[run_scenario(s) for s in scenarios]
        failed=[r["id"] for r in results if not r["passed"]]
        if not failed:raise AssertionError(f"surviving mutant {attribute}={value}")
        evidence.append({"mutation":f"{attribute}={value}","detected":True,"failed_scenarios":failed})
    # A wrong answer must propagate through report generation to the process exit code.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="door-alert-exit-") as temp:
        case=json.loads(json.dumps(scenarios[0]))
        case["assertions"][0]["warning"]=not case["assertions"][0]["warning"]
        path=Path(temp)/"wrong.json";path.write_text(json.dumps([case]),encoding="utf-8")
        proc=subprocess.run([sys.executable,"-m","door_alert","run","--scenarios",str(path),"--output",str(Path(temp)/"result")],cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
        if proc.returncode!=1:raise AssertionError(f"failed assertion exit code must be 1, got {proc.returncode}")
    report={"mutants_detected":len(evidence),"mutants_checked":len(mutants),"mutants":evidence,
            "cli_failed_assertion_exit_code":1,"scope":"Four selected boundary mutations; not exhaustive mutation coverage"}
    (ROOT/"reports/demo/mutation_check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    from door_alert.reporting import source_hashes
    summary={"unit_tests_run":int(match.group(1)),"unit_tests_passed":True,
             "boundary_mutations_detected":len(evidence),"cli_failed_assertion_exit_code":1,
             "source_sha256":source_hashes(ROOT)}
    (ROOT/"reports/demo/check_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Detected {len(evidence)}/{len(mutants)} selected boundary mutants; CLI failure exits 1.")
    return 0


if __name__=="__main__":raise SystemExit(main())
