"""Scenario parsing, periodic stimulus expansion, and explicit expected-value checks."""

from dataclasses import asdict
import json
from pathlib import Path
import re
from .controller import Controller, TICK_MS
from .protocol import Frame, encode_doors, encode_vehicle, require_time


def _aligned(value, label, maximum=None):
    require_time(value)
    if value % TICK_MS or maximum is not None and value > maximum:
        raise ValueError(f"{label} must be on a 10-ms tick and within scenario duration")
    return value


def _event_frame(event, at_ms):
    kind = event.get("kind")
    try:
        if kind == "vehicle":
            return encode_vehicle(at_ms, event["speed_kmh"], event["ignition"])
        if kind == "doors":
            return encode_doors(at_ms, event["door_mask"])
        if kind == "raw":
            if not isinstance(event.get("data_hex"), str):
                raise ValueError("raw data_hex must be a string")
            return Frame(at_ms, event["arbitration_id"], bytes.fromhex(event["data_hex"]))
    except KeyError as exc:
        raise ValueError(f"missing event field: {exc.args[0]}") from exc
    raise ValueError(f"unknown event kind: {kind}")


def validate_scenario(scenario):
    if not isinstance(scenario, dict):
        raise ValueError("scenario must be an object")
    for field in ["id", "title", "requirements", "duration_ms", "events", "assertions"]:
        if field not in scenario:
            raise ValueError(f"missing scenario field: {field}")
    if not isinstance(scenario["id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", scenario["id"]):
        raise ValueError("scenario id must be safe ASCII text for a filename")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{prefix}{n}" for prefix in ["COM", "LPT"] for n in range(1, 10)}
    if scenario["id"].upper() in reserved:
        raise ValueError("scenario id is a reserved Windows device name")
    if not isinstance(scenario["title"], str) or not scenario["title"].strip():
        raise ValueError("scenario title must be nonempty text")
    duration = _aligned(scenario["duration_ms"], "duration_ms")
    if duration > 120_000:
        raise ValueError("educational scenarios are limited to 120000 ms")
    reqs = scenario["requirements"]
    if not isinstance(reqs, list) or not reqs or any(
            not isinstance(x, str) or x not in {f"REQ-{n:02d}" for n in range(1, 13)} for x in reqs):
        raise ValueError("requirements must contain known REQ-01..REQ-12 identifiers")
    if not isinstance(scenario["events"], list):
        raise ValueError("events must be a list")
    for event in scenario["events"]:
        if not isinstance(event, dict) or "at_ms" not in event:
            raise ValueError("each event needs at_ms")
        at = _aligned(event["at_ms"], "event at_ms", duration)
        _event_frame(event, at)
        if "period_ms" in event:
            period = _aligned(event["period_ms"], "period_ms")
            if period == 0:
                raise ValueError("period_ms must be positive")
            until = _aligned(event.get("until_ms", duration), "until_ms", duration)
            if until < at:
                raise ValueError("until_ms must not precede at_ms")
        elif "until_ms" in event:
            raise ValueError("until_ms requires period_ms")
    assertions = scenario["assertions"]
    if not isinstance(assertions, list) or not assertions:
        raise ValueError("scenario needs at least one explicit assertion")
    for assertion in assertions:
        if not isinstance(assertion, dict) or "at_ms" not in assertion:
            raise ValueError("each assertion needs at_ms")
        _aligned(assertion["at_ms"], "assertion at_ms", duration)
        for flag in ["warning", "data_fault"]:
            if type(assertion.get(flag)) is not bool:
                raise ValueError(f"assertion {flag} must be boolean")
        if "reason" in assertion and (type(assertion["reason"]) is not int or assertion["reason"] not in range(1, 7)):
            raise ValueError("assertion reason must be 1..6")
    return scenario


def load_scenarios(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load scenarios: {exc}") from exc
    if isinstance(value, dict) and "scenarios" in value:
        value = value["scenarios"]
    if not isinstance(value, list) or not value:
        raise ValueError("scenario file must contain a nonempty list")
    seen = set()
    for scenario in value:
        validate_scenario(scenario)
        normalized_id = scenario["id"].casefold()
        if normalized_id in seen:
            raise ValueError(f"duplicate scenario id: {scenario['id']}")
        seen.add(normalized_id)
    return value


def run_scenario(scenario, controller_factory=Controller):
    validate_scenario(scenario)
    expanded = []
    for index, event in enumerate(scenario["events"]):
        at = event["at_ms"]
        period = event.get("period_ms")
        times = [at] if period is None else range(at, event.get("until_ms", scenario["duration_ms"]) + 1, period)
        for timestamp in times:
            expanded.append((timestamp, index, _event_frame(event, timestamp)))
    expanded.sort(key=lambda row: (row[0], row[1]))
    controller = controller_factory()
    trace = []
    pos = 0
    for timestamp in range(0, scenario["duration_ms"] + 1, TICK_MS):
        while pos < len(expanded) and expanded[pos][0] == timestamp:
            controller.receive(expanded[pos][2])
            pos += 1
        trace.append(asdict(controller.tick(timestamp)))
    by_time = {item["timestamp_ms"]: item for item in trace}
    checks = []
    for expected in scenario["assertions"]:
        actual = {key: by_time[expected["at_ms"]][key]
                  for key in ["warning", "data_fault", "reason"] if key in expected}
        matches = all(actual[key] == expected[key] for key in actual)
        checks.append({"at_ms": expected["at_ms"], "expected": {k:expected[k] for k in actual},
                       "actual": actual, "passed": matches})
    return {"id": scenario["id"], "title": scenario["title"],
            "requirements": scenario["requirements"], "passed": all(x["passed"] for x in checks),
            "assertions": checks, "trace": trace,
            "input_frames": [row[2].to_dict() for row in expanded]}
