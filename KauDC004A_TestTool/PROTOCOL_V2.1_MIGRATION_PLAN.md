# AFDT1024 / AFDR1024 协议 V2.1 适配计划

> 依据文档：
> - `DOC/Ka波段1024单元发射子阵（无变频）控制接口协议_V2.1_20260317.pdf`（TX / AFDT1024）
> - `DOC/Ka波段1024单元接收子阵（无变频）控制接口协议_V2.1_20260317.pdf`（RX / AFDR1024）
>
> 约束：**不兼容旧协议**（V1 / V2 / 旧设备 bug 行为一律移除）。

---

## 1. 背景与目标

新版 V2.1 协议对 TX/RX 子阵的**查询返回帧**做了变更，并明确了波束计算公式与校验范围。本次任务把上位机（`main_qt6.py`）、协议模块（`afdt1024_protocol.py`）、设备模拟器（`device_simulator.py`）和测试（`test_serial_improved.py`）全部对齐到 V2.1，移除所有旧协议兼容代码。

> 注：本次**不涉及** KaUDC004A（`protocol.py`），它是独立的变频器协议，未变更。

---

## 2. V2.1 协议关键点（TX 与 RX 共性 + 差异）

### 2.1 帧格式（不变）
```
帧头(0x50 0x53 0x41) + ID(1) + 数据包长度(1) + N字节数据 + CheckSum(1)
```
- **CheckSum = 除 CheckSum 外所有字节求和的低 8 位**（全字段求和，无任何例外分支）。
- ID 规则：`ID=0` 全阵列响应不返回；`ID=实际ID` 全阵列响应且对应 ID 返回；`ID=实际ID+128` 仅对应 ID 响应并返回。

### 2.2 配置指令（5 条，收到后按 ID 原封返回）
| 指令 | TX ADDR | RX ADDR | 数据包长度 | 数据布局（含 ADDR 字节） |
|---|---|---|---|---|
| 波束设置 | 0x50 | 0x90 | 5 | `FREQ[7:0]` `BeamV[11:0]` `BeamH[11:0]` `ADDR` |
| 阵列使能 | 0x51 | 0x91 | 5 | `EN_ROW[15:0]` `0xFFFF` `ADDR` |
| 极化设置 | 0x53 | 0x93 | 5 | `reserved` `POL[1bit]` `ADDR` |
| 推动PA使能 | 0x56 | —（RX无） | 5 | `reserved` `PA_EN[1bit]` `ADDR` |
| 整板相位校准 | 0x57 | 0x97 | 5 | `reserved` `PS_Align[6bit]` `ADDR` |
| ID 号更新 | 0x20 | 0x20 | 3 | `reserved` `ID_new[7:0]` `ADDR`（用公共 ID 0x00 配置）|

- FREQ：0~70。TX 实际频率 = 27500 + 50×FREQ（27500~31000 MHz）；RX = 17700 + 50×FREQ（17700~21200 MHz）。
- POL：0=LHCP，1=RHCP。PA_EN：0=关，1=开（TX 专有）。PS_Align：0~63，步进 5.625°。

### 2.3 查询指令与返回（**本次核心变更**）
- 查询请求：数据包长度=1，数据=`ADDR`（TX=0x5C，RX=0x9C）。
- **查询返回（V2.1 末尾新增"指令号"字节）**：

**TX 返回**（数据包长度 = **7**，前 12 字节求和）：
| Byte6 | Byte5 | Byte4 | Byte3 | Byte2 | Byte1 | Byte0 |
|---|---|---|---|---|---|---|
| Rev(无意义) | STATE | SysVcc | SysTemp | ATT_Tc | MCU_VER | **0x5C(指令号)** |

**RX 返回**（数据包长度 = **6**，前 11 字节求和，**无 STATE 字段**）：
| Byte5 | Byte4 | Byte3 | Byte2 | Byte1 | Byte0 |
|---|---|---|---|---|---|
| Rev(无意义) | SysVcc | SysTemp | ATT_Tc | MCU_VER | **0x9C(指令号)** |

- `SysVcc` 实际电压 = 值 × 0.1 V；`SysTemp` 实际温度 = 值 − 80 ℃。
- `STATE`：B0 = PA_EN（推动 PA 使能状态），其余位保留（仅 TX）。
- `ATT_Tc`：BF 温补衰减值（仅查询用）；`MCU_VER`：系统版本号。

### 2.4 波束值计算（V2.1 明确公式，与现有实现**不一致**，需改）
```
Ux = 180 × (f / f0) × sinθ × cosφ        # θ 离轴角(俯仰), φ 方位角, 单位度
Uy = 180 × (f / f0) × sinθ × sinφ
BeamH = AngleToCode_12bit(Ux)
BeamV = AngleToCode_12bit(Uy)

AngleToCode_12bit(ang):
    if ang >= 0:  code = round(ang × 2048 / 180)
    else:         code = round(ang × 2048 / 180 + 4096)
    return code mod 4096          # round 取四舍五入(远离零)
```
- 参考频率 f0：**TX=30000 MHz，RX=20270 MHz**。
- 帧内布局统一为 `FREQ | BeamV[11:0] | BeamH[11:0]`（BeamV 在高位 D23~D12，BeamH 在低位 D11~D0）。

---

## 3. 现状差异分析（要改什么）

### 3.1 `afdt1024_protocol.py`
| 项 | 现状（旧） | 改为（V2.1） |
|---|---|---|
| `parse_response(frame, has_rx_status_bug=False)` | 带 RX 校验和 bug 兼容分支；用"末尾是否已知 addr"区分 echo/状态 | **删除 bug 参数**；统一全字段求和；末尾字节一律视为"指令号/ADDR"返回 |
| 状态/echo 判别 | 状态帧 `addr=None` | 引入指令号常量：`0x5C→TX状态`、`0x9C→RX状态`，其余已知 ADDR→配置 echo |
| `angle_to_beam()` | `int(ang/(360/4095))`，负数+360，截断 | 改为 `AngleToCode_12bit`：`round(ang×2048/180)`，负数+4096，mod 4096 |
| 波束位打包 `build_tx/rx_beam_command` | BeamV 低 4 位丢失（打包 bug） | 修正为完整 12bit `FREQ|BeamV[11:0]|BeamH[11:0]` |
| `build_rx_beam_frame(id, freq, beam_v, beam_h)` | 参数顺序与 TX 相反（历史混乱） | 统一为 `(id, freq, beam_h, beam_v)`，与 TX 一致 |
| `parse_status_response` (TX) | 输入 6 字节 `[Rev,STATE,Vcc,Temp,ATT,MCU]` | 输入仍是去掉指令号后的 6 字节，**字段顺序不变**，逻辑基本保留 |
| `parse_rx_status_response` (RX) | 输入 5 字节 `[Rev,Vcc,Temp,ATT,MCU]` | 同上，去掉指令号后 5 字节，顺序不变 |

> 关键设计：解析时把**末尾指令号当作 ADDR 取出**（`payload = data[:-1]`），于是状态数据的字段排布与旧版一致，`parse_status_response`/`parse_rx_status_response` 内部几乎不动；变化集中在 `parse_response` 的分派与新的指令号常量。

### 3.2 `main_qt6.py`（`SerialWorker._process_frame`）
- 删除 `has_rx_status_bug=True` 的二次重试逻辑。
- 分派改为按指令号：`addr==0x5C`→`parse_status_response`（TX）；`addr==0x9C`→`parse_rx_status_response`（RX）；`addr∈配置ADDR`→显示"✓ xx配置成功"。
- TX/RX 波束设置调用统一：`build_tx_beam_frame(id, freq_num, beam_h, beam_v)` 与 `build_rx_beam_frame(id, freq_num, beam_h, beam_v)`（消除现有 RX 的 `beam_v, beam_h` 反序传参）。
- `calculate_beam_values` 接口不变（返回 `(beam_h, beam_v)`），内部换新算法。

### 3.3 `device_simulator.py`
- TX 状态返回：payload 改为 7 字节 `[Rev,STATE,Vcc,Temp,ATT,MCU,0x5C]`，长度=7，**正常全字段校验和**。
- RX 状态返回：payload 改为 6 字节 `[Rev,Vcc,Temp,ATT,MCU,0x9C]`，长度=6，**删除 `build_rx_status_response_with_bug`，改正常校验和**。

### 3.4 `test_serial_improved.py`
- 更新 `test_status_response_parsing` / `test_rx_status_response_parsing` 注释与（如需要）输入，保证与新字段排布一致。
- 移除任何依赖旧 RX 校验和 bug 的断言。
- **新增**：完整查询帧端到端解析测试（TX length=7/末尾0x5C、RX length=6/末尾0x9C、正常校验和）。
- **新增**：波束计算回归测试，用协议示例表逐行校验（见验收标准 §4.2）。

---

## 4. 验收标准

### 4.1 帧构建/解析
- [ ] TX 波束帧：`build_tx_beam_frame` 产出帧头 `50 53 41`、ID 正确、数据包长度=5、末尾 ADDR=0x50、CheckSum 为前 10 字节求和。
- [ ] RX 波束帧同上，ADDR=0x90。
- [ ] `parse_response` 对完整 TX 查询返回帧（length=7，末尾 0x5C，正常校验和）返回 `addr=0x5C` 且校验通过。
- [ ] `parse_response` 对完整 RX 查询返回帧（length=6，末尾 0x9C，正常校验和）返回 `addr=0x9C` 且校验通过。
- [ ] 校验和错误、长度不匹配、错误帧头均返回对应错误信息，不抛异常。

### 4.2 波束计算（必须与协议示例表逐行一致）
**TX（f0=30000）**：
| Freq | θ | φ | 期望 BeamV | 期望 BeamH |
|---|---|---|---|---|
| 29500 | 0 | 0 | 0 | 0 |
| 29500 | 30 | 0 | 0 | 1007 |
| 29500 | 30 | 45 | 712 | 712 |
| 29500 | 30 | 90 | 1007 | 0 |
| 29500 | 30 | 135 | 712 | 3384 |
| 29500 | 30 | 225 | 3384 | 3384 |
| 29500 | 30 | 315 | 3384 | 712 |
| 30000 | 30 | 45 | 724 | 724 |

**RX（f0=20270）**：
| Freq | θ | φ | 期望 BeamV | 期望 BeamH |
|---|---|---|---|---|
| 19450 | 0 | 0 | 0 | 0 |
| 19450 | 30 | 0 | 0 | 983 |
| 19450 | 30 | 45 | 695 | 695 |
| 19450 | 30 | 90 | 983 | 0 |
| 19450 | 30 | 135 | 695 | 3401 |
| 19450 | 30 | 225 | 3401 | 3401 |
| 19450 | 30 | 315 | 3401 | 695 |
| 20000 | 30 | 45 | 714 | 714 |

- [ ] 上述全部行计算结果完全匹配。

### 4.3 状态解析
- [ ] TX：`SysVcc=0x77(119)` → 11.9 V，`SysTemp=0x77(119)` → 39 ℃，`STATE.B0` → PA_EN。
- [ ] RX：同样的 Vcc/Temp 换算正确，无 STATE 字段不报错。

### 4.4 端到端（模拟器联调）
- [ ] `python device_simulator.py` 后，上位机 TX/RX 面板"查询状态"能正确显示电压/温度（不再出现旧 bug 导致的解析失败或 -80℃ 异常）。
- [ ] TX/RX 各配置指令发送后，日志显示"✓ xx配置成功"（echo 正确识别）。
- [ ] `pytest test_serial_improved.py` 全绿。

### 4.5 回归
- [ ] KaUDC004A 面板功能不受影响（`protocol.py` 未改）。
- [ ] GUI 正常启动（`./run.sh`）。

---

## 5. 决策点（已确认）

1. **UI 字段** → **维持电压/温度最小集**，不新增 STATE/ATT_Tc/MCU_VER 显示。
2. **DOC Markdown 协议文档** → **同步更新**为 V2.1（`AFDT1024_TX_Protocol.md` / `AFDR1024_RX_Protocol.md`）。
3. **子阵 ID +128 模式** → **需要 UI 支持**：TX/RX 面板"子阵设置"区新增"仅本子阵(ID+128)"复选框，勾选时所有指令的 `device_id = id + 128`（仅对应 ID 响应并返回）。新增面板辅助方法 `_get_device_id()` 统一返回修饰后的 ID。

---

## 6. 不做的事（范围边界）
- 不兼容任何旧协议/旧设备行为（含 RX 校验和 bug）。
- 不改动 KaUDC004A 协议与面板。
- 不重构线程/UI 架构，仅做协议层与必要调用点适配。
