> 历史草稿（2026-09-13 已被替代）：以下内容保留追溯，不作为当前实现或验收依据。
> 当前 V2 已取消 READY/COMMIT，使用空 BEGIN 与自动安装；见 ../ka_rf_unit_v2_sync/。
> 下文历史测试数量不代表 V2 验收通过，旧接线与超时描述不得用于联调。

# KA_RF_UNIT V0.3.0 OTA 客户控制器 — 上位机侧 development 日志

## 2026-09-12 初版交付（DRAFT）

### 协议依据

* 设备侧受控原件：`/Users/xmac/Documents/project_manager/1-softHz/3-project_dev/3-satlite_comm_terminal/code/target/ka_rf_unit/doc/customer_ota_20260911/{plan,acceptance,development}.md`
* 设备侧源：rf_unit_protocol.c:145-172（STATUS 响应布局）、ymodem.c:322-371（EOT 流程）、raw_fw.c:60-76（CRC32）、lib_check.c:5-27（CRC16 init=0x0000）
* 命令字 `0x21..0x24`、响应 `0xA1..0xA4` 与设备 `RF_UNIT_OTA_*` 宏一一对齐
* 7 个 RESULT_BUSY/INVALID_STATE/CANDIDATE_EXISTS/IMAGE_MISMATCH/VERIFY_FAILED/IO_FAILED/UNAVAILABLE 与设备 `topic_manage.h:30-45` 字面一致

### 实现细节

#### 协议层（`protocol.py`）

* 新增 OTA 命令字/响应/阶段/结果码常量
* 新增 `crc16_ccitt_ymodem(data)`：**不**复用现有 `crc16_ccitt_false`（init=0xFFFF）—— YMODEM init=0x0000 是**新函数**
* 新增 `crc32_iso_hdlc(data)`：等价 `zlib.crc32(data) & 0xFFFFFFFF`
* 新增 `encode_ota_begin/commit/abort/status` + `decode_ota_status_response` + `build_ota_*`
* `decode_payload` 增加 OTA 分支：`RES_OTA_STATUS → decode_ota_status_response`，其他 OTA 响应 → 单字节 result
* `CMD_NAMES` / `RESULT_NAMES` 注册 8 + 7 项
* `_validate_ota_filename`：1..63 字节、每个字节 0x21..0x7E、禁 `/` `\`、禁末尾 NUL

#### 状态机（`ota_traffic.py`）

* 9 阶段：`IDLE / WAITING_STATUS / WAITING_BEGIN_OK / YMODEM_TX_INIT / YMODEM_TX_BLOCKS / WAITING_READY_CONFIRM / READY / WAITING_COMMIT_OK / RESET_WAIT / IDLE_FAIL`
* YMODEM-1K 发送端支持 SOH 128B 与 STX 1024B 双包头；用 `_awaiting_block0_ack` / `_awaiting_end_block_ack` / `_awaiting_eot_ack` / `_eot_count` 四个标志区分 ACK 路径
* 块号回绕：`self._block_index = (self._block_index + 1) & 0xFF`
* 预校验：文件名正则 / size 1..768 KiB / CRC32 参考向量自检 / STATUS 必须已收到
* `poll(now)` 由 driver 在串口线程内周期调用，驱动超时；超时回调前先校验 `state == expected_state`

#### Driver（`driver.py`）

* 新增命令方法：`ota_begin/commit/abort/status`（走 `_queue_frame`）
* 新增 Qt 信号：`ota_status_signal` / `ota_event_signal` / `ota_progress_signal`
* 新增 `start_ota/stop_ota` 转交串口线程所有权（与 AFDTR `start_traffic` 完全对称）
* `handle_bytes` 在原 `result_signal` 分派前增加 OTA 响应分派（0xA1..0xA4 → 喂入 `_ota_engine.on_response`）
* OTA 引擎 TX 回调 `_ota_send_to_queue` 直接走 `send_bytes`（YMODEM 字节流不经协议帧）
* OTA 引擎事件回调 `_ota_dispatch_event` 把 `status_received` 路由到 `ota_status_signal`、`progress` 路由到 `ota_progress_signal`，其余进 `ota_event_signal` + 日志

#### Panel（`ota_panel.py` + `panel.py`）

* `OtaPanel` 新增第三个 tab "客户 OTA 升级"，与 AFDTR `TrafficPanel` 同位
* 文件选择 `QFileDialog.getOpenFileName`，后台校验文件名正则 + 文件存在 + size 边界
* 按钮灰化策略：IDLE 仅 STATUS + ABORT；WAITING_*/YMODEM_*/RESET_WAIT 全部禁用；READY 允许 STATUS + COMMIT + ABORT
* 设备 STATUS 响应 → 更新 phase / 版本 / boot_state / 候选
* YMODEM 进度 → `ota_progress_signal` → 进度条 + 百分比标签
* 结果码展示（7 个新 RESULT_* 必须有明确提示语）
* `_on_reset_clicked` 强制 `stop_ota()` 并回到 IDLE
* `_ready_countdown_timer` 每秒更新 READY 建议窗口（不主动倒计时硬约束）
* `shutdown()` 停止定时器 + `stop_ota()`，与 panel.deactivate 对称

### 软件验证命令

```bash
# 编译
.venv/bin/python -m compileall -q src tests packaging

# 跑测试
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/devices/test_ka_rf_unit_ota_traffic.py
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q  # 全套
```

实际结果：94 用例（含协议字节级 ~43 + 状态机 ~30 + Driver ~12 + Panel ~12）全过；全套 446 用例全过。

### Review 与开放项

* 设备侧 plan P5 实板 BLOCKED；真机回归待解锁
* 命令字与 RESULT_* 编号按设备侧 `topic_manage.h` 当前值实现，待 V0.3.0 受控原件正式签发后再校正
* DE 时序保守 5ms；实测时按设备侧 TC 波形调整
* 测试用 `_SpyDriver` 模式（与现有 `test_ka_rf_unit.py:269-364` 一致）覆盖 OTA 路径

### 不在范围（与设备侧 plan 一致）

* 半双工 DE 时序（上位机不直接驱动）
* YMODEM CRC16 拆分计算
* 固件签名验证
* 候选镜像一致性自动检查
* 真实设备自动化（仍按 P5 节奏）
