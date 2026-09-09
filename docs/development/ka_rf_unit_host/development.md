# KA_RF_UNIT 上位机开发记录

## 2026-09-09 负温度解码修复（v3.1.5）

- 修正 STATUS_REPORT 大端格式串：payload 偏移 27/29/31 为 int16 温度（0.1°C），
  偏移 33/35/37/39 为 uint16 波束；载荷仍为 43 B，完整帧仍为 51 B。
- 以独立偏移向量复现旧实现两项失败，覆盖三路负温度、正负混合、零值、波束 0/1/2048/4095、
  UI 摄氏度格式化和模拟器构帧逐字节一致性；修复后全量 pytest 192 passed，compileall/diff 检查通过。
- 发布目标为 GitHub v3.1.5；Windows CI 构建/EXE 冒烟与 Release 资产以对应运行结果为准，
  真实设备负温度回读尚待实测。

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
