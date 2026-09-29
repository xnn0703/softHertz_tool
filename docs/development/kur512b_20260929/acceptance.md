# KuR512B 主动读取日志落盘 — 验收标准

## 1. 六类证据与状态

| 类别 | 描述 | 当前状态 |
| --- | --- | --- |
| 源码静态检查 | `python -m compileall -q src tests packaging` 通过 | ✅ 待跑 |
| 主机单元/集成测试 | `QT_QPA_PLATFORM=offscreen python -m pytest -q` 通过 | ✅ 待跑 |
| 模拟器闭环 | `soft-hertz-kur512-sim` + 上位机伪串口配置/查询/CSV/曲线 | ✅ 待跑（主机可执行） |
| macOS/Linux 源码运行 | `./run.sh app --smoke` 通过；可选真机 `-ku` 模式连模拟器 | ✅ 待跑 |
| Windows 原生 EXE 启动 | 干净 Windows 10 1809+/11 启动 EXE，连真实 RS485 | ⏳ 缺 Windows runner |
| 真实设备配置/查询/长稳 | 真实 KuR512B 板，460800 串口；100 Hz × 3 ID × 15 min 长稳 | ⏳ 缺硬件 |

## 2. 协议层断言

- `protocol.build_frame` 校验和正确，6+N 字节（含末尾 ADDR）
- `parse_response` 拒绝长度不匹配、坏校验、空数据区
- 构帧 0x90：FREQ 0/41 边界，POL 0/180/254/255 边界，BeamV/H 0/2047/2048/4095 边界
- 构帧 0x91：en_row 0x000/0xFFF → 完整帧含 0xFFF
- 构帧 0x97：PS_Align 0/63
- 构帧 0x20：使用公共 ID 0x00
- 状态响应：Rev/SysVcc/SysTemp/MCU_VER 解析正确（SysVcc ×0.1，SysTemp −80）。响应 LEN=4，载荷 4 字节无尾部 ADDR。

## 3. 流式拆帧

- 半帧：补齐后输出完整帧
- 粘包：两帧一次读入时拆为两帧
- 垃圾前缀：保留 P/PS 后缀
- 坏长度：仅前移 1 字节
- 坏校验：丢弃并继续解析
- 半个帧头：等待后续字节

## 4. Driver

- `set_query_hz(0)` 停止主动轮询；`set_query_hz(100)` 不报错
- round-robin：3 ID 列表发出顺序 1→2→3→1…
- 帧间隔 ≥3 ms：相邻发送时间戳差 ≥ 3 ms
- CSV 表头：`ts,device_id,rev,sys_vcc,sys_temp,mcu_ver,raw_hex`
- CSV 每行：`raw_hex` 与设备回包逐字节相等（大写无分隔符）
- 100 Hz 持续 1 s：CSV 行数 ≥ 80（容忍 ±20% 抖动）
- `stop()`：recorder 在 1 s 内关闭；文件无半行

## 5. 面板布局

- POL 控件（线极化 + LHCP/RHCP + 数值输入）可见
- 查询 Hz 输入上限 = 100
- 打开日志目录按钮可见
- 最近一行预览含 `raw_hex`
- 实时曲线窗口下拉 60/300/900 s
- 清空曲线按钮可见
- **不**再有"目标工作频率"输入框或最近频率列

## 6. 实时曲线

- 首次采样后 `_x_origin_ns` 锁定；后续 `rel_seconds = (t_ns - origin) / 1e9` 持续累积负值
- 1 个 subarray 累积 1000 点 → `refresh()` 后曲线渲染点数 = 1000
- 注入超过 `CHANNEL_BUFFER_CAPACITY` (30000) 后只保留最近 N 点（环形覆盖）
- 切窗口（1/5/15 min）：X 轴右边界按新窗口宽度重设，缓冲保留
- 停止主动读取：`reset()` 清空 buffer + 曲线 + X/Y 轴范围
- 100 Hz × 3 ID 持续运行：buffer 滚动 + pyqtgraph peak downsample + X 扩窗节流保证 UI ≤ 10 Hz

## 7. 模拟器

- 纯内核：`KUR512Simulator.handle_frame(0x9C)` 返回 4 字节状态
- `KUR512Simulator.handle_frame(0x90)` 记录 freq/beam/pol 状态
- 多 subarray 隔离：ID=1 写入不影响 ID=2 状态
- 串口模拟器：循环读串口、回响应、停止时关闭串口

## 8. 文档契约

- 新建模块均通过 `tests/integration/test_documentation_contract.py`
- README 工作区段、TODO、模拟器入口同步
- AGENTS.md 命名表与协议要点小节同步
- 协议受控原件 `docs/protocols/controlled-originals/` 可见
- 受控协议笔记 `docs/protocols/readable-notes/KuR512B_RX_Protocol.md` 完整

## 9. 待补证据

- Windows EXE 原生冒烟：等待 CI/专用 Windows 环境
- 真实 KuR512B 板：等待硬件到位后补充串口参数、波特率实测、100 Hz × N ID 长稳曲线
- 客户敏感数据审查：协议原件由客户提供，PDF 中如有客户标识需在 README 标注
