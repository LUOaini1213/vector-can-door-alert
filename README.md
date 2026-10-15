# 车门状态告警 CAN 仿真与自动化测试

一个从汽车产品需求走到信号定义、状态逻辑、异常测试与结果追踪的教学项目。
场景是：点火开启、车门未关且速度达到触发条件时提醒驾驶员。

**现在即可运行的部分是 Python 离线仿真。** 无需 CANoe、CAN 接口或第三方 Python 包。
仓库另附 DBC 和两份 CAPL 接入源码；CAPL 尚未在 CANoe 中编译、运行。
这两项验证状态分别记录，不混为同一项。

## 立即运行

需要 Python 3.10 或以上。在本目录打开终端：

```powershell
python -X utf8 -m door_alert demo
```

Windows 也可以双击 `run_demo.cmd`，它会运行场景并打开本次 HTML 报告。
报告默认在 `reports/demo/report.html`，可直接用浏览器打开。

运行全部标准库检查：

```powershell
python -X utf8 scripts/check_project.py
```

第一次阅读按这个顺序：

1. `docs/learning_guide.md`：七个小任务，先预测再运行。
2. `docs/requirements.md`：为什么 190 ms 不报、200 ms 报，300 ms 新鲜、310 ms 超时。
3. `reports/demo/report.html`：逐场景查看输入、警告、数据故障与断言。
4. `docs/design.md` 与 `door_alert/controller.py`：查看信号和状态逻辑。
5. `canoe/README.md`：以后在合适的 CANoe 环境中导入与验收。

## 需求到结果

```mermaid
flowchart LR
    A[需求 REQ-01 至 12] --> B[DBC 与场景输入]
    B --> C[CAN 报文编解码]
    C --> D[10 ms 控制器]
    D --> E[与手工预期对照]
    E --> F[报告与报文轨迹]
```

输入为两条经典 CAN 标准帧，输出为一条状态帧，DLC 均为 8。

| 报文 | ID | 内容 |
|---|---|---|
| VehicleStatus | `0x100` | 车速，0.01 km/h 分辨率；点火状态 |
| DoorStatus | `0x101` | 左前、右前、左后、右后四扇车门的开闭位 |
| AlertStatus | `0x200` | warning、data_fault、原因码 |

触发与解除规则：

- 两路数据有效、新鲜，点火开启，任一门打开，速度 **>=5.00 km/h 连续 200 ms** 后开启警告。
- 已开启后，速度 **<=3.00 km/h** 解除；3..5 km/h 之间保持已有状态，避免阈值抖动。
- 关门或关闭点火，在当前评估点解除警告。
- 任一路输入缺失、无效或超时，输出 `data_fault=1`，清除原去抖计时；数据恢复后重新等 200 ms。
- 新鲜度定义为帧龄 **<=300 ms**；模型每 10 ms 评估，因此 310 ms 的评估点报超时。
- 以上阈值是本项目的教学定义。数据故障时清除本项目的警告并单独置故障位，是供测试讨论的设计选择，不是量产车辆安全策略。

## 本轮实际验证

2026-10-15 执行所得，原始证据保留在 `reports/demo/`：

| 检查 | 结果 | 证据 |
|---|---|---|
| 标准库单元测试 | 32 个测试通过 | `check_summary.json`，脚本可复跑 |
| 手工预期场景 | 16 场景、121 个时点断言通过 | `report.json`、`assertions.csv` |
| 选定边界变异 | 4/4 被场景检出 | `mutation_check.json` |
| 失败是否传播给终端 | 故意改错预期时返回码 1 | `mutation_check.json` |
| DBC 独立编解码交叉检查 | 2,058 个向量通过 | `interop_check.json`，cantools 45.0.0 |
| ASC 独立解析与内容对照 | 16 文件、1,237 条消息通过 | `interop_check.json`，python-can 4.6.1 |
| CANoe / CAPL | 未执行 | 待 `canoe/README.md` 中的人工验收 |

DBC 检查把本仓的字节结果与独立开源解析器对照；ASC 检查核对每条消息的
时间、ID、方向和数据。它们不证明 CANoe 已成功导入，也不证明 CAPL 编译通过。
SC13 的 9 字节输入只用于软件入口长度错误测试，不能作为合法经典 CAN 帧发送。
这种过长输入保留在 JSON 证据中，导出 ASC 时跳过，并记录跳过数量。

如需复跑可选的独立格式检查：

```powershell
python -m venv .verification-venv
.\.verification-venv\Scripts\python.exe -m pip install -r requirements-verification.txt
.\.verification-venv\Scripts\python.exe scripts/verify_interop.py
```

日常仿真和全部单元测试不需要安装这些可选包。

## 输出与复现

- `report.json`：全部输入、每个 10 ms 周期、每个预期/实际断言和源文件 SHA-256。
- `report.html`：场景筛选、失败筛选、时序图与需求关联表。
- `assertions.csv`：断言汇总，可用 Excel 查看。
- `traces/SCxx.csv`：该场景全部控制器快照。
- `traces/SCxx.asc`：合成经典 CAN 报文轨迹，可由 ASC 解析器读取。

事件均在 10 ms 网格上。同一时刻先接收全部输入，再计算；同 ID 最后一帧生效。
运行不依赖真实时间或随机数。相同输入产生相同逻辑结果；报告生成时间会变化。
只允许报告所列的 0x100/0x101 输入改变对应状态，未知 ID 被忽略。

## 新增：日志分析与异常监控

第二阶段已补充 ASC 导入、固定协议解码、三类规则、DuckDB 存储、SQL 分钟统计及中文 Streamlit 只读看板。规则为报文超时、信号无效和车速突变；选择一条事件可追溯到原 ASC 物理行，以及前序有效帧或恢复帧。

Windows 双击 **`run_monitor.cmd`**；它会安装单独的可选依赖、建示例库并打开本地看板。原来的 `run_demo.cmd` 和标准库仿真仍可直接使用。

完整运行方式、时间边界和限制见 [日志监控说明](docs/log_monitor/README.md)，练习顺序见 [四次小练习](docs/log_monitor/learning.md)。本次冻结报告位于 [监控报告](reports/log_monitor/2026-10-15/report.html)，独立验收见 [acceptance.json](reports/log_monitor/2026-10-15/acceptance.json)。演示仍使用仿真数据，不改变下述 CANoe/CAPL 状态。

## CANoe 演示版能做什么

Vector 当前提供免费的交互式在线演示，需登录客户门户。官方 FAQ 明确表示：
**不支持上传用户自定义数据库/数据，且退出会话后修改不保存**。
因此，它适合练习内置样例和界面；本仓自定义 DBC/CAPL 需要能导入自定义文件的
合适环境才能进一步验证。详细入口和下一步见 `docs/demo_access.md`。

官方来源：

- [CANoe 产品与应用范围](https://www.vector.com/zh/product/canoe/)
- [在线演示与限制 FAQ](https://portal.vector.com/de/web/help/canoe-demo)
- [CAPL 文档入口](https://support.vector.com/kb?id=kb_article_view&sysparm_article=KB0011332)
- [cantools 官方项目](https://github.com/cantools/cantools)
- [python-can 官方文档](https://python-can.readthedocs.io/)

## 面试与贡献说明

本项目于 2026-10-15 在 AI 辅助下新建。它用于补足从需求到验证的个人学习产物，
不归入既往实习或企业交付。仓库产物与本人能独立实现的能力分别评价。
建议先完成学习指南中的改参数、加用例、解释失败三项，再按实际操作描述个人贡献。
`docs/interview.md` 提供可核验的讲法和追问，避免把尚未执行的 CANoe 阶段写成已完成。

后续可完成的具体升级：在合适环境中导入 DBC、编译两份 CAPL，按验收表记录真实日志；
再把 Python 断言接到真实日志回放中，进行跨环境结果对照。
