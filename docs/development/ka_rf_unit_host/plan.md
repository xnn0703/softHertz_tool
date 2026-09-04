# KA_RF_UNIT 上位机接入计划

## 背景

Ka 波段射频单元（KA_RF_UNIT）已发布《Ka 波段射频单元控制接口协议 V1》。
设备侧固件通过 RS422（默认 460800）以帧头 `50 53 41`（ASCII "PSA"）+ 大端
载荷 + CRC-16/CCITT-FALSE 提供 7 个控制命令和 1 个主动状态上报
（`0x30 STATUS_REPORT`，43 B payload / 51 B 完整帧）。

上位机当前覆盖 AFDTR（KaUDC004A / AFDT1024 / AFDR1024）与 AFD01_QS 工作区，
尚无对应 KA_RF_UNIT 的设备纵向切片和工作区。本计划在不破坏既有架构边界、
不引入 Qt/serial 依赖到协议/流层、不修改 AFD01_QS / AFDTR 既有行为的前提下，
新增 KA_RF_UNIT 设备切片、独立工作区和虚拟串口模拟器。

## 目标

- 新增 `src/soft_hertz_tool/devices/ka_rf_unit/` 设备纵向切片：
  - `protocol.py`：纯函数编解码；CRC、帧头、7 个控制命令构帧器、
    `STATUS_REPORT` 解码、范围校验、`describe` 监视摘要。
  - `stream.py`：可恢复分包、粘包和异常字节的增量分帧器。
  - `driver.py`：独占 `SerialThread` 的 Driver；不构造业务 UI。
  - `panel.py`：KA_RF_UNIT 单设备面板，含串口、7 个命令组、0x30 状态表、
    Driver 日志栏；连接代际与生命周期与现有 Panel 一致。
  - `simulator.py`：复用正式协议层，按 `report_hz` 主动发送 `0x30` 并对
    7 个控制命令应答结果码。
- 新增独立工作区 `workspaces/ka_rf_unit.py`，注册到 `app/registry.py` 的
  `WORKSPACE_SPECS`，与 AFDTR、AFD01_QS 平级。
- 新增 `soft-hertz-ka-rf-sim` CLI 入口，`run.sh` / `run.bat` 增加
  `ka-rf-sim` 模式与帮助。
- 新增/更新测试：
  - `tests/devices/test_ka_rf_unit.py`：协议正常向量（与协议文档 DEMO
    字节流对照）、范围校验、分包/粘包/异常字节恢复、`STATUS_REPORT`
    字段解码（含温度 int16/10、conv_lock_mask 位含义、波束 0–4095、
    极化 0/1）；Driver 在收到 0x30 后发布 `status_signal`；模拟器
    应答控制命令和 OUT_OF_RANGE 行为；Panel 连接代际、shutdown 幂等、
    closeEvent 在 stop 超时时 `ignore`。
  - `tests/integration/test_workspace_registry.py`：工作区数量与顺序更新。
  - `tests/integration/test_unix_launcher.py`：`ka-rf-sim` 入口分发。
- README 增补工作区、模拟器命令、TODO 行。
- `docs/development/ka_rf_unit_host/plan.md` + `acceptance.md` 同步落地。

## 非目标

- 不修改《Ka 波段射频单元控制接口协议》任何字段、命令号、CRC、状态帧长
  度、串口参数；docx 仅作为受控原件参考资料，不复制进仓库。
- 不实现真实 RS422/PLL/DSA/温补/物理 RF 验收。
- 不实现 KaTR003B_for_starwin 变频器或 KA256 V2 阵面控制的真实硬件回放；
  上位机只按协议编解码并展示状态。
- 不修改 AFDTR、AFD01_QS、KaUDC004A 既有行为；不动 Windows 打包与 CI。
- 不引入 TCP/UDP/广播通信；本工作区只支持串口。
- 不修改 PyInstaller 打包脚本、GitHub Actions 与发布脚本。

## 架构与依赖

```
app/registry -> workspaces/ka_rf_unit -> devices/ka_rf_unit.panel
                                       -> devices/ka_rf_unit.driver -> shared.transport.SerialThread
devices/ka_rf_unit.driver      -> devices/ka_rf_unit.protocol
                                -> devices/ka_rf_unit.stream
devices/ka_rf_unit.simulator   -> devices/ka_rf_unit.protocol
                                -> devices/ka_rf_unit.stream
```

- `protocol.py` 与 `stream.py` 不得 `import PySide6` 或 `import serial`，
  由 `tests/integration/test_dependency_boundaries.py` 静态校验。
- `devices/ka_rf_unit/` 不得导入 `soft_hertz_tool.workspaces` 或
  `soft_hertz_tool.app`。
- `MainWindow` 只读 `WORKSPACE_SPECS`，不硬编码具体设备特判。

## 并发与生命周期

- pyserial 仅由 `SerialThread` 打开、读写、关闭。
- `Panel` 通过 `_connection_generation` 闭包令牌过滤过期 Driver 信号。
- `disconnect_device()` 等待 `worker.stop()` 返回 True 后才清状态；
  超时时返回 False，主窗口据此取消工作区切换。
- Qt 控件仅在主线程更新；状态表用 100 ms QTimer 批量刷新（业务 UI ≤ 10 Hz）。
- 1 秒未收到 `0x30` 时 `0x30 上报频率` 标签转红色"超时"。
- `activate` / `deactivate` / `shutdown` / `closeEvent` 与现有 Panel
  保持相同语义，幂等且可重复调用。

## 协议实现要点

- 帧头 `50 53 41` + 协议版本 `0x01` + 命令字 + 载荷长度 + 载荷 + CRC-16/CCITT-FALSE。
- `0x10 SET_CONV_FREQ` payload 固定 10 B：4 个 2 B 频率 + 2 个 1 B 极化。
- LO 字段留空 → 编码 0 → 设备按文档 AUTO 表选 LO；手动值必须为偶数 MHz。
- `0x11 SET_CONV_ATT` 步进 0.5 dB（协议字段 ×10），范围 0–31.5 dB。
- `0x12 SET_TX_EN` 开启后 PA 自动跟随；TX 关闭时 PA 关闭；
  UI 不构造第二份硬件事实。
- `0x14 SET_BEAM` `target_mask` bit0=TX、bit1=RX，至少 1 位；波束码 0–4095。
- `0x15 SET_EXT_REF` 仅支持 10/100 MHz。
- `0x20 SET_REPORT_HZ` 0~200 Hz；0 表示关闭主动上报。
- `0x30 STATUS_REPORT` 43 B payload；`conv_lock_mask` 关键三位 bit0/bit1/bit2
  分别表示 REF_VALID / RX_LO_LOCK / TX_LO_LOCK。
- 温度字段为 `int16`，真实值 = 字段值 / 10，单位 °C。

## 风险

- 与协议文档 DEMO 帧逐字节对照是底线；任何构帧偏差都会破坏 RS422 联调。
- `STATUS_REPORT` 字段顺序和类型较多；格式串必须可被 `struct.calcsize`
  校验为 43，并保证解码字段顺序与 `STATUS_REPORT_FIELDS` 一一对应。
- Panel `_refresh_timer` 与 `SerialConnectionWidget._timer` 在
  activate/deactivate 之间需要严格对称启停，否则会出现隐藏页面仍在
  刷新或端口扫描继续运行的情况。
- 不同代际的旧 Driver 信号不能污染新连接 UI；测试必须覆盖替换 Driver
  时旧信号被忽略的场景。

## 2026-09-04 波束扫描修复范围

- 角度转 12 bit 码与 KA256 V2 固件统一：对有限相位执行半远离零舍入，再按 4096 取模；不在上位机以
  `±180°` 拒绝固件可编码的相位。
- 手动频点分别输入 TX 与 RX；扫描只计算 `target_mask` 实际选中的阵面，未选阵面的 0x14 字段填 0，
  由既有 target_mask 忽略。
- 自动频点仅接受未超过 `REPORT_TIMEOUT_S` 的 STATUS_REPORT 缓存，并分别验证 TX/RX RF 协议范围。
- 增加固件同源黄金点、负半码、超过 ±180° 的模回绕、手动双频、单阵面与过期状态回归；不修改 0x14
  wire 格式、串口行为或固件。

## 验收命令

1. `python -m compileall -q src tests packaging` 通过。
2. `QT_QPA_PLATFORM=offscreen python -m pytest -q` 全绿，含本计划新增
   的 20+ 用例。
3. `./run.sh app --smoke` 启动-关闭通过；下拉框可见 `AFDTR / AFD01_QS / KA_RF_UNIT`。
4. 虚拟串口对上跑 `soft-hertz-ka-rf-sim <PTY1> --baudrate 460800` +
   `SoftHertz Tool` 选 `KA_RF_UNIT` 接 `PTY2`：可发 7 个控制命令并
   在监视器看到 TX/RX/DROP，状态表 10 Hz 刷新且 1 秒超时显示红色。
5. `tests/integration/test_dependency_boundaries.py` 与
   `test_repository_layout.py` 仍 PASS。
