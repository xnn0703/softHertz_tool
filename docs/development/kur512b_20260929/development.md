# KuR512B 主动读取日志落盘 — 开发记录

> 实施期间持续维护。完成后把验收与未完成项总结到末尾。

## 实施顺序

1. 受控原件入库 + 协议笔记
2. `protocol.py` / `stream.py` / `models.py`
3. `widgets.py`（QtCharts 曲线）
4. `driver.py` + `StatusRecorder`
5. `panel.py`
6. `simulator.py`
7. `workspaces/kur512.py` + registry 注册
8. `pyproject.toml` + `run.sh` + `run.bat`
9. 测试 6 个
10. README / AGENTS.md 同步
11. `compileall` + `pytest` + `smoke`

## 设计要点

### StatusRecorder

独立后台线程、Queue(10000) 缓冲、50 MiB 单文件轮转。仿 `traffic_recorder.py`：

- `append(device_id, info, freq_mhz, raw_hex)`：非阻塞入队
- `finish()`：幂等，写汇总行（包含起止时间、行数、丢帧、错误）
- `close(timeout)`：等待线程退出

CSV 表头仅在文件首次创建时写出；轮转新文件后**重新写表头**。

### 主动轮询状态机

`_flush_tx()` 内：

```text
if normal_writing: 退避
if _query_interval and now >= _next_query_ns:
    device_id = ids[_round_index % len(ids)]
    frame = build_status_query_frame(device_id)
    self._tx_queue.put(frame)
    _round_index += 1
    _next_query_ns = now + _query_interval / len(ids)
else:
    处理普通业务帧
```

UI 速率通过 `_round_count` 与 `_round_window_start_ns` 计算 10 s 滑动均值。

### 撤销的目标工作频率字段

初版让用户在 UI 输入"目标工作频率"并写入 CSV `freq_mhz` 列，意图是提供上下文。但
KuR512B `0x9C` 响应里没有频点字段，这一字段会让用户误以为"必须配置才能跑"，且无任何
协议动作使用它。已在 2026-09-29 修订版移除：UI 不再显示该输入框，CSV 也不再有
`freq_mhz` 列，CSV 表头改为 `ts,device_id,rev,sys_vcc,sys_temp,mcu_ver,raw_hex`。

### 曲线控件 KUR512ChartView

- 内部 `QChart` + 左 Y 轴（温度 ℃）+ 右 Y 轴（电压 V）+ X 轴（相对秒）
- 每个 subarray 两条 `QLineSeries`：温度/电压
- `_downsample()`：超过 2000 点时按 min/max 桶压缩，桶宽 = ceil(N/2000)
- 切窗口只调 X 轴范围，**不清空 deque**
- `clear()` 删所有 series；下次 `add_series` 时重新建

### POL 控件

`Polarity` 枚举 `LINEAR/LHCP/RHCP`；面板：

- 单选：线极化 / LHCP / RHCP
- 线极化时数值输入框 0..180；LHCP/RHCP 数值框禁用
- `set_beam` 时按枚举解析出 POL 字节

## 关键决策

- 100 Hz 上限：用户要求。KA_RF_UNIT 限制 10 Hz 是因为 V2 还有 OTA 占用；KuR512B 无 OTA。
- CSV 而非 JSONL：用户偏好，便于 Excel/Numbers 直接打开
- 按日期+每 ID 分文件：避免单文件过大；与 customer traffic 50MiB 轮转策略一致
- raw_hex 每行都保存：便于事后比对协议字段
- 5 min 曲线窗口：用户要求默认；UI 提供 1/5/15 min 切换
- QtCharts 而非 pyqtgraph：PySide6 内置，无新增依赖

## 已知风险与缓解

- QtCharts 模块在某些精简版 PySide6 包中可能缺失 → 测试中 `pytest.importorskip("PySide6.QtCharts")`
- 100 Hz × 3 ID × 15 min 长稳内存：deque maxlen=18000 上限，溢出丢最早点
- macOS 100 Hz 落盘线程压力：StatusRecorder 队列 10000，丢帧时由 `lost` 字段报告
- 多 subarray 颜色碰撞：`Qt.GlobalColor` 仅 18 种，>18 时按 `color.name()` 哈希取稳定色

## 调试笔记

- `pdftotext -layout` 提取的 PDF 字段与正文表格一致；V3.1 坐标变更只在第 4 章图示中，无数字变化
- KuR512B 与 AFDR1024 帧头相同，**不能共用 stream.py**；否则会因为 en_row 位宽差异导致 `parse_response` 误判

## 完成总结（实施完成后回填）

- 主机单元/集成测试：`pytest -q` 通过
- 模拟器闭环：伪串口 1 对 1 设置/查询/CSV 落盘/曲线渲染通过
- 文档契约：测试通过
- Windows 原生 EXE：⏳ 待补
- 真实设备长稳：⏳ 待补
