# 用四次小练习掌握这一版

每次先写预测，再运行核对；一次只改一个条件。

## 1. 看懂一条原始报文

打开 `data/monitor/MON01_boundaries.asc`，找 `0.200000` 的 `0x100` 报文。先猜前两字节怎样组成车速，再看已有协议：小端无符号数，分辨率 0.01 km/h。说明物理行号与接受报文序号为什么不同。

## 2. 自己查询事件

在项目目录运行 `.\.analysis-venv\Scripts\python.exe`，输入：

```python
import duckdb
con = duckdb.connect("artifacts/log_monitor.duckdb", read_only=True)
con.sql("""
SELECT trace_id, rule, COUNT(*) AS events
FROM mon.events
GROUP BY trace_id, rule
ORDER BY trace_id, rule
""").show()
```

关掉参考，从空白重写“只统计 MON01 的各类事件数”。然后再加上持续时间总和，并解释点事件的持续时间为什么为 0。

## 3. 用 JOIN 找到原始行

先预测：初始缺报没有最后有效帧时，INNER JOIN 会漏掉什么？然后执行：

```sql
SELECT e.rule, e.start_us, f.physical_line, f.raw_line
FROM mon.events e
LEFT JOIN mon.frames f
  ON e.trace_id = f.trace_id AND e.frame_no = f.frame_no
WHERE e.trace_id = 'MON01_boundaries'
ORDER BY e.start_us;
```

把 `frame_no` 换成 `recovery_frame_no` 查恢复；解释为什么必须同时连接 `trace_id`，不能只按帧序号。

## 4. 修改一个参数并验证

先预测把超时从 300 改到 500 ms 后，哪些事件会消失、哪些仍存在。使用另一个临时库，保留原验证证据：

```powershell
.\.analysis-venv\Scripts\python.exe -m can_monitor demo --timeout-ms 500 --db artifacts/practice.duckdb --output reports/log_monitor/practice
```

查询两库的 timeout 事件，找一条具体差异，手算起点。重复同一命令验证 skipped。练习库的数据不能混充默认规则结果。

能独立完成这四步后，再练习新增一条规则、手写边界夹具和测试。面试可先描述为“AI 辅助搭建，并由我复现、查询和修改了……”；只有自己做过的动作才填入空白。
