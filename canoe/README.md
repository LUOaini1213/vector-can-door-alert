# CANoe 接入与人工验收说明

## 当前状态与所需环境

本目录包含两个 **待编译的 CAPL 接入源码**，并非已运行的 CANoe 工程。当前没有在用户的 CANoe 环境中编译、启动测量或生成 Trace；根目录 Python 仿真的结果不能作为 CANoe 验证证据。这里不提供虚构的 `.cfg` 文件。

Vector 有免费的 CANoe 在线演示，但官方 FAQ 说明其环境不能上传用户数据或自定义数据库，且会话不保留更改。因此，在线演示可用于熟悉界面和内置样例，**不能直接导入本项目的 DBC/CAPL 来完成验收**。运行下面的步骤需要允许导入自定义文件的合适 CANoe 环境及其有效使用权限；可向学校实验室或 Vector 询问可用的培训/评估方式。[官方在线演示 FAQ](https://portal.vector.com/de/web/help/canoe-demo)

以下按 CANoe 桌面版的经典 CAN 工作流写成。菜单名称会随版本和界面语言变化；没有记录可用版本号之前，不把某个菜单路径当成现场验证结果。CANoe 19 起可访问在线帮助；早期版本使用安装内的 Help。遇到 API 签名或编译错误，以对应安装版本的 CAPL Reference 为准。[Vector CAPL 文档入口](https://support.vector.com/kb?id=kb_article_view&sysparm_article=KB0011332)

## 文件和拓扑

| 文件 | 放置位置 | 职责 |
|---|---|---|
| `door_alert.can` | CAN1 的 Simulation Setup 网络节点 `DoorAlert` | 接收 0x100/0x101，每 10 ms 计算一次并输出 0x200 |
| `scenario_driver.can` | 同一 CAN1 的 Simulation Setup 网络节点 `ScenarioDriver` | 唯一输入源，每 100 ms 发送输入，键 1–4 选择场景 |
| `../data/body_control.dbc` | 同一 CAN1 的 Databases | 给 Trace/Graphics 提供报文名和物理量解码 |

不使用系统变量，不依赖面板、额外 DLL、诊断模块或 vTESTstudio。CAPL 用 ID 和原始字节读写；DBC 负责显示层解码。两个节点都放在 **Simulation Setup**，不放在 Measurement Setup 的过滤链中。Vector 说明测量链中的 CAPL 节点可能需要显式转发报文；这里的节点没有网关/转发职责，因此不使用 `output(this)`。[Vector 节点位置说明](https://support.vector.com/kb/?id=kb_article_view&sysparm_article=KB0012859)

## 新建本地仿真配置

1. 在合适的 CANoe 环境中新建 **CAN / Classic CAN** 空白配置，只保留一个 CAN 网络和逻辑通道 **CAN1**。本项目不使用 CAN FD 或扩展 ID。
2. 在该版本的工作模式设置中选择 **Simulation / Simulated bus**，确认测量不要求真实接口。具体名称按本机帮助查找；如果仍提示必须连接硬件或授权不包含仿真，先解决环境条件，不把硬件映射错误当成源码故障。
3. 将 CAN1 设为一致的经典 CAN 位速率，例如 **500 kbit/s**。这是教学配置值，不是车型参数。
4. 打开 **Simulation → Simulation Setup**。在 CAN1 的 **Databases → Add** 中加入 `data/body_control.dbc`，确认解码的 VehicleStatus、DoorStatus、AlertStatus 的 ID 分别为 `0x100`、`0x101`、`0x200`，且 DLC 为 8。不要让同一网络挂两个定义相同 ID 的不同 DBC。
5. 在 CAN1 网络线上通过 **Insert Network Node** 建立 `DoorAlert` 与 `ScenarioDriver` 两个节点。打开每个节点的 Configuration，将状态设为 simulated/enabled，并分别选择本目录中同名 CAPL 文件。如果要求关联 DBC 节点，选择相应的控制器或刺激源节点；源码已显式使用 CAN1，逻辑通道必须匹配。
6. 关闭自动生成的交互层/剩余总线发送器，或确认它们不发送上述三个 ID。不要再增加 Interactive Generator、Replay 或第三个输入节点。本演示必须由 `ScenarioDriver` 独占 `0x100/0x101`，由 `DoorAlert` 独占 `0x200`。
7. 在 CAPL Browser 中分别打开两份源码，编译；记录 CANoe 完整版本、编译时间和完整诊断。只有出现编译成功，才能把状态从“未编译”改成“本版本编译通过”。若编辑器不能直接识别文本结构，在本机 CAPL Browser 建立空白文件，将 variables、函数和对应事件体移入其原生结构后重编译，并保存实际改动。
8. 使用 CANoe 自己的 Save As 保存本机 `.cfg`，保持 DBC/CAPL 的相对引用。更换电脑后重新打开，验证引用仍能解析。

第 4–5 步的基本菜单来自 Vector 的 Test Feature Set 教程。此处只使用其“关联数据库”和“添加仿真节点”工作流，**不需要**教程中的测试模块、系统变量或诊断功能。[Vector 官方教程](https://support.vector.com/sys_attachment.do?sys_id=b1d992aa1bcca094d2cd97de1d4bcb4b)

## Trace Graphics 与运行

1. 打开 **Trace**、**Graphics** 与 **Write** 窗口。Trace 保留时间、通道、方向、ID、DLC、Data，并将 ID 过滤为 100/101/200（十六进制）。检查 0x100 和 0x101 为约 100 ms 周期，0x200 为约 10 ms 周期。
2. 在 Graphics 中从 DBC 的信号树加入 `VehicleSpeed`、`IgnitionOn`、`DoorFL`、`DoorFR`、`DoorRL`、`DoorRR`、`Warning`、`DataFault`、`Reason`。车门原始掩码可同时在 Trace 的 DoorStatus byte 0 观察。不要把 raw 500 当成物理 500 km/h：速度因子是 0.01。
3. 开始 Measurement。初始 0x200 应为 `00 01 01 00 00 00 00 00`，意为没有输入时 data_fault=1。初始状态的发送请求在 `on start`，实际总线 Trace 可有发送时延。
4. 默认运行场景 1。将焦点放在能接收 CAPL 键事件的 CANoe 窗口，按 1、2、3、4；先确认 Write 显示 `Scenario n selected`，再判断切换是否成功。每个场景重复周期为 5 s，前 500 ms 都发送点火关闭、车门关闭的正常帧，用真实输入复位控制器。
5. 每切一个场景至少记录一整轮 5 s。测量停止后保存原始 CANoe 日志（如 BLF/ASC）、配置与 Graphics/Trace 截图。不要仅凭 Write 的 `output` 调用日志证明接收或通过。

## 四组人工验收点

以下是**待执行的预期结果**，不是已通过的测试记录。帧内容和具体时刻以实际 Trace 为证据。输出三元组依次为 `(warning, data_fault, reason)`。

先定义对齐零点：每次选场景后，找到首个周期输入帧的发送时刻 `T`，理想值为全局 `5 mod 10 ms`。`B` 是该帧已到达后，控制器进行的第一个 10-ms 评估时刻，理想值为 `T+5 ms`。下表时间为 **相对 B**，不是按键的时刻，也不是 Measurement 起始时刻。

| 按键 | 相对 B 的时刻 | 输入或观察点 | 预期输出 |
|---|---:|---|---|
| 1 正常 | 0 ms | 点火关闭，所有输入有效 | `(0,0,2)` |
| 1 正常 | 500 ms | 点火开启、门关闭 | `(0,0,3)` |
| 1 正常 | 1000 ms | 10 km/h、门开 | `(0,0,5)` 开始去抖 |
| 1 正常 | 1190 ms | 连续条件仅 190 ms | `(0,0,5)` |
| 1 正常 | 1200 ms | 连续条件达到 200 ms | `(1,0,6)` |
| 1 正常 | 2000 ms | 关门 | `(0,0,3)` |
| 1 正常 | 2700 ms | 2500 ms 再次开门后经过 200 ms | `(1,0,6)` |
| 1 正常 | 3500 ms | 点火关闭，门仍开 | `(0,0,2)` |
| 2 边界 | 500 ms | 4.99 km/h、门开 | `(0,0,4)` |
| 2 边界 | 1000 / 1190 / 1200 ms | 5.00 km/h 的去抖边界 | `(0,0,5)` / `(0,0,5)` / `(1,0,6)` |
| 2 边界 | 1500 ms | 4.00 km/h，已激活 | `(1,0,6)`，回差保持 |
| 2 边界 | 2000 ms | 3.00 km/h | `(0,0,4)`，包含下阈值 |
| 2 边界 | 2500 ms | 4.99 km/h，未激活 | `(0,0,4)`，不能重新激活 |
| 2 边界 | 3200 / 3300 / 3500 ms | 再去抖完成 / 4 km/h / 关门 | `(1,0,6)` / `(1,0,6)` / `(0,0,3)` |
| 3 丢帧 | 700 ms | 500 ms 开门后已去抖 | `(1,0,6)` |
| 3 丢帧 | 1000–1600 ms | 暂停 DoorStatus；VehicleStatus 继续 | 仅门数据逐渐变旧 |
| 3 丢帧 | 约 1200 ms | 门数据年龄首次超过 300 ms 的评估点 | `(0,1,1)` |
| 3 丢帧 | 1700 / 1900 ms | 门帧恢复 / 重新去抖 200 ms | `(0,0,5)` / `(1,0,6)` |
| 4 非法帧 | 1000 ms | DoorStatus DLC=1 | `(0,1,1)` |
| 4 非法帧 | 1200 / 1400 ms | 同 ID 正常帧恢复 / 去抖完成 | `(0,0,5)` / `(1,0,6)` |
| 4 非法帧 | 1800 / 2000 / 2200 ms | 门 mask=16 / 恢复 / 去抖完成 | `(0,1,1)` / `(0,0,5)` / `(1,0,6)` |
| 4 非法帧 | 2600 / 2800 / 3000 ms | 速度 raw=25001 / 恢复 / 去抖完成 | `(0,1,1)` / `(0,0,5)` / `(1,0,6)` |
| 4 非法帧 | 3400 / 3600 / 3800 ms | ignition=2 / 恢复 / 去抖完成 | `(0,1,1)` / `(0,0,5)` / `(1,0,6)` |
| 4 非法帧 | 4200 ms | 正常关门 | `(0,0,3)` |

场景 4 的“非法帧”指本项目应用协议不接受的 DLC/字段值，**不是**物理 CAN CRC、ACK、位错误或错误帧注入。未知 ID 也不会改变控制器状态。

## 与 Python 时间语义如何对齐

- Python 场景文件把输入时刻和评估时刻放在同一个整数 10-ms 网格上，规定“同一时刻先接收所有输入，再评估”。CANoe 是事件驱动且包含发送、仲裁、接收等事件，不能从源码假设同时间戳回调的顺序与 Python 完全相同。
- 因此刺激源在 `5 mod 10 ms` 发起输入，控制器在 `0 mod 10 ms` 评估，留出约 5 ms 间隔；不依赖两个节点的 `on start` 调用次序。一个周期内同一 ID 只发一帧，避免“正常帧和坏帧谁最后到”的歧义。
- 控制器使用 `timeNow()/100` 得到整数 ms，以**本节点实际接收时刻**记录输入年龄；周期触发使用 `msTimer`。正常仿真负载下表中的 B 对齐结果应吻合。若某输入在下一个评估点后才到，状态转换会后移一个或多个 tick；必须按 Trace 的接收时间定位原因，不能把所有延迟都算成算法问题。
- freshness 的判断严格是 `age <= 300 ms` 可用，`age > 300 ms` 故障。Python 网格的例子常在年龄 310 ms 首次报旧；CAPL 接收可能位于 5 ms 相位，因此首个报旧点可能为年龄 305 ms。这是采样相位差，不能把故障阈值改成 `>=300` 来“对齐”。
- 边界验收应先检查原始字节，然后检查**第一次满足条件的控制评估点**，200 ms 后才允许告警。图上物理发帧到告警的间隔可以是约 205 ms；Trace 的状态报文还包含输出排队/发送时间。
- 若要逐帧对比 Python，先记录 CANoe 实际接收时刻、统一时间原点和采样规则，使用相同输入时间轴重放；不能直接比较原有 `data/scenarios.json` 的绝对时间与本互动刺激源。本文的 4 个循环演示也不代替 Python 全部回归场景。
- `timeNow()` 的 32 位 10-µs 计数会回绕。本源码限定短教学测量（建议单次小于 1 小时并重启测量），没有实现跨回绕的长期计时方案。周期定时器采用回调内重装；实时负载造成的调度偏移应在实际环境记录。

## 验收证据模板

在合适环境真实执行后填写，当前值均为“未执行”：

| 项目 | 当前记录 |
|---|---|
| CANoe 版本与有效使用环境 | 未执行 |
| 两文件编译诊断 | 未执行 |
| 仿真模式与 CAN1 配置截图 | 未执行 |
| 0x100/0x101 周期、DLC、raw 字节检查 | 未执行 |
| 0x200 初始化与 10-ms 周期 | 未执行 |
| 场景 1–4：实际时刻/预期/实际/判定 | 未执行 |
| 3.00 / 5.00 阈值与去抖 190/200-ms 边界 | 未执行 |
| 丢帧超时和有效帧恢复 | 未执行 |
| DLC/字段异常与同 ID 恢复 | 未执行 |
| 原始日志与保存后可重开的本机配置 | 未执行 |

验收失败时依次检查：编译首个诊断 → 节点是否 enabled → CAN1/仿真模式 → 发送器是否唯一 → Trace 是否实际收到 → 原始字节和 DLC → 接收与评估时序 → 状态机分支。每条结论保留证据，不将尚未执行的步骤写成通过。

## 官方参考

- [CANoe 在线演示 FAQ](https://portal.vector.com/de/web/help/canoe-demo)：在线环境的上传与会话限制。
- [CAPL Documentation KB0011332](https://support.vector.com/kb?id=kb_article_view&sysparm_article=KB0011332)：按版本查完整 API/事件参考。
- [CANoe Test Feature Set Tutorial](https://support.vector.com/sys_attachment.do?sys_id=b1d992aa1bcca094d2cd97de1d4bcb4b)：数据库关联与仿真节点配置。
- [CAPL Callback Interface in CANoe](https://support.vector.com/sys_attachment.do?sys_id=27ee721387020a18a0460fe40cbb35d3)：CAPL 节点及毫秒定时器的官方实例；本项目不依赖其诊断模块。
- [CAPL 在测量/仿真节点中的位置差异](https://support.vector.com/kb/?id=kb_article_view&sysparm_article=KB0012859)：节点位置、转发和跨区域时延。

链接查阅日期：2026-10-15。上述来源用于查工作流与 API，本文的车门告警需求、阈值和验收场景为自拟教学内容。
