# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **分支说明**：本文件针对 **`dev_kaudc004a`** 分支。该分支与 `master` 是**两套完全不同的代码**——`master` 是 `softHertz_upper/code/` 下的多设备插件式 PyQt5 工具，`dev_kaudc004a` 则是 `KauDC004A_TestTool/code/` 下重写的单文件 PySide6 工具。本文件只描述后者，切回 master 前需另行了解其结构。

## 项目简介

KauDC004A_TestTool（打包后名为 **SoftHertz_AFDTR_Tool**）：一个 PySide6 GUI 串口调试工具，主窗口里**三个设备面板并排**，各自独立连接串口、互不共享状态：

- **KaUDC004A**：Ka 波段上下变频器（本振/衰减/温度/版本）
- **Ka1024_TX**：AFDT1024 发射子阵（波束/阵列使能/推动 PA/极化/状态）
- **Ka1024_RX**：AFDR1024 接收子阵（波束/阵列使能/极化/状态，无 PA）

源码全部在 `KauDC004A_TestTool/code/`，是扁平模块（无包结构），必须在该目录下运行。

## 常用命令

> 一键运行（自动建 venv + 装依赖 + 启动）：在**仓库根目录**执行 `./run.sh`（Windows `run.bat`）；`--sim` 启动设备模拟器，`--update` 强制重装依赖。

```bash
cd KauDC004A_TestTool/code

# 运行上位机
python main_qt6.py

# 运行设备模拟器（用于无硬件时联调；默认 TX=COM10, RX=COM11，可传参覆盖）
python device_simulator.py [tx_port] [rx_port]

# 运行测试（pytest 用例）
pytest test_serial_improved.py
# 或：python -m pytest test_serial_improved.py -v
# 跑单个用例：pytest test_serial_improved.py::TestProtocolParsing::test_aa55_frame_build_and_parse

# 安装依赖
pip install -r ../requirements.txt   # PySide6>=6.5, pyserial>=3.5, PyInstaller>=5.13

# 打包为单文件 exe（产物：dist/SoftHertz_AFDTR_Tool.exe）
python build_spec.py
```

## 架构

整个程序约 2600 行，核心是三层：**UI 面板（主线程）↔ Qt 信号 ↔ 串口 Worker（QThread）↔ 协议模块（纯函数）**。

### `main_qt6.py`（全部 UI + 线程）
- **`MainWindow`**：把 `KaUDCPanel` / `TXPanel` / `RXPanel` 三个面板横排，关闭时逐个 `_disconnect()`。
- **`DevicePanel`**（基类）：封装串口设置区、端口下拉（2s 定时刷新）、连接/断开按钮。子类必须实现 `_setup_ui()` / `_do_connect()` / `_on_status()`。
- **三个面板子类**：每个面板创建自己的 Worker、连接信号、构建命令帧并 `worker.send_frame()`。TX 与 RX 面板结构高度相似但协议地址/状态解析不同。
- **两个 Worker 线程类**（近乎重复，刻意分开）：
  - **`SerialWorker`**：服务 TX/RX，解析 AFDT1024 协议（"PSA" 帧头）。`device_type` 为 `"TX"`/`"RX"`。
  - **`KaUDCWorker`**：服务 KaUDC004A，解析 0xAA55 定长帧。
  - 两者都用 `pyserial`（非 QSerialPort）在 `run()` 里轮询 `in_waiting` 读取，自带 `buffer` 做粘包拆帧，通过 `log_signal` / `status_signal` / `response_signal` 把结果发回 UI 线程。

> **为什么用 pyserial 而非 QSerialPort**：`SerialWorker` 注释明确说明 `QSerialPort` 在 `QThread` 中有线程亲和性问题，故改用 pyserial。注意 `DEV_LOG.md` / `plan.md` 里"迁移到 QtSerialPort"的描述是**过时计划**，与现状不符；`.sisyphus/plans/kau_testtool_analysis.md` 提到的 Tkinter 更是重写前的旧状态。**以源码为准**。

### `protocol.py`（KaUDC004A 协议，纯函数）
- 定长 **12 字节帧**：帧头 `AA 55 0C 00` + 6 字节 payload + 2 字节 **CRC16-CCITT**（poly `0x1021`，init `0xFFFF`，big-endian，覆盖 byte0~9）。
- 命令码常量：`0x0B` 版本、`0x0C` 温度、`0x0E`/`0x12` 收/发本振、`0x13` 本振查询、`0x14`/`0x15` 收发衰减、`0x16` 衰减查询。
- 衰减范围 0~300（值/10 = dB）。

### `afdt1024_protocol.py`（AFDT1024/AFDR1024 协议 **V2.2**，纯函数）
- **变长帧**：帧头 `"PSA"`(`50 53 41`) + device_id(1) + length(1) + payload + addr(1) + **求和校验**(`sum & 0xFF`，**不是 CRC**；除 CheckSum 外全字段求和)。
- **V2.1：所有返回帧末尾都是指令号(ADDR)**。`parse_response(frame)` 返回 `{device_id, addr, payload}`，统一取末尾字节为 addr：`addr ∈ CONFIG_ECHO_ADDRS` → 配置 echo；`addr==0x5C` → TX 状态返回；`addr==0x9C` → RX 状态返回（见 `STATUS_RETURN_ADDRS`）。查询返回数据长度 TX=7 / RX=6（V2.1 在末尾**新增了指令号字节**）。
- 配置命令地址：TX `0x50/0x51/0x53/0x56/0x57`、RX `0x90/0x91/0x93/0x97`、ID更新 `0x20`。
- **查询指令**：查询1(状态) `0x5C`(TX)/`0x9C`(RX) 返回电压/温度/PA；**V2.2 查询2(波束参数)** `0x5F`(TX)/`0x9F`(RX) 返回 POL/EN_ROW/FREQ/BeamV/BeamH（`parse_beam_query_response`，返回帧由 `BEAM_QUERY_RETURN_ADDRS` 标识）。
- 波束帧内布局 `FREQ | BeamV[11:0] | BeamH[11:0]`；`build_*_beam_frame` 参数顺序**已统一**为 `(device_id, freq, beam_h, beam_v)`。
- `calculate_beam_values(theta, phi, freq, is_tx)` → `(beam_h, beam_v)`：`AngleToCode_12bit(180×f/f0×sinθ×cosφ 或 sinφ)`，`round(ang×2048/180)`、负数 +4096、mod 4096；f0 TX=30000 / RX=20270 MHz。**freq 必须用量化到 50MHz 步进的实际频率**(`27500/17700 + 50×freq_num`)，否则设置↔回读角度有系统偏差（`_on_set_beam` 已处理）。`beam_code_to_angle` 为其反算（码值→θ/φ，UI 现仅显示 BeamV/BeamH 码值）。
- **不兼容旧协议**（含历史 RX 校验和 bug，已移除）。

### `device_simulator.py`（TX/RX 设备模拟器，支持多子阵）
独立脚本，TX/RX 各监听一个串口。每个模拟器持有一组子阵 ID（`ids=`，默认 `main()` 里 `[1,2,3]`）：按收到帧的目标 ID 路由——`ID=0` 广播不返回；`目标&0x7F ∈ ids` 才回复；状态电压/温度随 ID 变化以便验证多行。配置命令回 echo，状态查询回 V2.1 状态帧（正常校验和）。

## 关键约定与陷阱

- **三面板完全独立**：没有共享的串口/状态管理器，每个面板一个 Worker、一个串口连接。新增设备就是再写一个 `DevicePanel` 子类 + 一个 Worker + 在 `MainWindow` 里 `addWidget`。
- **两套协议、两种校验**：KaUDC004A = CRC16-CCITT（big-endian）；AFDT1024 = 字节求和。改协议时别用错校验算法。
- **AFDT1024 V2.1 一律以末尾指令号(ADDR)分派**：`SerialWorker._process_frame` 按 `parse_response` 返回的 `addr` 分流——`0x5C→parse_status_response`(TX)、`0x9C→parse_rx_status_response`(RX)、其余已知 ADDR→配置 echo。状态 `status_info` 会带上 `device_id` 上抛，供多子阵按 ID 路由到表格行。
- **（历史）RX 校验和 bug 已在 V2.1 移除**：旧 RX 设备算校验和漏 mcu_ver 字节，曾用 `has_rx_status_bug` 兼容；V2.1 明确全字段求和，已删除该兼容逻辑，模拟器也改为正常校验和。
- **多子阵（TX/RX 一条总线挂多个子阵，ID 区分）**：`DevicePanel` 基类提供子阵管理——`_parse_id_list()` 解析 ID 列表；`_get_target_device_id()` 按「目标下拉(全部=广播 ID=0 / 指定 ID)」+「仅本子阵(+128)」算配置 device_id；状态用按 ID 一行的表格，`_update_status_row()` 按回复帧 `device_id & 0x7F` 路由；`_on_query_status()` 对每个 ID 发查询1(状态)+查询2(波束参数)，`_update_status_row` 按列名增量合并到同一行。`_gen_subarray_ids(cols, n)` 按协议拼接编号（左列 `0x01~0x0N`、右列 `0x11~0x1N`）一键生成 ID。三种 ID 模式：`0`=广播不返回 / 实际ID=对应返回 / `+128`=仅对应返回。
- **波束 12bit 打包**：帧内 `FREQ | BeamV[11:0] | BeamH[11:0]`（BeamV 高位、BeamH 低位）。`build_*_beam_frame` 参数顺序已统一 `(device_id, freq, beam_h, beam_v)`。
- **温度解码当前返回原始字节**：`protocol.py` 的 `decode_temperature` 和 `main_qt6.py` 里 0x0C 分支的"`0x80`=0°C 偏移"逻辑都被**注释掉了**（最近提交 `feat: 更新协议文档和温度解码逻辑` 有意为之）。改温度显示前先确认这是否仍是预期。
- **状态字段换算**：AFDT1024 状态里 `sys_vcc = 原值 × 0.1` V，`sys_temp = 原值 − 80` ℃。
- **UI 卡顿历史问题**：早期"快速点按钮 → 多帧回复 → `log_signal.emit` 泛滥 → UI 冻结"，详见 `UI_FREEZE_ANALYSIS.md`。新增高频日志/信号时注意别重蹈覆辙。

## 文档地图

- `DOC/AFDT1024_TX_Protocol.md`、`DOC/AFDR1024_RX_Protocol.md`：TX/RX 协议规范（**已更新到 V2.2**），对应 PDF 原件 `…控制接口协议_V2.2_20260612.pdf`。改协议代码时的权威依据。
- `KauDC004A_TestTool/PROTOCOL_V2.1_MIGRATION_PLAN.md`、`PROTOCOL_V2.2_PLAN.md`、`MULTI_SUBARRAY_PLAN.md`：各轮协议适配与多子阵改造的计划/验收。
- `KauDC004A_TestTool/DEV_LOG.md`、`plan.md`、`PROTOCOL_FIX_PLAN.md`、`UI_FREEZE_ANALYSIS.md`：开发日志与历次修复方案。**注意其中关于 QtSerialPort/Tkinter 的描述已过时**，仅作历史参考。
- `DOC/上位调试软件需求.txt`、`DOC/修改记录.txt`：需求与版本变更记录。
