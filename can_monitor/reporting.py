"""Static, shareable evidence snapshot of the local monitor database."""

import csv
from datetime import datetime, timezone
import hashlib
from html import escape
import json
from pathlib import Path

from .queries import MonitorQueries
from .integrity import validate_trace

ROOT = Path(__file__).resolve().parents[1]


def _table(rows, columns=None):
    if not rows:
        return "<p>无记录</p>"
    columns = columns or list(rows[0])
    headers = "".join(f"<th>{escape(column)}</th>" for column in columns)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(row.get(column, '')))}</td>"
                                     for column in columns) + "</tr>" for row in rows)
    return f'<div class="tablewrap"><table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>'


def write_report(db_path, output):
    traces, frames, events, minutes, rejected, checks = [], [], [], [], [], []
    contexts = []
    with MonitorQueries(db_path) as queries:
        csv_headers = {name: [row[1] for row in queries.con.execute(f"PRAGMA table_info('mon.{name}')").fetchall()]
                       for name in ("traces", "frames", "events", "minute_stats", "rejected_lines")}
        traces = queries.traces()
        for trace in traces:
            identifier = trace["trace_id"]
            fs, es = queries.frames(identifier), queries.events(identifier)
            ms, rs = queries.minute_stats(identifier), queries.rejected_lines(identifier)
            checks.append(validate_trace(queries.con, identifier))
            frames.extend(fs); events.extend(es); minutes.extend(ms); rejected.extend(rs)
            if identifier.startswith("MON"):
                for event in es:
                    contexts.append({"trace_id": identifier, "event_id": event["event_id"],
                                     "rule": event["rule"], "frames": queries.context(identifier, event["event_id"])})
    rule_counts = {rule: sum(event["rule"] == rule for event in events)
                   for rule in ("MESSAGE_TIMEOUT", "SIGNAL_INVALID", "SPEED_JUMP")}
    totals = {"traces": len(traces), "frames": len(frames), "events": len(events),
              "rejected_lines": len(rejected), "unknown_frames": sum(f["decode_status"] == "unknown" for f in frames),
              "invalid_frames": sum(f["decode_status"] == "invalid" for f in frames), "events_by_rule": rule_counts}
    paths = [ROOT / "monitor_app.py", ROOT / "requirements-monitor.txt", ROOT / "data/body_control.dbc",
             ROOT / "door_alert/protocol.py", ROOT / "sql/monitor_schema.sql"]
    for directory in ("can_monitor", "tests_monitor"):
        paths.extend(sorted((ROOT / directory).glob("*.py")))
    paths.extend(p for p in sorted((ROOT / "scripts").glob("*monitor*.py")))
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "totals": totals,
              "traces": traces, "events": events, "minute_stats": minutes, "rejected_lines": rejected,
              "reconciliation": checks, "example_event_contexts": contexts, "source_code_sha256": hashes,
              "scope": "Offline fixed-protocol classic CAN ASC analysis; simulated data is explicitly labeled. No CANoe or hardware validation.",
              "reconciliation_scope": "Independent SQL checks table counts, references and per-minute metrics; it does not authenticate source bytes or vehicle provenance.",
              "duration_semantics": "Timeout first starts at last valid us + threshold us + 1. Open intervals end at the last observed frame. Per-signal time sums may overlap."}
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    for name, rows in (("traces", traces), ("frames", frames), ("events", events), ("minute_stats", minutes),
                       ("rejected_lines", rejected), ("reconciliation", checks)):
        fields = list(rows[0]) if rows else csv_headers.get(name, ["trace_id"])
        with (output / f"{name}.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    all_ok = bool(checks) and all(all(value for key, value in row.items() if key != "trace_id") for row in checks)
    cards = "".join(f'<div><strong>{value:,}</strong>{label}</div>' for label, value in (
        ("日志场景", totals["traces"]), ("接受报文", totals["frames"]),
        ("规则事件", totals["events"]), ("格式隔离行", totals["rejected_lines"])))
    sections = [("按场景的来源与指纹", _table(traces, ["trace_id", "source_name", "provenance", "frame_count", "event_count", "rejected_line_count", "source_sha256"])),
                ("三类规则事件", _table(events, ["trace_id", "rule", "can_id", "channel", "start_us", "end_us", "duration_us", "open_at_end", "frame_no", "recovery_frame_no", "detail"])),
                ("分钟统计（时间轴为日志相对时间）", _table(minutes)),
                ("格式隔离记录", _table(rejected)), ("数量、时长与血缘对账", _table(checks))]
    body = "".join(f"<section><h2>{escape(title)}</h2>{content}</section>" for title, content in sections)
    provenance_counts = {label: sum(t['provenance'] == label for t in traces)
                         for label in sorted({t['provenance'] for t in traces})}
    source_notice = f"当前数据库有 {len(traces)} 份日志，来源标记统计：" + ", ".join(
        f"{label}: {count}" for label, count in provenance_counts.items())
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CAN 日志分析验证报告</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f0f4f9;color:#17243b;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}}main{{max-width:1280px;margin:auto;padding:30px 22px}}h1{{font-size:30px}}h2{{font-size:20px}}section,.notice{{background:white;border:1px solid #dbe3ee;border-radius:12px;padding:20px;margin:20px 0}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.cards div{{background:white;padding:18px;border-radius:10px}}strong{{display:block;font-size:27px}}.tablewrap{{overflow-x:auto}}table{{border-collapse:collapse;font-size:13px;white-space:nowrap}}th,td{{padding:8px;border:1px solid #dce4ee;text-align:left}}th{{background:#edf3fb}}code{{background:#edf3fb;padding:3px 6px}}@media(max-width:700px){{.cards{{grid-template-columns:repeat(2,1fr)}}main{{padding:18px 12px}}}}</style></head><body><main>
<h1>车辆日志分析与异常监控</h1><p>离线 ASC → 固定协议解码 → DuckDB → 规则事件 → 原始报文追踪</p><div class="cards">{cards}</div>
<div class="notice"><b>分层核对：{'通过' if all_ok else '失败或无数据'}</b><p>{escape(source_notice)}。来源标签由导入流程提供。规则事件不等于真实车辆故障，也不等于原控制器的车门 warning 输出。CAPL/CANoe 和硬件状态不因这一版而改变。</p><p>独立 SQL 逐分钟核对帧数、无效/未知数、事件起点、超时时长及车速均值/最大值；这些检查证明表间一致性，不能验证原始文件字节或车辆来源真实性。</p><p>超时严格超过阈值后第 1 微秒开始；未恢复事件只统计到日志末尾。分钟超时时长是各 ID/通道的累计信号时长，同一时刻多个信号可叠加。</p><p>交互看板：运行 <code>run_monitor.cmd</code>，可按场景、规则与时间过滤，选择事件查看触发、前序和恢复报文。</p><small>生成 UTC {escape(report['generated_at_utc'])}</small></div>{body}</main></body></html>'''
    (output / "report.html").write_text(html, encoding="utf-8")
    if not all_ok:
        raise ValueError("monitor report reconciliation failed; inspect report.json")
    return report
