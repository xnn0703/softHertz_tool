> 历史草稿（2026-09-13 已被替代）：以下内容保留追溯，不作为当前实现或验收依据。
> 当前 V2 已取消 READY/COMMIT，使用空 BEGIN 与自动安装；见 ../ka_rf_unit_v2_sync/。
> 下文历史测试数量不代表 V2 验收通过，旧接线与超时描述不得用于联调。

# KA_RF_UNIT V0.3.0 OTA 客户控制器 — 上位机侧 acceptance

## A 段：上位机侧专属验收（A01..A07）

### A01 预校验
- 文件名满足 `^[A-Za-z0-9._-]+\.bin$`，长度 1..63 字节（由 `protocol._validate_ota_filename` 在 begin 时承担）
- 文件 size 1..0xC0000（768 KiB）
- CRC32 算法等价 `zlib.crc32`，参考向量 `b"123456789" → 0xCBF43926`

### A02 协议字节序
- BEGIN/COMMIT/ABORT/STATUS 请求帧命令字 0x21..0x24
- 响应 0xA1..0xA4 = 请求 | 0x80
- COMMIT payload 大端：`size:u32 + crc32:u32 + name_len:u8 + filename`
- STATUS 响应 payload 大端：`result:u8 + phase:u8 + fw_major/minor/revision:u16 + app_boot_state:u8 + update_requested:u8 + candidate_present:u8 [+ size:u32 + crc32:u32 + name_len:u8 + filename]`

### A03 CRC 双套独立
- OTA 协议帧 `crc16_ccitt_false`（init=0xFFFF）参考向量 `b"123456789" → 0x29B1`
- YMODEM 块 `crc16_ccitt_ymodem`（init=0x0000）参考向量 `b"123456789" → 0x31C3`
- 同数据两套 CRC 输出必须不同

### A04 超时表与设备侧一致
- BEGIN 响应 2s
- 'C' 到 block0 ACK 10s
- 数据块响应 2s，每块最多 10 次重试
- 无有效进展 10s
- 整次原始传输 120s
- COMMIT 响应 10s
- READY 独占 120s（上位机被动等，不主动倒计时硬约束）

### A05 状态机 9 阶段覆盖
- IDLE / WAITING_STATUS / WAITING_BEGIN_OK / YMODEM_TX_INIT / YMODEM_TX_BLOCKS / WAITING_READY_CONFIRM / READY / WAITING_COMMIT_OK / RESET_WAIT / IDLE_FAIL

### A06 7 个新 RESULT_* 全部识别并展示
- 0x06 BUSY / 0x07 INVALID_STATE / 0x08 CANDIDATE_EXISTS / 0x09 IMAGE_MISMATCH / 0x0A VERIFY_FAILED / 0x0B IO_FAILED / 0x0C UNAVAILABLE
- 每个 result 必须有明确中文提示语

### A07 UI 灰化按钮
- IDLE 全可用；WAITING_*/YMODEM_*/RESET_WAIT 全禁用；READY 仅 STATUS + COMMIT + ABORT
- deactivate/shutdown 必须停止 OTA 引擎与定时器

## B 段：与设备侧 acceptance.md 14 项对齐（BLOCKED）

| 设备侧条目 | 上位机侧状态 | 上位机侧验证方式 |
|---|---|---|
| 正常升级 | BLOCKED | 真机回归 |
| 输出保持 | 设备侧 | — |
| 通道纯净 | 设备侧 + 接线验证 | 真机回归 |
| 即时提交 | BLOCKED | 真机回归 |
| 丢响应 | 部分覆盖（A04 超时表） | 单测覆盖 + 真机回归 |
| 异常上传 | 部分覆盖（CAN 触发 IDLE_FAIL） | 单测覆盖 + 真机回归 |
| 校验 | A01 + A02 + protocol._validate_ota_filename | 单测覆盖 |
| 竞争 | 与 UART1 维护通道互斥（设备侧） | 真机回归 |
| 候选恢复 | A04 READY 独占 120s | 单测覆盖 + 真机回归 |
| 启动保留候选 | 设备侧 | — |
| 存储读取失败 | 设备侧 | — |
| 存储故障 | 设备侧 | — |
| 断电 | 设备侧 | — |
| 连续运行 | BLOCKED | 真机回归 |

### B.1 真机回归操作手册（待 P5 解锁）

1. 硬件：USB-RS422 转换器（如 FTDI USB-RS485-WE-1800-BTFTS）
2. 接线：转换器 A/B 接设备 UART4 PD0/PD1（注意 RS485 收发方向）
3. 波特率：460800 / 8N1 / 无流控
4. 路径：`python -m soft_hertz_tool` → 选 KA_RF_UNIT → 串口下拉 → OTA tab → 浏览 `.bin` → BEGIN → 观察 → COMMIT
5. 日志：`~/Documents/SoftHertz/SoftHertz_Tool/logs/ka_rf_unit_ota_<时间戳>.jsonl`
6. 记录：设备固件版本（升级前/后）、串口参数、日志路径、截图

## C 段：Windows EXE 验证（BLOCKED）

`python packaging\build_windows.py` 后 `dist\SoftHertz_Tool.exe` 启动 OTA tab——P0 BLOCKED（需 Windows 环境）

## D 段：open 项

* 设备侧 V0.3.0 plan P5 实板 BLOCKED → 真机回归暂未解锁
* 设备侧 V0.3.0 plan P5 软件验证 BLOCKED
* UART1 维护通道文档未发布 → 竞争场景验证待补
* DE 时序保守 5ms → 实测按设备侧 TC 波形调整
