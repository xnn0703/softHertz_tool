# KuR512B 工作区与主动读取日志落盘 — 计划

## 1. 范围

新增一个独立 `KUR512` 工作区，面向 `KuR512B`（Ku 波段 512 单元接收子阵，无变频）。
页面设计参考 `AFDR1024`，新增**按用户配置频率主动读取 0x9C 状态查询**、**CSV 落盘**与**最近 5 min 实时温度/电压曲线**。

- 协议版本：KuR512B V3.1（受控原件 `docs/protocols/controlled-originals/KuR512B(无变频)控制接口协议_V3.1_20260511.pdf`）。
- 串口：460800 8N1 无流控。
- 不修改 AFDTR/AFD01/AFD01_QS/KA_RF_UNIT 任何既有代码；只在 `app/registry.py` 增加一条 `WorkspaceSpec`。

## 2. 非目标

- 不抽象 KuR512B 与 AFDR1024 共用基类（差异点已在 `docs/protocols/readable-notes/KuR512B_RX_Protocol.md` 第 7 节列出，独立模块更清晰）。
- 不导出曲线 PNG；曲线仅供页面查看，状态记录只导出 CSV。
- 不实现 TCP/UDP/双线 RS485 自动方向控制适配器识别；只按普通串口对待。
- 不修改 AFD01_QS 100 Hz 长稳验收条目；KuR512B 长稳仅在 acceptance.md 中标注"待 Windows 真机"。

## 3. 公开 API

- 工作区 key：`KUR512`
- 设备型号（UI/日志/文档）：`KuR512`
- 模拟器入口：`soft-hertz-kur512-sim`
- 一键脚本模式：`./run.sh kur512-sim <端口> --ids 1,2,3 --baudrate 460800`

## 4. 协议支持矩阵

| 命令 | ADDR | 说明 |
| --- | --- | --- |
| RX 波束设置（含 POL） | 0x90 | 10700..12750 MHz（步进 50），POL 0..180 / 254 / 255 |
| RX 阵列使能 | 0x91 | 12 bit en_row + 0xFFF |
| RX 整板相位校准 | 0x97 | PS_Align 0..63（步进 5.625°） |
| ID 更新 | 0x20 | 公共 ID=0x00 |
| 状态查询 | 0x9C | Rev/SysVcc(×0.1 V)/SysTemp(−80 ℃)/MCU_VER |

不实现极化独立指令与波束参数查询；面板极化通过 0x90 一起下发。

## 5. UI 分组

| 组 | 控件 |
| --- | --- |
| 串口设置 | 端口/波特率/连接按钮（沿用 `SerialConnectionWidget`） |
| 子阵设置 | 1/2 列布局生成 + 手工 ID + 目标 + `+0x80` 仅本子阵（与 AFDR1024 一致） |
| 波束设置 | 频率(MHz, 10700..12750 步进 50) + θ + φ + POL（线极化 0..180 / LHCP / RHCP） |
| 阵列 | 使能开关 |
| 相位校准 | PS_Align 0..63 |
| 状态 | 按 ID 显示 Rev / 电压 / 温度 / MCU_VER / 最近原始报文 |
| 主动读取 | 查询 Hz (0..100) + 启动/停止 + 当前实际频率 + 最近一行预览 + 打开日志目录 |
| 实时曲线 | 1/5/15 min 窗口切换 + 温度/电压双 Y 轴 + 清空曲线 |
| 日志 | 设备 Driver 日志只读文本（与 AFDR1024 一致） |

## 6. 主动轮询与 CSV

- 输入框：查询频率 0..100 Hz，默认 1 Hz
- 一轮遍历所有 ID；帧间隔 ≥3 ms（受控原件建议 ≥3 ms）
- 达到频率上限时按 ID 列表循环，**不补发漏掉的帧**
- CSV 路径：`Documents/SoftHertz/SoftHertz_Tool/logs/kur512/<device_id>/status-YYYY-MM-DD.csv`
- CSV 字段：`ts, device_id, rev, sys_vcc, sys_temp, mcu_ver, raw_hex`
- 50 MiB 单文件轮转，不自动删除历史
- `ts` 取本地时区 ISO8601 毫秒精度
- **不**写入目标工作频率：`0x9C` 响应不包含频点信息，UI 不再要求用户配置该字段

## 7. 实时曲线

- 技术栈：`pyqtgraph` `PlotWidget`（参考 `satellite_debug_tool.ui.GroupedChartWidget`）
- 缓冲：`ChannelBuffer` 预分配 `np.ndarray`（默认 capacity 30000 ≈ 5 min × 100 Hz），每通道 2 个（temp/volt）；append O(1)；`get_tail(n)` 返回 ndarray 副本
- 窗口：默认 300 s；可切 60 / 300 / 900 s；切换只重设 X 轴右边界，缓冲保留
- 刷新：≤10 Hz 重绘（与状态表共用 QTimer）；`refresh()` 拉 buffer → `setData(xs, ys)` 整批，不再逐点 append
- 下采样：pyqtgraph 内置 `setDownsampling(mode="peak", auto=True)` + `setClipToView(True)`
- X 扩窗节流：`_X_SCROLL_STEP_SEC=1.0`；只在最新数据超出右边界 1 s 才 `setXRange`，避免每帧重绘
- 稳定原点：首次采样确定 `_x_origin_ns`，后续 `(t - origin) / 1e9` 算相对秒数
- 抗锯齿：曲线 `antialias=False`（长路径 AA 极慢）
- 颜色：高区分度调色板；温度实线蓝、电压虚线橙

## 8. 验收（详见 acceptance.md）

1. 协议正常向量、边界值、流式拆帧
2. Driver 主动轮询 0..100 Hz 边界与 CSV 落盘
3. 面板布局与控件可见性
4. 实时曲线缓冲与下采样
5. 模拟器设置/回读闭环
6. 文档契约与工作区注册
7. 模拟器与上位机伪串口联调（可选）

## 9. 风险与不做的事

- Windows EXE 原生冒烟：依赖 Windows runner，本机不可达，验收中标记待补
- KuR512B 真实设备回归：暂无硬件，acceptance 中标记待补
- 100 Hz × N ID × 15 min 长稳：不在主机单元测试覆盖；需真机或 macOS 长时间运行记录到 acceptance.md
