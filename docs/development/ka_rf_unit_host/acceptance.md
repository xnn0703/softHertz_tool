# KA_RF_UNIT 上位机接入验收

## A. 设备切片与构建产物

- [x] 新增 `src/soft_hertz_tool/devices/ka_rf_unit/`：`protocol.py`、
      `stream.py`、`driver.py`、`panel.py`、`simulator.py`、`__init__.py`。
- [x] `protocol.py` 仅依赖 `struct` / `dataclasses` / `typing`，不导入
      `PySide6` 或 `serial`；`stream.py` 同样保持纯逻辑。
- [x] `pyproject.toml` 新增 `soft-hertz-ka-rf-sim` 脚本入口。
- [x] `run.sh` 与 `run.bat` 增加 `ka-rf-sim` 模式与帮助。

## B. 协议编解码

- [x] `crc16_ccitt_false("123456789") == 0x29B1`，与文档参考向量一致。
- [x] 7 个控制命令构帧结果与协议文档 DEMO 字节流逐字节一致：
      `0x10/0x11/0x12/0x13/0x14/0x15/0x20`。
- [x] `parse_response` 拒绝坏 magic、坏协议版本、坏长度、坏 CRC；
      合法帧返回 `decoded` 字典与 `"OK"`。
- [x] `STATUS_REPORT` payload 固定 43 B；`struct.calcsize` 与字段顺序匹配。
- [x] `conv_lock_mask` 仅展示三位：`ref_valid` / `rx_lo_lock` / `tx_lo_lock`。
- [x] 范围校验覆盖 `rx_rf_valid` / `tx_rf_valid` / `rx_lo_valid` /
      `tx_lo_valid` / `conv_att_valid` / `ext_ref_valid`。

## C. 流解析与 Driver

- [x] `FrameStreamParser` 支持分包、粘包、异常字节恢复、坏长度回退。
- [x] `KaRfUnitDriver` 在串口线程内完成拆帧；TX/DROP 走 `FrameRecord`；
      `0x30` 发布 `status_signal`，控制响应发布 `result_signal`。
- [x] `Driver.stop()` 确认线程退出后清空 `FrameStreamParser` 缓冲与
      上报频率统计。
- [x] Driver 不导入 Qt 控件；Panel 仍通过 `_connection_generation` 闭包
      令牌过滤过期信号。

## D. 工作区与 UI

- [x] `workspaces/ka_rf_unit.py` 实现 `KaRfUnitWorkspace(Workspace)`，
      在 `app/registry.py` 注册 `WorkspaceSpec("KA_RF_UNIT", ...)`。
- [x] 下拉框展示顺序：`AFDTR` → `AFD01_QS` → `KA_RF_UNIT`。
- [x] Panel 包含 7 个命令组、状态表（22 行）、日志栏；`activate` /
      `deactivate` / `shutdown` / `closeEvent` 与现有 Panel 一致。
- [x] `0x30 上报频率` 标签在 1 秒内无 STATUS_REPORT 时转红色"超时"；
      95–105 Hz 显绿色，其它频率显橙色。
- [x] `shutdown()` 可重复调用且返回 True；`closeEvent` 在 stop 超时时
      `event.ignore()`。

## E. 模拟器

- [x] `soft-hertz-ka-rf-sim` 默认 460800，可配 921600 与 `--report-hz`。
- [x] 对 7 个控制命令按协议返回结果码；非法值返回 `OUT_OF_RANGE`。
- [x] `report_hz=0` 时不发 `0x30`；`report_hz>0` 时按目标周期发送，
      抖动后跳过已错过的截止时间，不突发补帧。

## F. 软件验证

- [x] `python -m compileall -q src tests packaging` 通过。
- [x] `QT_QPA_PLATFORM=offscreen python -m pytest -q` 全绿；新增
      `tests/devices/test_ka_rf_unit.py` 含 20+ 用例，覆盖协议正常
      向量、范围校验、流解析恢复、Driver 信号分发、模拟器应答、
      Panel 生命周期与代际过滤。
- [x] `tests/integration/test_dependency_boundaries.py` PASS：新增设备
      切片未违反 `shared`/`devices`/`workspaces`/`app` 单向依赖。
- [x] `tests/integration/test_repository_layout.py` PASS：未引入生成物。
- [x] **波束扫描**：θ/φ 起止、步进、间隔与频点源配置完整；12 bit 补码换算（`u*2048/180`）覆盖 0/90/180/-180 边界；扫描 IDLE/RUNNING/PAUSED/FINISHED 状态机在隐藏/关闭页面时强制停 timer；未连接 Driver 的拍会被跳过并累计错误。
- [x] **波束扫描修复**：上位机编码与 KA256 V2 `lroundf + mod 4096` 合同一致；手动 TX/RX 双频、单阵面
      扫描和过期 STATUS_REPORT 均 fail-closed；固件黄金点和边界回归通过。

## G. 文档

- [x] README 增加 `KA_RF_UNIT` 工作区段、模拟器命令、TODO 行。
- [x] 本目录 `plan.md` + `acceptance.md` 已落地。
- [x] 协议原文 docx 不进仓库；本目录保留文档要点供后续 reviewer。

## H. 验收边界（本轮 BLOCKED 项）

- [ ] RS422 链路实测、460800/921600 真实设备回归；需要真实设备、
      逻辑分析仪与 RF 仪表。
- [ ] 0x30 在真实设备 200 Hz 上报下的长稳测试与丢帧率统计。
- [ ] 真实设备 conv_lock_mask 三位与温度换算验证。

完成以上 P0/P1 之后，本计划方可由 `BLOCKED` 升级为 `PASS`。
