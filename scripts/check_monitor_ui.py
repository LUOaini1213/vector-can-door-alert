"""Exercise the optional read-only Streamlit UI against the generated demo DB.

Run with .analysis-venv/Scripts/python.exe scripts/check_monitor_ui.py.
The supplied database is never modified. Provenance display uses an isolated
temporary copy; no traces are imported by this check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import duckdb


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from can_monitor.queries import MonitorQueries  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402


def _healthy(app: AppTest) -> None:
    assert not app.exception, [str(error) for error in app.exception]
    assert not app.error, [error.value for error in app.error]


def _metric(app: AppTest, label: str) -> str:
    return next(item.value for item in app.metric if item.label == label)


def _column_format(table, column: str) -> str:
    """Inspect the actual frontend configuration, not only Python values."""
    return json.loads(table.proto.columns)[column]["type_config"]["format"]


def run_checks(db_path: Path | None = None) -> dict:
    db_path = (db_path or ROOT / "artifacts" / "log_monitor.duckdb").resolve()
    if not db_path.is_file():
        raise FileNotFoundError("First run python -m can_monitor demo")
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    with MonitorQueries(db_path) as queries:
        traces = queries.traces()
        demo = next(row for row in traces if row["trace_id"] == "MON01_boundaries")
        timeouts = [
            event for event in queries.events("MON01_boundaries", rule="MESSAGE_TIMEOUT")
            if event["recovery_frame_no"] is not None
        ]
        selected = max(timeouts, key=lambda event: event["duration_us"])

    previous_env = os.environ.get("CAN_MONITOR_DB")
    checks = []
    try:
        os.environ["CAN_MONITOR_DB"] = str(db_path)
        app = AppTest.from_file(str(ROOT / "monitor_app.py"), default_timeout=30).run()
        _healthy(app)
        app.sidebar.selectbox[0].select("MON01_boundaries").run()
        _healthy(app)
        assert _metric(app, "窗口内原始帧") == f'{demo["frame_count"]:,}'
        assert _metric(app, "相交监控事件") == f'{demo["event_count"]:,}'
        assert _metric(app, "隔离行（整段日志）") == f'{demo["rejected_line_count"]:,}'
        checks.append("full_trace_metrics")

        assert _column_format(app.dataframe[0], "开始秒") == "%.6f"
        assert _column_format(app.dataframe[0], "结束秒") == "%.6f"
        assert _column_format(app.dataframe[0], "持续毫秒") == "%.3f"
        frame_tables = [table for table in app.dataframe if "日志秒" in table.value.columns]
        assert len(frame_tables) == 2
        for table in frame_tables:
            assert _column_format(table, "日志秒") == "%.6f"
            assert _column_format(table, "timestamp_us") == "%d"
        checks.append("microsecond_column_formats_serialized")

        assert 0.900001 in app.dataframe[0].value["开始秒"].values
        all_frames = next(table.value for table in frame_tables if len(table.value) == demo["frame_count"])
        boundary = all_frames.loc[all_frames["timestamp_us"] == 900_001]
        assert not boundary.empty and (boundary["日志秒"] == 0.900001).all()
        checks.append("microsecond_boundary_values_preserved")

        captions = [item.value for item in app.caption]
        assert any("来源：教学仿真" in caption for caption in captions)
        assert any("期望 ASC 通道 1" in caption and "300.000 ms（300000 μs）" in caption
                   for caption in captions)
        checks.append("selected_trace_provenance_and_rule_configuration")

        app.sidebar.selectbox[1].select("MESSAGE_TIMEOUT").run()
        _healthy(app)
        assert set(app.dataframe[0].value["规则代码"]) == {"MESSAGE_TIMEOUT"}
        checks.append("rule_filter")

        selector = next(item for item in app.selectbox if item.label == "选择事件，追踪对应原始行")
        selector.select(selected["event_id"]).run()
        _healthy(app)
        context = app.dataframe[1].value
        for number in (selected["frame_no"], selected["previous_frame_no"], selected["recovery_frame_no"]):
            if number is not None:
                assert number in context["frame_no"].values
        assert context["关联角色"].str.contains("恢复帧").any()
        assert context["关联角色"].str.contains("最后有效锚点").any()
        assert {"raw_line", "physical_line"} <= set(context.columns)
        checks.append("selected_event_source_anchors_and_recovery")

        # The handwritten demo includes a timeout from 1.400001 to 61.100000 s.
        # Its explicit recovery must remain visible beyond the selected window.
        assert selected["start_us"] == 1_400_001 and selected["end_us"] == 61_100_000
        app.sidebar.slider[0].set_range(0.9, 1.5).run()
        _healthy(app)
        context = app.dataframe[1].value
        recovery = context.loc[context["frame_no"] == selected["recovery_frame_no"]]
        assert len(recovery) == 1 and recovery["日志秒"].iloc[0] > 1.5
        checks.append("far_recovery_outside_time_window")

        app.sidebar.slider[0].set_range(1.400001, 1.400001).run()
        _healthy(app)
        assert _metric(app, "窗口内原始帧") == "0"
        assert _metric(app, "相交监控事件") == "2"
        assert _metric(app, "当前观察窗") == "0.000000 s"
        assert set(app.dataframe[0].value["开始秒"]) == {1.400001}
        assert selected["recovery_frame_no"] in app.dataframe[1].value["frame_no"].values
        checks.append("single_microsecond_point_window_with_recovery")

        app.sidebar.selectbox[1].select("SIGNAL_INVALID").run()
        app.sidebar.slider[0].set_range(60.0, 61.3).run()
        _healthy(app)
        assert _metric(app, "相交监控事件") == "0"
        checks.append("empty_event_window")

        for trace in traces:
            app.sidebar.selectbox[0].select(trace["trace_id"]).run()
            _healthy(app)
        checks.append("all_scenarios_render")

        assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
        checks.append("database_bytes_unchanged")

        with tempfile.TemporaryDirectory(prefix="can-monitor-ui-") as directory:
            absent = Path(directory) / "not-created.duckdb"
            os.environ["CAN_MONITOR_DB"] = str(absent)
            missing = AppTest.from_file(str(ROOT / "monitor_app.py"), default_timeout=30).run()
            _healthy(missing)
            assert any("python -m can_monitor demo" in item.value for item in missing.code)
            assert not absent.exists()
        checks.append("missing_database_cli_hint_without_creation")

        with tempfile.TemporaryDirectory(prefix="can-monitor-ui-provenance-") as directory:
            isolated = Path(directory) / "user-provided.duckdb"
            shutil.copyfile(db_path, isolated)
            with duckdb.connect(str(isolated)) as con:
                con.execute("UPDATE mon.traces SET provenance='user-provided-unverified'")
            os.environ["CAN_MONITOR_DB"] = str(isolated)
            unverified = AppTest.from_file(str(ROOT / "monitor_app.py"), default_timeout=30).run()
            _healthy(unverified)
            captions = [item.value for item in unverified.caption]
            assert any("来源：用户提供，真实性未验证" in caption for caption in captions)
            assert not any("仿真" in caption for caption in captions)
        checks.append("unverified_source_label_without_synthetic_claim")

        assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
    finally:
        if previous_env is None:
            os.environ.pop("CAN_MONITOR_DB", None)
        else:
            os.environ["CAN_MONITOR_DB"] = previous_env

    return {
        "status": "passed",
        "checks": checks,
        "check_count": len(checks),
        "scenario_count": len(traces),
        "database_sha256_before_and_after": before,
        "far_recovery_event_id": selected["event_id"],
        "scope": "Streamlit AppTest with synthetic demo data; no browser visual or vehicle validation",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "artifacts" / "log_monitor.duckdb")
    args = parser.parse_args()
    print(json.dumps(run_checks(args.db), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
