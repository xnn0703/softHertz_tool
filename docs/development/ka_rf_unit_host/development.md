# KA_RF_UNIT 上位机开发记录

## 2026-09-04 波束扫描角度合同修复

- 上位机 `angle_u_to_code()` 统一为 KA256 V2 firmware 的“半远离零舍入后 modulo 4096”规则。
  上位机不再以 `±180°` 拒绝固件可编码的相位。
- 手动扫描频点拆分为独立 TX/RX 输入；0x14 未被 target_mask 选择的阵面字段固定为 0，且不参与角度计算。
- 自动频点只消费 1 秒内的 STATUS_REPORT；TX/RX 分别按协议频率范围校验。
- 新增固件黄金点、负半码、相位回绕、TX-only 与 STATUS_REPORT 超时回归。`pytest` 与
  `compileall` 为软件证据；RS422、阵面应用和 RF 指向仍需实物验收。
