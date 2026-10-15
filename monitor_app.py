"""Read-only local explorer for the optional offline CAN monitor.

Start with: python -m streamlit run monitor_app.py
The CLI creates the database; opening this app never imports or changes data.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from can_monitor.queries import MonitorQueries


ROOT = Path(__file__).resolve().parent
RULE_LABELS = {
    "SIGNAL_INVALID": "信号解码无效",
    "SPEED_JUMP": "车速突变",
    "MESSAGE_TIMEOUT": "报文超时",
}
PROVENANCE_LABELS = {
    "synthetic": "教学仿真",
    "user-provided-unverified": "用户提供，真实性未验证",
}
FRAME_COLUMNS = [
    "关联角色", "frame_no", "physical_line", "日志秒", "timestamp_us", "can_id",
    "channel", "direction", "dlc", "data_hex", "decode_status",
    "speed_kmh", "ignition", "door_mask", "warning", "data_fault",
    "reason_code", "decode_error", "raw_line",
]


def _seconds(value: int) -> float:
    return int(value) / 1_000_000


def _can_id(value: object) -> str:
    return "" if value is None else f"0x{int(value):03X}"


def _frame_column_config() -> dict:
    return {
        "日志秒": st.column_config.NumberColumn(format="%.6f"),
        "timestamp_us": st.column_config.NumberColumn(
            format="%d", help="源 ASC 时间转换后的整数微秒；不经过毫秒取整。",
        ),
    }


def _trace_config(trace: dict) -> dict:
    config = trace.get("config_json", "{}")
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            return {}
    return config if isinstance(config, dict) else {}


def _readable_decimal(value: object) -> str:
    try:
        number = Decimal(str(value))
        return format(number, "f") if number.is_finite() else str(value)
    except InvalidOperation:
        return str(value)


def _frame_table(rows: list[dict], event: dict | None = None) -> pd.DataFrame:
    """Keep each source frame, including duplicates, and label explicit anchors."""
    rendered = []
    for frame in rows:
        row = dict(frame)
        roles = []
        if event is not None:
            number = row.get("frame_no")
            if number == event.get("frame_no"):
                roles.append("最后有效锚点" if event["rule"] == "MESSAGE_TIMEOUT" else "触发帧")
            if number == event.get("previous_frame_no") and "最后有效锚点" not in roles:
                roles.append("前一有效帧")
            if number == event.get("recovery_frame_no"):
                roles.append("恢复帧")
        if event is not None:
            row["关联角色"] = " / ".join(roles) if roles else "时间邻域"
        row["日志秒"] = _seconds(row["timestamp_us"])
        row["can_id"] = _can_id(row["can_id"])
        rendered.append(row)
    if not rendered:
        return pd.DataFrame(columns=FRAME_COLUMNS)
    table = pd.DataFrame(rendered)
    return table[[column for column in FRAME_COLUMNS if column in table.columns]]


def _event_table(events: list[dict]) -> pd.DataFrame:
    rows = []
    for event in events:
        rows.append({
            "event_id": event["event_id"],
            "规则": RULE_LABELS.get(event["rule"], event["rule"]),
            "规则代码": event["rule"],
            "can_id": _can_id(event["can_id"]),
            "通道": event["channel"],
            "开始秒": _seconds(event["start_us"]),
            "结束秒": _seconds(event["end_us"]),
            "持续毫秒": event["duration_us"] / 1_000,
            "结束时未恢复": bool(event["open_at_end"]),
            "触发或锚点帧": event.get("frame_no"),
            "恢复帧": event.get("recovery_frame_no"),
            "说明": event["detail"],
        })
    return pd.DataFrame(rows)


def _event_label(event: dict) -> str:
    recovery = " · 结束时未恢复" if event["open_at_end"] else ""
    return (
        f'{_seconds(event["start_us"]):.6f} s · '
        f'{RULE_LABELS.get(event["rule"], event["rule"])} · '
        f'{_can_id(event["can_id"])} / 通道 {event["channel"]} · '
        f'帧 {event.get("frame_no") if event.get("frame_no") is not None else "无锚点"}{recovery}'
    )


def _database_hint(db_path: Path) -> None:
    st.info("还没有可读取的监控数据库。先在项目目录运行 CLI，生成离线分析结果。")
    st.code(
        'python -m can_monitor demo\n'
        'python -m streamlit run monitor_app.py',
        language="powershell",
    )
    st.caption(f"当前数据库路径：{db_path}")
    st.caption("也可以通过 CAN_MONITOR_DB 环境变量指定 CLI 已生成的数据库。")


def _render() -> None:
    db_path = Path(os.environ.get("CAN_MONITOR_DB", str(ROOT / "artifacts" / "log_monitor.duckdb")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    st.title("车辆日志分析与异常监控")
    st.caption("离线学习项目 · ASC 离线日志 · Python / DuckDB / SQL")
    st.info(
        "监控事件来自教学规则；控制器 warning 是报文中的另一项输出。"
        "本项目未验证实车、物理 CAN 总线或 CANoe/CAPL，也不构成车辆故障诊断。"
    )
    if not db_path.is_file():
        _database_hint(db_path)
        return

    # A short-lived read-only connection per Streamlit rerun, never cached.
    with MonitorQueries(db_path) as queries:
        traces = queries.traces()
        if not traces:
            st.info("数据库已存在，但尚无日志。请用 CLI 导入后刷新。")
            _database_hint(db_path)
            return

        st.sidebar.header("查看范围")
        by_trace = {trace["trace_id"]: trace for trace in traces}
        trace_id = st.sidebar.selectbox(
            "场景 / 日志",
            list(by_trace),
            format_func=lambda item: f'{item} · {by_trace[item]["frame_count"]} 帧',
        )
        trace = by_trace[trace_id]
        config = _trace_config(trace)
        rule = st.sidebar.selectbox(
            "监控规则",
            [None, *RULE_LABELS],
            format_func=lambda item: "全部规则" if item is None else RULE_LABELS[item],
        )
        start_us, end_us = int(trace["start_us"]), int(trace["end_us"])
        start_seconds, end_seconds = _seconds(start_us), _seconds(end_us)
        if start_us < end_us:
            lower, upper = st.sidebar.slider(
                "时间窗（日志秒）",
                min_value=start_seconds,
                max_value=end_seconds,
                value=(start_seconds, end_seconds),
                step=0.000001,
                format="%.6f s",
                key=f"time_window_{trace_id}",
            )
            selected_start = max(start_us, round(lower * 1_000_000))
            selected_end = min(end_us, round(upper * 1_000_000))
        else:
            selected_start, selected_end = start_us, end_us
            st.sidebar.caption(f"日志只有一个时间点：{start_seconds:.6f} s")
        st.sidebar.caption("时间窗包含两端。事件按区间交集筛选，持续时间仍显示事件完整区间。")
        st.sidebar.caption("界面只读；刷新不会重新导入数据。")
        if st.sidebar.button("刷新数据库"):
            st.rerun()

        frames = queries.frames(trace_id, start_us=selected_start, end_us=selected_end)
        events = queries.events(trace_id, rule=rule, start_us=selected_start, end_us=selected_end)
        minute_rows = queries.minute_stats(trace_id)
        rejected_rows = queries.rejected_lines(trace_id)

        st.subheader(trace_id)
        provenance = PROVENANCE_LABELS.get(trace["provenance"], "来源标记未识别")
        st.caption(
            f'源文件：{trace["source_name"]} ｜ 来源：{provenance} ｜ '
            f'完整日志范围：{start_seconds:.6f}–{end_seconds:.6f} s'
        )
        channels = ", ".join(str(channel) for channel in config.get("expected_channels", [])) or "未记录"
        timeout_us = config.get("timeout_us")
        timeout_label = (
            f"{timeout_us / 1_000:.3f} ms（{timeout_us} μs）"
            if isinstance(timeout_us, int) else "未记录"
        )
        st.caption(
            f'当前规则配置：期望 ASC 通道 {channels}；超时阈值 {timeout_label}；'
            f'车速突变阈值 {_readable_decimal(config.get("max_acceleration_kmh_s", "未记录"))} km/h/s。'
            "通道编号使用 ASC 文件中的值；有效报文间隔严格大于超时阈值后触发。"
        )
        first_row = st.columns(2)
        first_row[0].metric("窗口内原始帧", f"{len(frames):,}")
        first_row[1].metric("相交监控事件", f"{len(events):,}")
        second_row = st.columns(2)
        second_row[0].metric("隔离行（整段日志）", f"{len(rejected_rows):,}")
        second_row[1].metric("当前观察窗", f"{_seconds(selected_end - selected_start):.6f} s")

        st.subheader("有效车速采样")
        speed_rows = [
            {"日志秒": _seconds(row["timestamp_us"]), "车速 km/h": row["speed_kmh"], "通道": str(row["channel"])}
            for row in frames
            if row.get("decode_status") == "valid" and row.get("speed_kmh") is not None
        ]
        if speed_rows:
            st.scatter_chart(pd.DataFrame(speed_rows), x="日志秒", y="车速 km/h", color="通道")
        else:
            st.info("当前时间窗没有可解码的车速样本。")
        st.caption("每个点对应一条有效车速报文；不插值、不跨缺报区间连线。相同点可能重叠，原始帧表保留重复记录。")

        events_tab, frames_tab, minutes_tab, quality_tab = st.tabs([
            "异常事件与原始报文", "窗口内全部帧", "分钟统计（整段日志）", "隔离与来源",
        ])
        with events_tab:
            if not events:
                st.success("当前筛选范围没有监控规则事件。")
            else:
                st.dataframe(
                    _event_table(events), width="stretch", hide_index=True,
                    column_order=[
                        "开始秒", "结束秒", "规则", "can_id", "持续毫秒", "通道",
                        "结束时未恢复", "触发或锚点帧", "恢复帧", "说明", "event_id", "规则代码",
                    ],
                    column_config={
                        "开始秒": st.column_config.NumberColumn(format="%.6f"),
                        "结束秒": st.column_config.NumberColumn(format="%.6f"),
                        "持续毫秒": st.column_config.NumberColumn(format="%.3f"),
                    },
                )
                by_event = {event["event_id"]: event for event in events}
                event_id = st.selectbox(
                    "选择事件，追踪对应原始行",
                    list(by_event),
                    format_func=lambda item: _event_label(by_event[item]),
                    key=f"event_{trace_id}_{rule}",
                )
                event = by_event[event_id]
                st.caption(f"事件 ID：{event_id}")
                st.write(event["detail"])
                if event["open_at_end"]:
                    st.warning("日志结束前未观察到有效恢复。结束时间截在日志末尾，不代表之后仍持续异常。")
                context = queries.context(trace_id, event_id)
                st.caption(
                    "下表包含事件起点前后各 0.2 秒，以及明确关联的触发帧、最后有效锚点和恢复帧。"
                    "恢复帧可能超出上方时间窗；physical_line 是源 ASC 文件的物理行号。"
                )
                if context:
                    st.dataframe(
                        _frame_table(context, event), width="stretch", hide_index=True,
                        column_config=_frame_column_config(),
                    )
                else:
                    st.info("此事件没有可关联的源帧。初始缺报事件可能尚无最后有效锚点。")
                if event["rule"] == "MESSAGE_TIMEOUT":
                    st.caption("缺报发生的时刻没有对应报文；最后有效锚点用于追溯，恢复只由匹配 ID 与通道的有效报文触发。")

        with frames_tab:
            st.caption("warning / data_fault / reason_code 是控制器报文输出；它们与上方监控规则事件分别记录。")
            st.dataframe(
                _frame_table(frames), width="stretch", hide_index=True,
                column_config=_frame_column_config(),
            )
            if frames:
                st.download_button(
                    "下载当前窗口原始帧 CSV",
                    data=pd.DataFrame(frames).to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{trace_id}_{selected_start}_{selected_end}_frames.csv",
                    mime="text/csv",
                )

        with minutes_tab:
            st.caption("以下统计使用整段所选日志，不受上方规则或时间窗筛选影响。分钟编号由日志秒 / 60 向下取整。")
            if minute_rows:
                table = pd.DataFrame(minute_rows)
                table["超时累计信号秒"] = table["timeout_duration_us"] / 1_000_000
                st.bar_chart(table, x="minute_index", y="frame_count")
                st.caption("上图为每分钟原始帧数；表中的 event_start_count 单独记录监控事件起点数。")
                st.bar_chart(table, x="minute_index", y="超时累计信号秒")
                st.caption("各 ID / 通道超时区间在每分钟内的重叠时长相加，可能大于 60 秒；不是唯一墙钟停机时长。")
                st.dataframe(table, width="stretch", hide_index=True)
            else:
                st.info("此日志没有分钟统计。")

        with quality_tab:
            st.subheader("未进入原始帧表的候选行")
            if rejected_rows:
                st.dataframe(pd.DataFrame(rejected_rows), width="stretch", hide_index=True)
            else:
                st.success("此日志没有被解析器隔离的候选行。")
            st.caption("正常 ASC 头部和注释不属于报文，不计入隔离；不支持或格式错误的候选记录按物理行保留。")
            st.subheader("来源与规则参数")
            st.code(str(trace["source_sha256"]), language="text")
            st.caption("上方为原始文件字节的 SHA-256。来源标记由导入流程提供，不等同于实车真实性验证。")
            st.json(config)
            st.caption(f"数据库：{db_path}")


def main() -> None:
    st.set_page_config(page_title="车辆离线日志分析", page_icon="🚘", layout="wide")
    try:
        _render()
    except Exception as error:
        st.error(f"读取或显示日志分析结果失败：{type(error).__name__}: {error}")
        st.caption("关闭其他正在写入该数据库的进程，再通过 CLI 重新构建并刷新。界面不会自动修改数据库。")


if __name__ == "__main__":
    main()
