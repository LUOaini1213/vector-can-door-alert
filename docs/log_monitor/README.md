# 车辆日志分析与异常监控

这是原 CAN 项目的第二阶段：把离线 ASC 日志变成可查询的信号、可解释的规则事件和交互看板。2026-10-15 在 AI 辅助下新增；示例全部是明确标记的仿真数据。

## 一键启动

Windows 在项目根目录双击 `run_monitor.cmd`。首次会创建 `.analysis-venv`、安装固定版本依赖、导入示例并启动本地 Streamlit。浏览器地址为 `http://127.0.0.1:8503`。结束时在启动终端按 Ctrl+C。

手动运行：

```powershell
py -3 -m venv .analysis-venv
.\.analysis-venv\Scripts\python.exe -m pip install -r requirements-monitor.txt
.\.analysis-venv\Scripts\python.exe -m can_monitor demo
.\.analysis-venv\Scripts\python.exe -m streamlit run monitor_app.py --server.address 127.0.0.1 --server.port 8503 --browser.gatherUsageStats false
```

如果本目录已经有环境，从第三条开始。新库为 `artifacts/log_monitor.duckdb`，可以由源码和示例重建；看板只读，导入由 CLI 完成。避免在其他进程写库时打开看板查询，导入完成后再刷新。

## 建议先演示 MON01_boundaries

1. 左侧选择 `MON01_boundaries`，时间窗保持完整。
2. 看车速采样，识别 0.2 秒的 10→40 km/h 跳变；图只画真实采样点，不跨缺报间隙连线。
3. 在异常表选择 `MESSAGE_TIMEOUT` 事件，查看最后有效帧和恢复帧。它们可能相隔几十秒，恢复帧仍会显式列出。
4. 在分钟统计中观察超时区间怎样跨过 60 秒边界。两种信号的超时时长可以叠加，不能当成整车停机秒数。
5. 在隔离页找到 DLC 与实际字节数不一致的原始行，检查源文件物理行号。

完整 demo 来源为 `reports/demo/traces/SC01.asc` 至 `SC16.asc`，加 `data/monitor/MON01_boundaries.asc`。新样例是人工编写的边界输入，不是采集的车辆运行记录。原仿真 SC13 的 9 字节软件入口测试没有导出为合法经典 CAN ASC 报文，因此监控只能分析实际导出的 ASC 内容。

## 三条规则

| 规则 | 当前教学口径 | 追溯依据 |
|---|---|---|
| SIGNAL_INVALID | 已知 ID 的长度或信号值不符合固定协议 | 触发帧、原始字节、解码错误 |
| SPEED_JUMP | 同通道相邻有效车速，间隔不超过超时阈值，变化率绝对值 >100 km/h/s | 前一有效帧与当前帧 |
| MESSAGE_TIMEOUT | 默认通道 1 的 0x100、0x101 超过 300 ms 未收到匹配的有效帧 | 最后有效锚点、恢复帧或日志结束 |

速度变化率恰等于阈值不触发；同一时刻不同速度单独记录为时间冲突，变化率未定义，不伪造无穷大。超过超时阈值的长间隙会重新建立速度比较基准。无效帧不会刷新“最后有效”时间。

监控精度为整数微秒。有效帧龄 **<=300 ms**，首次超时在最后有效时间加 **300,001 μs**；如果该微秒恰好收到有效恢复帧，保留持续时间为 0 的边界事件。原控制器按 10 ms 网格评估，因此它可能在 310 ms 才输出 data_fault；这不是同一个采样过程。

缺少第一条有效输入时，从日志起点给予同样的初始宽限。文件结束后不外推：`open_at_end=True` 表示尚未观察到恢复，时长只统计到最后一条接受报文。未知 ID 保留为 unknown，不擅自判为故障。

## 表与重跑

- `mon.traces`：源文件 SHA256、来源标记、配置、模型指纹、数量和时间范围。
- `mon.frames`：接受的原始报文、物理行号与解码结果，重复帧保留。
- `mon.rejected_lines`：不支持或结构错误的候选行，保留原文和原因。
- `mon.events`：规则事件、区间、触发/前序/恢复帧引用。
- `mon.minute_stats`：每分钟帧数、事件起点数、超时累计信号时长、有效车速采样均值与最大值。
- `mon.runs`：导入成功、跳过、失败审计；时间字段为 UTC。

相同日志 ID、来源字节、规则和模型指纹再次导入会跳过；改变输入、参数或模型会在事务中只替换该日志，保留其他日志。`after_delete` 故障注入验证发布回滚，FAILED 审计保留。

仅支持本项目的经典 CAN、标准 11 位 ID、绝对秒时间、十六进制 ASC 子集。错误候选行进入隔离；不支持的 base/relative 头部、已接受报文倒序、无接受报文会拒绝整次导入。UTF-8/BOM 可用。没有通用 CAN FD、扩展帧、任意厂商 ASC 或任意 DBC 导入能力。信号解码复用 `door_alert.protocol`，与现有固定 `body_control.dbc` 对应。

自己的 ASC 用：

```powershell
.\.analysis-venv\Scripts\python.exe -m can_monitor ingest "C:\your-log.asc" --trace-id MY01
```

这类导入默认标为 `user-provided-unverified`；来源标签不证明实车真实性。看板可通过 `CAN_MONITOR_DB` 环境变量切换到另一个已建好的库。

## 验证与边界

2026-10-15 实际运行：17 份仿真日志、1,260 条接受报文、19 个规则事件（7 次超时、9 次信号无效、3 次速度突变）、1 行格式隔离。新增 21 项独立验收通过，Streamlit AppTest 的 8 项交互检查通过，1,260 条接受记录与 python-can 独立解析结果逐项一致。原有 32 项控制器单元测试仍通过。

```powershell
.\.analysis-venv\Scripts\python.exe -m unittest discover -s tests_monitor -v
.\.analysis-venv\Scripts\python.exe scripts/verify_monitor.py
```

本次实际证据见 `reports/log_monitor/2026-10-15/`。原有控制器、DBC/ASC 格式交叉检查和新增监控的验证分别记录。本扩展不改变 CANoe/CAPL 未编译、未运行的状态，也不构成车辆安全策略或真实故障诊断。

`verify_monitor.py` 使用单独的 `artifacts/monitor_verification.duckdb` 存放固定样例验收，不改动用户工作的 `log_monitor.duckdb`。

技术参考：[python-can ASCReader](https://python-can.readthedocs.io/en/stable/file_io.html)、[Streamlit 文档](https://docs.streamlit.io/)、[DuckDB Python](https://duckdb.org/docs/stable/clients/python/overview)。
