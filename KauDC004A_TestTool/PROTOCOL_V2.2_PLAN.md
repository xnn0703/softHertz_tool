# 协议 V2.2 适配：查询指令2（波束参数）合并到状态显示

> 依据：`DOC/…控制接口协议_V2.2_20260612.pdf`（TX/RX）。V2.2 相对 V2.1 仅**新增查询指令2**。

## V2.2 变化
- 新增「查询指令2：波束参数查询」。请求数据长度=1，ADDR：**TX=0x5F / RX=0x9F**。
- 返回数据长度=17（前 22 byte 求和）。数据区(去末尾指令号后 16 字节, D127~D0 big-endian)：

| D127~D65 | D64 | D63~D48 | D47~D32 | D31~D24 | D23~D12 | D11~D0 |
|---|---|---|---|---|---|---|
| Rev(无意义) | POL | EN_ROW[15:0] | 0xFFFF | FREQ[7:0] | BeamV[11:0] | BeamH[11:0] |

字节解析（payload[0]=Byte16 … payload[15]=Byte1）：
- `POL = payload[7] & 0x01`
- `EN_ROW = (payload[8]<<8)|payload[9]`（0xFFFF=开/0x0000=关）
- `FREQ = payload[12]` → 实际频率 TX=27500+50×FREQ / RX=17700+50×FREQ
- `BeamV = (payload[13]<<4)|(payload[14]>>4)`，`BeamH = ((payload[14]&0x0F)<<8)|payload[15]`

## 决策（已确认）
- 指向显示：**码值 + 反算角度都显示**（θ/φ 由 BeamV/BeamH + 频率反算）。
- 模拟器：**记录配置后回读**（记住每 ID 的波束/极化/使能，查询2返回）。

## 改动点
- `afdt1024_protocol.py`：新增 `ADDR_TX_BEAM_QUERY=0x5F`/`ADDR_RX_BEAM_QUERY=0x9F`、`BEAM_QUERY_RETURN_ADDRS`；`build_tx/rx_beam_query_frame`；`parse_beam_query_response(payload, is_tx)`；`beam_code_to_angle(beam_v, beam_h, freq, is_tx)`（码值→θ/φ）。
- `main_qt6.py`：`SerialWorker._process_frame` 识别 0x5F/0x9F → 解析并经 `status_signal` 上抛（带 device_id + 波束字段）；`_on_query_status` 每 ID 发查询1+查询2；状态表格扩列（极化/使能/频率/BeamV/BeamH/θ/φ），`_update_status_row` 改为按列名增量更新（查询1更新电压/温度/PA，查询2更新波束列）。
- `device_simulator.py`：维护 per-ID 状态，解析波束/使能/极化配置帧存储，查询2(0x5F/0x9F)返回。
- `test_serial_improved.py`：查询2帧构建/解析、码值↔角度往返、模拟器配置回读。
- `DOC/AFDT1024_TX_Protocol.md`/`AFDR1024_RX_Protocol.md`：更新到 V2.2。

## 验收标准
- [ ] `parse_beam_query_response` 对构造帧正确解出 POL/EN_ROW/FREQ/BeamV/BeamH。
- [ ] `beam_code_to_angle` 用协议示例反算：29500/BeamV712/BeamH712 → θ≈30,φ≈45；BeamH3384 → φ≈135。
- [ ] 查询全部 → 每 ID 两条查询，电压/温度与波束参数合并到同一行。
- [ ] 模拟器：先发波束/极化/使能配置，再查询2 → 回读到一致的值（配置回读闭环）。
- [ ] pytest 全绿；GUI 表格新列正常、横向可滚动；KaUDC 不受影响。
