"""Evidence reports: explicit assertions, requirements links, and reproducible traces."""

from datetime import datetime, timezone
from html import escape
import csv
import hashlib
import json
from pathlib import Path

from . import __version__
from .controller import Reason
from .protocol import encode_alert


def source_hashes(root):
    paths = sorted(list((root / "door_alert").glob("*.py"))
                   + list((root / "data").glob("*")) + list((root / "canoe").glob("*.can"))
                   + list((root / "tests").glob("*.py")) + list((root / "scripts").glob("*.py"))
                   + [root / "docs/requirements.md", root / "docs/design.md"])
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}


def _asc(path, result, stamp):
    # This is a synthesized Classic CAN log, not a recording from real hardware.
    lines = [f"date {stamp.strftime('%a %b %d %I:%M:%S %p %Y')}",
             "base hex timestamps absolute", "internal events logged",
             "// Synthetic educational trace; no CANoe/hardware execution is claimed.",
             "Begin Triggerblock"]
    events = []
    for n, frame in enumerate(result["input_frames"]):
        events.append((frame["timestamp_ms"], 0, n, frame["arbitration_id"],
                       frame["data_hex"], "Rx"))
    for n, state in enumerate(result["trace"]):
        frame = encode_alert(state["timestamp_ms"], state["warning"], state["data_fault"], state["reason"])
        events.append((frame.timestamp_ms, 1, n, frame.arbitration_id, frame.data.hex(" ").upper(), "Tx"))
    events.sort(key=lambda e: e[:3])
    omitted = 0
    for at, _, _, arbitration_id, hex_data, direction in events:
        size = len(bytes.fromhex(hex_data))
        if size > 8:
            # A Classic CAN wire log cannot represent an impossible DLC9 frame.
            # The rejected API input remains in report.json for fault-injection evidence.
            omitted += 1
            continue
        lines.append(f"{at / 1000:.6f} 1 {arbitration_id:X} {direction} d {size} {hex_data}")
    if omitted:
        lines.append(f"// {omitted} overlength injection(s) omitted; see report.json input_frames.")
    lines.append("End Triggerblock")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return omitted


def _plot(trace):
    width, left, usable = 900, 45, 815
    duration = max(trace[-1]["timestamp_ms"], 10)
    top_speed = max(10, max((s["speed_kmh"] or 0) for s in trace))
    x = lambda s: left + s["timestamp_ms"] / duration * usable
    # Step polylines preserve tick-defined state changes instead of diagonal ramps.
    def step_points(values):
        out = []
        last_y = None
        for state, y in values:
            if last_y is not None: out.append(f"{x(state):.1f},{last_y:.1f}")
            out.append(f"{x(state):.1f},{y:.1f}")
            last_y = y
        return " ".join(out)
    warning = step_points((s, 147 - 36 * int(s["warning"])) for s in trace)
    fault = step_points((s, 212 - 36 * int(s["data_fault"])) for s in trace)
    # Split speed at unavailable intervals rather than drawing across missing data.
    runs, current = [], []
    for s in trace:
        if s["speed_kmh"] is None:
            if current:runs.append(current);current=[]
        else:current.append((s, 80 - 55 * s["speed_kmh"] / top_speed))
    if current:runs.append(current)
    speed = ''.join(f'<polyline points="{step_points(r)}" fill="none" stroke="#2563eb" stroke-width="2"/>' for r in runs)
    return f'''<svg viewBox="0 0 {width} 245" role="img" aria-label="Speed, warning and data-fault over simulation time">
<rect width="900" height="245" fill="#f8fafc"/>
<path d="M45 85H860 M45 150H860 M45 215H860" stroke="#cbd5e1"/>
<text x="5" y="20">km/h</text><text x="5" y="110">警告</text><text x="5" y="175">缺数</text>
<text x="45" y="237">0 ms</text><text x="780" y="237">{duration} ms</text>
{speed}<polyline points="{warning}" fill="none" stroke="#d97706" stroke-width="2"/>
<polyline points="{fault}" fill="none" stroke="#dc2626" stroke-width="2"/></svg>'''


def _html(report):
    summary = report["summary"]
    cards = []
    for result in report["scenarios"]:
        rows = []
        for check in result["assertions"]:
            def value(d):
                reason = d.get("reason")
                reason_text = f", reason={reason}" if reason is not None else ""
                return f"warning={int(d['warning'])}, fault={int(d['data_fault'])}{reason_text}"
            rows.append(f"<tr><td>{check['at_ms']}</td><td>{escape(value(check['expected']))}</td>"
                        f"<td>{escape(value(check['actual']))}</td><td>{'通过' if check['passed'] else '失败'}</td></tr>")
        status = "通过" if result["passed"] else "失败"
        cards.append(f'''<section id="{escape(result['id'], quote=True)}" class="case" data-passed="{str(result['passed']).lower()}">
<h2>{escape(result['id'])} {escape(result['title'])} <span class="{'pass' if result['passed'] else 'fail'}">{status}</span></h2>
<p>需求：{escape(', '.join(result['requirements']))} · {len(result['input_frames'])} 输入帧 · {len(result['trace'])} 控制周期</p>
{_plot(result['trace'])}
<details><summary>查看 {len(rows)} 个手工预期断言</summary><div class="table-wrap"><table><thead><tr><th>时间 ms</th><th>预期</th><th>实际</th><th>判定</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></details>
</section>''')
    req_rows = ''.join(f"<tr><td>{escape(req)}</td><td>{escape(', '.join(ids)) if ids else '尚未映射'}</td></tr>"
                       for req, ids in report["requirement_mapping"].items())
    options = ''.join(f'<option value="{escape(r["id"], quote=True)}">{escape(r["id"]+" "+r["title"])}</option>' for r in report['scenarios'])
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>车门告警仿真测试报告</title><style>
*{{box-sizing:border-box}}body{{font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif;color:#172033;background:#eef2f7;margin:0}}
main{{max-width:1080px;margin:auto;padding:32px 22px}}h1{{font-size:30px;line-height:1.3}}h2{{font-size:20px}}.case,.panel{{background:white;border:1px solid #d9e1eb;border-radius:12px;padding:22px;margin:20px 0}}
.counts{{display:flex;gap:16px;flex-wrap:wrap}}.counts div{{background:#fff;padding:14px 24px;border-radius:8px}}.counts strong{{font-size:28px;display:block}}
.pass{{color:#047857}}.fail{{color:#b91c1c}}svg{{width:100%;font:12px system-ui}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border:1px solid #dbe2eb;text-align:left;padding:9px}}th{{background:#f1f5f9}}
select,label{{font:inherit}}select{{max-width:100%;padding:8px;margin:8px}}.table-wrap{{overflow-x:auto}}summary{{cursor:pointer}}small{{color:#526079}}a{{color:#1d4ed8}}
@media print{{body{{background:white}}main{{padding:0}}.case{{break-inside:avoid}}.filters{{display:none}}details{{display:block}}}}
</style></head><body><main>
<h1>车门状态告警 仿真测试报告</h1><p>确定性时间轴 · CAN 报文编解码 · 需求到用例追踪</p>
<div class="counts"><div><strong>{summary['passed_scenarios']}/{summary['scenario_count']}</strong>场景通过</div><div><strong>{summary['passed_assertions']}/{summary['assertion_count']}</strong>断言通过</div><div><strong>{summary['mapped_requirements']}/12</strong>需求有场景映射</div></div>
<div class="panel"><strong>本次执行环境：Python 离线仿真</strong><p>数据与阈值是教学设计。以下结果来自实际执行 Python 控制器与手工预期的对照。CAPL 尚未在 CANoe 中编译或运行，ASC 是合成报文轨迹。需求映射数量不等于生产测试覆盖率。</p>
<small>UTC {escape(report['generated_at_utc'])} · 版本 {escape(report['version'])} · 证据和 SHA-256 见同目录 report.json</small></div>
<div class="panel filters"><label>查看场景 <select id="caseFilter"><option value="all">全部</option>{options}</select></label><label><input type="checkbox" id="failedOnly"> 只看失败</label></div>
{''.join(cards)}<section class="panel"><h2>需求与场景映射</h2><table><thead><tr><th>需求</th><th>关联场景</th></tr></thead><tbody>{req_rows}</tbody></table></section>
<p>原因码：1 数据不可用；2 点火关闭；3 车门全关；4 未达到触发条件/已降速解除；5 连续条件去抖中；6 告警激活。</p>
<script>function filterCases(){{const id=document.getElementById('caseFilter').value;const failed=document.getElementById('failedOnly').checked;document.querySelectorAll('.case').forEach(e=>{{e.hidden=(id!=='all'&&e.id!==id)||(failed&&e.dataset.passed==='true')}})}}document.getElementById('caseFilter').addEventListener('change',filterCases);document.getElementById('failedOnly').addEventListener('change',filterCases);</script>
</main></body></html>'''


def write_reports(results, output, root, scenario_path=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    traces = output / "traces"
    traces.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc)
    mapping = {f"REQ-{n:02d}":[] for n in range(1,13)}
    for result in results:
        for req in result["requirements"]:
            mapping[req].append(result["id"])
        result["asc_omitted_overlength_injections"] = _asc(traces / f"{result['id']}.asc", result, stamp)
        with (traces / f"{result['id']}.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=["timestamp_ms","warning","data_fault","reason","speed_kmh","door_mask","pending_since_ms"])
            writer.writeheader();writer.writerows(result["trace"])
    checks = [a for r in results for a in r["assertions"]]
    report = {"version":__version__, "generated_at_utc":stamp.isoformat(),
              "execution_environment":"Python deterministic offline simulation",
              "canoe_execution":"not_performed", "data_origin":"synthetic teaching scenarios",
              "source_sha256":source_hashes(root),
              "summary":{"scenario_count":len(results),"passed_scenarios":sum(r["passed"] for r in results),
                         "assertion_count":len(checks),"passed_assertions":sum(a["passed"] for a in checks),
                         "mapped_requirements":sum(bool(ids) for ids in mapping.values())},
              "requirement_mapping":mapping,"scenarios":results}
    if scenario_path is not None:
        source=Path(scenario_path)
        report["scenario_input"]={"name":source.name,"sha256":hashlib.sha256(source.read_bytes()).hexdigest()}
    (output / "report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (output / "report.html").write_text(_html(report),encoding="utf-8")
    with (output / "assertions.csv").open("w",newline="",encoding="utf-8-sig") as stream:
        writer=csv.DictWriter(stream,fieldnames=["scenario_id","at_ms","expected","actual","passed"])
        writer.writeheader()
        for result in results:
            for check in result["assertions"]:
                writer.writerow({"scenario_id":result["id"], "at_ms":check["at_ms"],
                                 "expected":json.dumps(check["expected"],ensure_ascii=False),
                                 "actual":json.dumps(check["actual"],ensure_ascii=False),"passed":check["passed"]})
    return report
