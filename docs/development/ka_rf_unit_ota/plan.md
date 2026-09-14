> 历史草稿（2026-09-13 已被替代）：以下内容保留追溯，不作为当前实现或验收依据。
> 当前 V2 已取消 READY/COMMIT，使用空 BEGIN 与自动安装；见 ../ka_rf_unit_v2_sync/。
> 下文历史测试数量不代表 V2 验收通过，旧接线与超时描述不得用于联调。

# KA_RF_UNIT V0.3.0 客户 RS485 OTA 上传（上位机侧）

## 文档基础

* **设备侧受控原件**：`/Users/xmac/Documents/project_manager/1-softHz/3-project_dev/3-satlite_comm_terminal/code/target/ka_rf_unit/doc/customer_ota_20260911/{plan,acceptance,development}.md`
* **设备侧源参考**：`application/app/control/rf_unit_protocol.h/.c`、`application/app/topic_manage.h`、`common/ymodem_port/ymodem_port.h/.c`、`common/raw_fw/raw_fw.c`、`shared/MiddleWare/components/ymodem/ymodem.h/.c`、`shared/PublicLib/lib_check.c`
* **本计划状态**：DRAFT；待设备侧 V0.3.0 受控原件正式签发后校正命令字与结果码编号

## 1. 角色定义

上位机（`soft_hertz_tool`）= **客户设备 OTA 发起者**。与 AFDTR 客户流量（`devices/afdtr1024/traffic.py`）同位——复用 `devices/ka_rf_unit/protocol.py`/`stream.py`/`driver.py`/`SerialThread`，**不**仿真设备侧，**不**新增 console_script，**不**扩展 `run.sh`/`run.bat` 模式。

## 2. 协议契约（受设备侧 plan.md P2 冻结）

### 2.1 命令字

| 请求 | 响应 | 含义 |
|---|---|---|
| `0x21` BEGIN | `0xA1` | 开始上传 |
| `0x22` COMMIT | `0xA2` | 提交并复位 |
| `0x23` ABORT | `0xA3` | 取消 |
| `0x24` STATUS | `0xA4` | 查询状态 |

响应 = 请求 \| 0x80。**无 DATA 命令字**——YMODEM 字节流直接走裸 UART。

### 2.2 帧 payload

* BEGIN：`name_len:u8 + filename`（1..63 字节 ASCII 0x21..0x7E，禁 `/` `\`）
* COMMIT：`size:u32 BE + crc32:u32 BE + name_len:u8 + filename`（size 1..0xC0000=768 KiB）
* ABORT / STATUS：空 payload
* STATUS 响应（成功）：`result:u8 + phase:u8 + fw_major:u16 BE + fw_minor:u16 BE + fw_revision:u16 BE + app_boot_state:u8 + update_requested:u8 + candidate_present:u8 [+ size:u32 BE + crc32:u32 BE + name_len:u8 + filename 当 candidate_present==1]`
* STATUS 响应（失败）：仅 `result:u8`

多字节字段全部大端；filename 1..63 字节 ASCII，无线上 NUL。

### 2.3 结果码

| 值 | 含义 |
|---|---|
| `0x00` | OK |
| `0x01` | BAD_VERSION |
| `0x02` | BAD_LENGTH |
| `0x03` | OUT_OF_RANGE |
| `0x04` | UNSUPPORTED |
| `0x05` | PERSISTENCE_FAILED |
| `0x06` | **BUSY** |
| `0x07` | **INVALID_STATE** |
| `0x08` | **CANDIDATE_EXISTS** |
| `0x09` | **IMAGE_MISMATCH** |
| `0x0A` | **VERIFY_FAILED** |
| `0x0B` | **IO_FAILED** |
| `0x0C` | **UNAVAILABLE** |

### 2.4 物理层

460800 8N1，UART4 PD0/PD1 + PC3 DE（RS485 半双工）。上位机**不**直接驱动 DE，靠 USB-RS422 转换器自动方向控制；保守 `5ms` 后再尝试读响应。

## 3. 时序契约（受设备侧 plan.md 行 53-65 冻结）

### 3.1 严格顺序

`STATUS 探测 → BEGIN → 等 'C' → YMODEM(block0 → 数据块 → 双 EOT → 空 block0) → 最后 ACK → STATUS 确认 READY → COMMIT → 设备复位 → 多次 STATUS 直到 app_boot_state≠PENDING`

### 3.2 超时表

| 阶段 | 超时 | 重试 |
|---|---|---|
| BEGIN 响应 | 2s | — |
| 首包到达（'C'→block0 ACK） | 10s | — |
| 数据块响应 | 2s | 每块最多 10 次 |
| 无有效进展 | 10s | 重复包不续期 |
| 整次原始传输 | 120s | — |
| 最后 ACK 丢失 | 静默 200ms 后 STATUS | — |
| COMMIT 响应 | 10s | 失联后重连查询 |
| READY 独占 | 120s | 查询不续期 |

## 4. YMODEM 流程

* **起始字符**：仅 `'C' (0x43)`（**不使用裸 NAK 0x15**）
* **block0**：SOH(0x01) + 0x00 + 0xFF + `filename\0size\0[pad]` + CRC16_BE（128B payload）
* **数据块**：**优先 STX(0x02) + 块号 + ~块号 + 1024B 数据 + CRC16_BE**（共 1029B）；设备侧 `YMODEM_BLOCK_MAX=1024 / MIN=128` 动态识别；客户侧 STX 优先，SOH 回退
* **块号回绕**：`0x01..0xFF → 0x00`，回码 `0xFF - 块号`
* **结束**：数据块完成 → EOT(0x04) → 设备回 ACK → 第二个 EOT → ACK → 末尾空 block0 → ACK → 完成

## 5. CRC 双套（关键：不可混用）

| 用途 | poly | init | refin/refout | xorout | 函数 |
|---|---|---|---|---|---|
| OTA 协议帧 | 0x1021 | **0xFFFF** | false | 0x0000 | `protocol.crc16_ccitt_false` |
| YMODEM 块 | 0x1021 | **0x0000** | false | 0x0000 | `protocol.crc16_ccitt_ymodem` |
| COMMIT image | 0xEDB88320（反射） | 0 | true | 0 | `protocol.crc32_iso_hdlc` |

参考向量：`b"123456789"` →
- `crc16_ccitt_false → 0x29B1`
- `crc16_ccitt_ymodem → 0x31C3`
- `crc32_iso_hdlc → 0xCBF43926`

## 6. 模块拆分

### 6.1 上位机侧新增/修改

| 文件 | 角色 |
|---|---|
| `src/soft_hertz_tool/devices/ka_rf_unit/protocol.py` | OTA 常量/编解码/CRC（**修改**，不依赖 Qt） |
| `src/soft_hertz_tool/devices/ka_rf_unit/driver.py` | OTA 命令方法 + Qt 信号 + `start_ota/stop_ota`（**修改**） |
| `src/soft_hertz_tool/devices/ka_rf_unit/ota_traffic.py` | 纯状态机 + YMODEM-1K 发送端（**新增**，与 AFDTR `traffic.py` 同位；不依赖 Qt/serial） |
| `src/soft_hertz_tool/devices/ka_rf_unit/ota_panel.py` | UI 子组件（**新增**，与 AFDTR `traffic_panel.py` 同位） |
| `src/soft_hertz_tool/devices/ka_rf_unit/panel.py` | 第三个 OTA tab 接入（**修改**） |
| `src/soft_hertz_tool/devices/ka_rf_unit/__init__.py` | 导出 `OtaPanel` 等（**修改**） |
| `tests/devices/test_ka_rf_unit_ota_traffic.py` | 协议字节级 + 状态机 + Driver + Panel 单测（**新增**） |

### 6.2 不做

* 不仿真设备侧
* 不新增 console_script
* 不扩展 `run.sh`/`run.bat` 模式
* 不动 `stream.py` / `simulator.py`
* 不动 `protocol.py:199` 的 `crc16_ccitt_false`（init=0xFFFF 是协议帧层，与 YMODEM 区分）

## 7. 集成点

```
┌─────────────────────┐
│  panel.py           │
│  OtaPanel (3rd tab) │──ui events──┐
└─────────────────────┘             │
                                    ▼
                          ┌───────────────────┐
                          │  driver.py        │
                          │  start_ota()      │
                          │  stop_ota()       │
                          │  _ota_engine.poll │
                          └─────────┬─────────┘
                                    │ send_bytes / handle_bytes
                                    ▼
                          ┌───────────────────────┐
                          │  ota_traffic.py       │
                          │  OtaTrafficEngine     │── events
                          │  - state machine      │   → driver → emit signal
                          │  - YMODEM-1K sender   │   → panel
                          └───────────────────────┘
                                    ▲ │ on_response
                                    │
                          ┌───────────────┐
                          │  protocol.py  │
                          └───────────────┘
```

## 8. 真机回归步骤（待设备侧 P5 解锁后填写）

1. 准备 USB-RS422 转换器（如 FTDI USB-RS485-WE-1800-BTFTS）
2. 接线：转换器 A/B 接设备 UART4 PD0/PD1（注意 RS485 收发方向）
3. 启动 `python -m soft_hertz_tool`，选 KA_RF_UNIT 工作区，接 PTY2 / `/dev/cu.usbserial-XXX` / `COMn`
4. 切到"客户 OTA 升级" tab
5. 浏览 `.bin` 固件镜像（满足 1..63 字节 ASCII、以 `.bin` 结尾）
6. 点击"开始 BEGIN" → 观察进度 → 点击"提交 COMMIT"
7. 设备复位后 UI 应自动轮询 STATUS 直到 STABLE
8. 记录设备固件版本、串口参数（波特率/校验位/流控）、日志路径、截图到 `acceptance.md` B 段

## 9. 不在范围

* 不模拟设备侧（真机即被测设备）
* 不实现 YMODEM CRC16 拆分计算（每块一次到位）
* 不做固件签名验证（保持设备侧 `raw_fw_finalize` 头校验 + 全量 CRC32 单一来源）
* 不自动化真实设备测试（仍按设备侧 P5 解锁节奏）

## 10. 风险与边界

* **设备侧 plan 未完**：P1..P4 "实施中"，P5 实板 BLOCKED；上位机侧可先做协议+UI+单测，**真机回归等设备侧 P5 解锁**
* **DE 时序**：上位机不直接驱动 DE，靠转换器自动；保守 5ms 后读响应；实测时按设备侧 TC 波形调整
* **超时管理**：`poll(now)` 先校验 `state == expected_state`，避免已回 IDLE 后再次超时误报
* **READY 倒计时**：120s 是设备侧硬约束；上位机 UI 显示但不主动倒计时硬约束（按"查询不续期"语义）
