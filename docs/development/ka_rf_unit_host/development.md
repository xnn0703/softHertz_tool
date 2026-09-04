# KA_RF_UNIT 上位机开发记录

## 2026-09-04 波束扫描角度合同修复

- 上位机 `angle_u_to_code()` 统一为 KA256 V2 firmware 的“半远离零舍入后 modulo 4096”规则。
  上位机不再以 `±180°` 拒绝固件可编码的相位。
- 手动扫描频点拆分为独立 TX/RX 输入；0x14 未被 target_mask 选择的阵面字段固定为 0，且不参与角度计算。
- 自动频点只消费 1 秒内的 STATUS_REPORT；TX/RX 分别按协议频率范围校验。
- 新增固件黄金点、负半码、相位回绕、TX-only 与 STATUS_REPORT 超时回归。`pytest` 与
  `compileall` 为软件证据；RS422、阵面应用和 RF 指向仍需实物验收。

## 2026-09-04 KA_RF_UNIT 面板单屏布局整理

- 去除与顶部设备型号下拉重复的 `KA_RF_UNIT` 标题行；串口栏保持独占一行。
- 频点与极化、波束配置保持两列；把 0x11、0x12、0x13、0x15、0x20 合并为三行常用控制区，字段、输入
  和发送按钮逐列对齐。扫描区继续使用 θ、φ 各一行的六列网格，频点来源、手动 TX/RX 和控制状态不换行。
- 0x30 状态表改为字段/值 × 3：23 个字段按列优先填入 8 行，固定表头和行高并禁用表内滚动条；日志改为
  紧凑单行高度，避免挤占控制和状态可见区域。
- 软件核查：`.venv/bin/python -m compileall -q src tests packaging` 通过；
  `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/devices/test_ka_rf_unit.py` 为 `40 passed`；
  `QT_QPA_PLATFORM=offscreen .venv/bin/python -m soft_hertz_tool --smoke` 退出成功。离屏主窗口在 1920×1080
  及 1470×956 下检查，命令、扫描和 0x30 字段均无需滚动即可见。
