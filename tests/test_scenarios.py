"""Fixture execution and negative schema tests, independent of implementation internals."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from door_alert.scenarios import load_scenarios, run_scenario


PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "data" / "scenarios.json"


class ScenarioFixture(unittest.TestCase):
    def test_all_16_manually_calculated_scenarios(self):
        scenarios = load_scenarios(FIXTURE)
        self.assertEqual(len(scenarios), 16)
        self.assertEqual(len({scenario["id"] for scenario in scenarios}), 16)
        for scenario in scenarios:
            with self.subTest(scenario=scenario["id"]):
                self.assertGreaterEqual(len(scenario["assertions"]), 5)
                result = run_scenario(scenario)
                self.assertEqual(result["id"], scenario["id"])
                self.assertEqual(len(result["assertions"]), len(scenario["assertions"]))
                failures = [entry for entry in result["assertions"] if not entry["passed"]]
                self.assertTrue(result["passed"], json.dumps(failures, ensure_ascii=False))
                self.assertFalse(failures)
                trace = result["trace"]
                self.assertEqual([entry["timestamp_ms"] for entry in trace],
                                 list(range(0, scenario["duration_ms"] + 1, 10)))

    def test_run_is_repeatable_and_does_not_mutate_fixture(self):
        scenario = load_scenarios(FIXTURE)[14]  # Same-time ordering regression.
        untouched = copy.deepcopy(scenario)
        first = run_scenario(scenario)
        second = run_scenario(scenario)
        self.assertEqual(first, second)
        self.assertEqual(scenario, untouched)

    def test_periodic_events_include_until_boundary(self):
        scenario = dict(
            id="PERIOD", title="inclusive until", requirements=["REQ-03"], duration_ms=200,
            events=[dict(at_ms=0, kind="vehicle", speed_kmh=5, ignition=True, period_ms=100, until_ms=200),
                    dict(at_ms=0, kind="doors", door_mask=1, period_ms=100, until_ms=200)],
            assertions=[dict(at_ms=200, warning=True, data_fault=False, reason=6)],
        )
        result = run_scenario(scenario)
        self.assertTrue(result["passed"])
        actual = [(frame["timestamp_ms"], frame["arbitration_id"]) for frame in result["input_frames"]]
        self.assertEqual(actual, [(0, 0x100), (0, 0x101), (100, 0x100),
                                  (100, 0x101), (200, 0x100), (200, 0x101)])

    def test_period_without_until_uses_scenario_duration(self):
        scenario = dict(
            id="DEFAULT_END", title="period uses duration", requirements=["REQ-03"], duration_ms=20,
            events=[dict(at_ms=0, kind="doors", door_mask=1, period_ms=10)],
            assertions=[dict(at_ms=20, warning=False, data_fault=True, reason=1)],
        )
        result = run_scenario(scenario)
        self.assertTrue(result["passed"])
        self.assertEqual([frame["timestamp_ms"] for frame in result["input_frames"]], [0, 10, 20])


class ScenarioSchema(unittest.TestCase):
    def setUp(self):
        self.good = dict(
            id="VALID", title="Minimal valid scenario", requirements=["REQ-04"], duration_ms=20,
            events=[], assertions=[dict(at_ms=0, warning=False, data_fault=True, reason=1)],
        )

    def load(self, value):
        with tempfile.TemporaryDirectory(prefix="door-alert-schema-") as directory:
            path = Path(directory) / "fixture.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return load_scenarios(path)

    def assert_bad(self, scenario):
        with self.assertRaises(ValueError):
            self.load([scenario])

    def test_valid_empty_inputs(self):
        self.assertEqual(self.load([self.good]), [self.good])

    def test_root_must_be_list(self):
        for invalid in ({}, None, "scenario", 1):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                self.load(invalid)

    def test_required_keys(self):
        for key in ("id", "title", "requirements", "duration_ms", "events", "assertions"):
            with self.subTest(key=key):
                scenario = copy.deepcopy(self.good)
                del scenario[key]
                self.assert_bad(scenario)

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            self.load([self.good, copy.deepcopy(self.good)])

    def test_windows_reserved_device_names_rejected(self):
        # Extensions such as .asc/.csv do not make Windows device names safe.
        names = ["CON", "PRN", "AUX", "NUL"]
        names += [f"COM{number}" for number in range(1, 10)]
        names += [f"LPT{number}" for number in range(1, 10)]
        for name in names:
            for variant in (name, name.lower(), name[0] + name[1:].lower()):
                with self.subTest(scenario_id=variant):
                    scenario = copy.deepcopy(self.good)
                    scenario["id"] = variant
                    self.assert_bad(scenario)

    def test_case_insensitive_ids_cannot_overwrite_trace_files(self):
        for first_id, second_id in [("SC01", "sc01"), ("Case_A", "case_a"), ("demo", "DEMO")]:
            with self.subTest(first_id=first_id, second_id=second_id):
                first = dict(copy.deepcopy(self.good), id=first_id)
                second = dict(copy.deepcopy(self.good), id=second_id)
                with self.assertRaises(ValueError):
                    self.load([first, second])

    def test_bad_duration(self):
        for duration in (-10, 1, 10.0, "20", True):
            with self.subTest(duration=duration):
                scenario = copy.deepcopy(self.good)
                scenario["duration_ms"] = duration
                self.assert_bad(scenario)

    def test_invalid_event_time(self):
        for timestamp in (-10, 1, 30, "0", True):
            with self.subTest(timestamp=timestamp):
                scenario = copy.deepcopy(self.good)
                scenario["events"] = [dict(at_ms=timestamp, kind="doors", door_mask=1)]
                self.assert_bad(scenario)

    def test_invalid_assertion_time(self):
        for timestamp in (-10, 1, 30, "0", True):
            with self.subTest(timestamp=timestamp):
                scenario = copy.deepcopy(self.good)
                scenario["assertions"][0]["at_ms"] = timestamp
                self.assert_bad(scenario)

    def test_boolean_expected_states_required(self):
        for key in ("warning", "data_fault"):
            for invalid in (0, 1, "false", None):
                with self.subTest(key=key, invalid=invalid):
                    scenario = copy.deepcopy(self.good)
                    scenario["assertions"][0][key] = invalid
                    self.assert_bad(scenario)

    def test_invalid_event_kinds_and_payloads(self):
        invalid_events = [
            dict(at_ms=0, kind="unrecognised"),
            dict(at_ms=0, kind="doors", door_mask=16),
            dict(at_ms=0, kind="doors", door_mask=-1),
            dict(at_ms=0, kind="vehicle", speed_kmh=-1, ignition=True),
            dict(at_ms=0, kind="vehicle", speed_kmh=251, ignition=True),
            dict(at_ms=0, kind="vehicle", speed_kmh="5", ignition=True),
            dict(at_ms=0, kind="vehicle", speed_kmh=5, ignition=2),
            dict(at_ms=0, kind="raw", arbitration_id=256, data_hex="not hex"),
            dict(at_ms=0, kind="raw", arbitration_id=-1, data_hex="00"),
            dict(at_ms=0, kind="raw", arbitration_id=0x800, data_hex="00"),
        ]
        for event in invalid_events:
            with self.subTest(event=event):
                scenario = copy.deepcopy(self.good)
                scenario["events"] = [event]
                self.assert_bad(scenario)

    def test_period_must_advance_in_10_ms_steps_within_duration(self):
        invalid_periods = [
            dict(period_ms=0, until_ms=20), dict(period_ms=-10, until_ms=20),
            dict(period_ms=5, until_ms=20), dict(period_ms=True, until_ms=20),
            dict(until_ms=20),
            dict(period_ms=10, until_ms=-10), dict(period_ms=10, until_ms=30),
            dict(period_ms=10, until_ms=1),
        ]
        for repeated in invalid_periods:
            with self.subTest(repeated=repeated):
                scenario = copy.deepcopy(self.good)
                scenario["events"] = [dict(at_ms=0, kind="doors", door_mask=1, **repeated)]
                self.assert_bad(scenario)


if __name__ == "__main__":
    unittest.main()
