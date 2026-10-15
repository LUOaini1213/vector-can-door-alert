# CANoe 演示与本项目运行方式

核对日期：2026-10-15。以下在线演示条件依据 [Vector 官方 CANoe Demo FAQ](https://portal.vector.com/de/web/help/canoe-demo)，后续以官方页面和实际账户可用状态为准。

## 官方在线演示能做什么

Vector 提供免费的交互式 CANoe 在线演示，通过 AWS WorkSpaces 流式访问，不需要在本机安装 CANoe。使用时需要登录 Vector Customer Portal 并同意相应条款。

它适合学习 CANoe 的界面和官方示例流程。官方 FAQ 同时明确：

- 不能上传用户自定义数据库或数据。
- 会话是临时的，所做修改不会保留。

因此，在线演示可以帮助你学习操作；不能用它直接上传本仓库 DBC、CAPL 和场景来完成自定义工程验证。登录成功、打开演示或看到界面，也不等于本项目已经在 CANoe 中运行。

## 如何进入

1. 打开 [CANoe 产品页](https://www.vector.com/zh/product/canoe/)，寻找在线演示入口，或从上述官方 FAQ 的入口进入。
2. 登录 Vector Customer Portal，阅读实际显示的使用条款后由你决定是否接受。
3. 在演示中练习观察网络、报文、信号和测试流程；记录实际操作过的步骤。
4. 把自己的操作过程写入学习记录，不把临时会话当作工程备份位置。

入口或登录页面变化时，回到官方产品页查找。这里不承诺账户开通速度、演示时长或可选模块，也不把历史演示版本的节点数量限制套用到当前在线版本。

## 如果要运行自己的 CANoe 工程

本机安装包和适用的使用授权是两件事。正式使用需要对应的授权；可否申请支持自定义工程的评估环境、评估期限和可用模块，需要由 Vector 确认。官方 FAQ 给出的联系渠道是 `sales@vector.com`，可向其咨询本项目所需的评估方式。本仓库没有代你发送咨询或申请。

准备咨询时，说明自己需要：Classic CAN 仿真、导入自定义 DBC、编译和运行 CAPL，以及本机无真实 ECU 的教学场景。以实际获得的授权范围决定能执行哪些集成步骤。

## 没有授权时照常完成项目

在仓库根目录运行：

```powershell
python -m unittest discover -s tests -v
python -m door_alert demo --output reports/demo
python -m door_alert run --scenarios data/scenarios.json --output reports/latest
```

这条路径通过 Python 生成 CAN 帧、计算状态并检查场景断言，无需 CANoe。可以完成信号编码、状态机、去抖、滞回、超时、异常注入和报告分析。

后续获得合适环境后，继续执行 `canoe/` 中的导入与运行说明。只有实际完成 DBC 导入、CAPL 编译、运行和结果核对，才能把相应阶段记为完成。

## 记录两种不同的进度

| 阶段 | 记录内容 |
|---|---|
| Python 本机验证 | Python 版本、命令、运行日期、报告位置、实际断言结果 |
| 官方在线演示学习 | 日期、亲手操作的窗口与功能、能独立解释的步骤 |
| 自定义 CANoe 工程验证 | CANoe 版本及授权范围、工程配置、DBC 导入、CAPL 编译日志、Trace 与测试结果 |

仓库初始提供的是可运行的 Python 验证路径和待集成的 CAPL 源码。每一阶段的完成状态都根据实际证据填写。
