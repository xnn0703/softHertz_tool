# AFDT1024 / AFDR1024 协议处理模块（V2.1, 20260317）
#
# 依据:
#   Ka波段1024单元发射子阵（无变频）控制接口协议_V2.1_20260317
#   Ka波段1024单元接收子阵（无变频）控制接口协议_V2.1_20260317
#
# V2.1 要点:
#   1. 所有返回帧的数据区最后一个字节均为"指令号"(ADDR)。
#   2. 查询返回帧在 V2.1 末尾新增指令号字节: TX 数据长度=7(末尾0x5C), RX 数据长度=6(末尾0x9C)。
#   3. CheckSum 一律为"除 CheckSum 外所有字节求和"的低 8 位（无任何例外分支）。
#   注: 不兼容旧协议/旧设备行为（含历史 RX 校验和 bug）。
import math

# 帧头定义
FRAME_HEADER = b"\x50\x53\x41"  # "PSA"

# ---- 指令地址定义 ----
# TX 设备指令
ADDR_TX_BEAM = 0x50  # TX 波束设置
ADDR_TX_ENABLE = 0x51  # TX 阵列使能
ADDR_TX_POLARIZATION = 0x53  # TX 极化设置
ADDR_PA_ENABLE = 0x56  # 推动 PA 使能
ADDR_PHASE_CAL = 0x57  # TX 整板相位偏移校准
ADDR_ID_UPDATE = 0x20  # ID 更新
ADDR_STATUS_QUERY = 0x5C  # TX 状态查询 / 查询返回指令号

# RX 设备指令
ADDR_RX_BEAM = 0x90  # RX 波束设置
ADDR_RX_ENABLE = 0x91  # RX 阵列使能
ADDR_RX_POLARIZATION = 0x93  # RX 极化设置
ADDR_RX_PHASE_CAL = 0x97  # RX 整板相位偏移校准
ADDR_RX_STATUS_QUERY = 0x9C  # RX 状态查询 / 查询返回指令号

# 配置命令地址（设备收到后按 ID 原封返回 echo）
CONFIG_ECHO_ADDRS = {
    ADDR_TX_BEAM,
    ADDR_TX_ENABLE,
    ADDR_TX_POLARIZATION,
    ADDR_PA_ENABLE,
    ADDR_PHASE_CAL,
    ADDR_ID_UPDATE,
    ADDR_RX_BEAM,
    ADDR_RX_ENABLE,
    ADDR_RX_POLARIZATION,
    ADDR_RX_PHASE_CAL,
}

# 查询返回指令号 -> 设备类型
STATUS_RETURN_ADDRS = {
    ADDR_STATUS_QUERY: "TX",  # 0x5C
    ADDR_RX_STATUS_QUERY: "RX",  # 0x9C
}

# 查询指令2（波束参数）地址与返回指令号 -> 设备类型（V2.2）
ADDR_TX_BEAM_QUERY = 0x5F
ADDR_RX_BEAM_QUERY = 0x9F
BEAM_QUERY_RETURN_ADDRS = {
    ADDR_TX_BEAM_QUERY: "TX",
    ADDR_RX_BEAM_QUERY: "RX",
}

# 配置命令地址映射（用于回显检测时显示命令名称）
ADDR_CMD_NAMES = {
    ADDR_TX_BEAM: "TX波束",
    ADDR_TX_ENABLE: "TX阵列使能",
    ADDR_TX_POLARIZATION: "TX极化",
    ADDR_PA_ENABLE: "PA使能",
    ADDR_PHASE_CAL: "TX相位校准",
    ADDR_ID_UPDATE: "ID更新",
    ADDR_RX_BEAM: "RX波束",
    ADDR_RX_ENABLE: "RX阵列使能",
    ADDR_RX_POLARIZATION: "RX极化",
    ADDR_RX_PHASE_CAL: "RX相位校准",
}

# 极化设置定义
POLARIZATION_LHCP = 0
POLARIZATION_RHCP = 1

# 阵列使能定义
ARRAY_ENABLE = 0xFFFF
ARRAY_DISABLE = 0x0000

# PA 使能定义
PA_DISABLE = 0
PA_ENABLE = 1

# 波控参考频率（单位 MHz）
TX_F0 = 30000  # 发射子阵单元间距对应中心频率
RX_F0 = 20270  # 接收子阵单元间距对应中心频率

# 12bit 波控值常量
BEAM_CODE_RANGE = 4096  # 12bit
BEAM_CODE_MASK = 0xFFF


def calculate_checksum(data):
    """计算校验和（所有字节求和的低 8 位）"""
    return sum(data) & 0xFF


def build_frame(device_id, addr, payload):
    """构建 AFDT1024/AFDR1024 协议帧。

    数据区 = payload + ADDR；数据长度 = len(payload) + 1。
    """
    data = payload + bytes([addr])
    length = len(data)
    frame = FRAME_HEADER + bytes([device_id]) + bytes([length]) + data
    frame += bytes([calculate_checksum(frame)])
    return frame


def parse_response(frame):
    """解析 AFDT1024/AFDR1024 V2.1 响应帧。

    V2.1: 数据区最后一字节为指令号(ADDR)，校验和为除 CheckSum 外所有字节求和的低 8 位。

    Returns:
        (dict{device_id, addr, payload}, "OK") 或 (None, 错误信息)
        payload 为数据区去掉末尾指令号后的内容。
        - addr ∈ CONFIG_ECHO_ADDRS  : 配置命令 echo
        - addr ∈ STATUS_RETURN_ADDRS: 查询返回（0x5C=TX, 0x9C=RX）
    """
    try:
        if frame[:3] != FRAME_HEADER:
            return None, "无效的帧头"

        device_id = frame[3]
        length = frame[4]
        data = frame[5:-1]
        checksum = frame[-1]

        if len(data) != length:
            return None, "长度不匹配"

        if checksum != calculate_checksum(frame[:-1]):
            return None, "校验和错误"

        if len(data) == 0:
            return None, "数据区为空"

        addr = data[-1]
        payload = data[:-1]
        return {"device_id": device_id, "addr": addr, "payload": payload}, "OK"
    except Exception as e:
        return None, f"解析错误: {str(e)}"


# ============================================================
# 波控值计算（V2.1）
# ============================================================


def angle_to_code_12bit(angle):
    """角度 -> 12bit 补码波控值（V2.1）。

    angle >= 0: round(angle * 2048 / 180)
    angle <  0: round(angle * 2048 / 180 + 4096)
    最终对 4096 取模。round 采用四舍五入(远离零)，与协议 Matlab round 一致。
    """
    val = angle * 2048.0 / 180.0
    if angle < 0:
        val += BEAM_CODE_RANGE
    code = math.floor(val + 0.5)  # 此处 val 已为非负，等价四舍五入
    return int(code) % BEAM_CODE_RANGE


def calculate_beam_values(theta, phi, freq, is_tx=True):
    """根据离轴角 theta 和方位角 phi 计算 (beam_h, beam_v)。

    theta: 离轴角(俯仰)，单位度
    phi:   方位角，单位度
    freq:  当前工作频率，单位 MHz
    is_tx: True=TX(f0=30000), False=RX(f0=20270)

    Returns: (beam_h, beam_v) 均为 12bit 补码值
    """
    f0 = TX_F0 if is_tx else RX_F0
    theta_rad = math.radians(theta)
    phi_rad = math.radians(phi)

    ux = 180.0 * (freq / f0) * math.sin(theta_rad) * math.cos(phi_rad)
    uy = 180.0 * (freq / f0) * math.sin(theta_rad) * math.sin(phi_rad)

    beam_h = angle_to_code_12bit(ux)
    beam_v = angle_to_code_12bit(uy)
    return beam_h, beam_v


def _pack_beam_payload(freq, beam_h, beam_v):
    """打包波束数据区(不含 ADDR)：FREQ | BeamV[11:0] | BeamH[11:0] = 4 Byte。

    布局(大端，D31~D0)：
        Byte3 = FREQ[7:0]                       (D31~D24)
        Byte2 = BeamV[11:4]                      (D23~D16)
        Byte1 = BeamV[3:0]<<4 | BeamH[11:8]      (D15~D8)
        Byte0 = BeamH[7:0]                       (D7~D0)
    """
    freq &= 0xFF
    beam_v &= BEAM_CODE_MASK
    beam_h &= BEAM_CODE_MASK
    return bytes(
        [
            freq,
            (beam_v >> 4) & 0xFF,
            ((beam_v & 0x0F) << 4) | ((beam_h >> 8) & 0x0F),
            beam_h & 0xFF,
        ]
    )


# ============================================================
# 命令 payload 构建（不含 ADDR）
# ============================================================


def build_tx_beam_command(freq, beam_h, beam_v):
    """TX 波束设置 payload：freq 0~70，beam_h/beam_v 为 12bit 补码"""
    return _pack_beam_payload(freq, beam_h, beam_v)


def build_rx_beam_command(freq, beam_h, beam_v):
    """RX 波束设置 payload（布局与 TX 一致）"""
    return _pack_beam_payload(freq, beam_h, beam_v)


def build_enable_command(enable):
    """阵列使能 payload：[EN_ROW_H][EN_ROW_L][0xFF][0xFF]，全 1 开 / 全 0 关"""
    value = ARRAY_ENABLE if enable else ARRAY_DISABLE
    return bytes([(value >> 8) & 0xFF, value & 0xFF]) + b"\xff\xff"


def build_polarization_command(polarization):
    """极化设置 payload：[reserved x3][POL]，POL 0=LHCP 1=RHCP"""
    return b"\x00\x00\x00" + bytes([polarization & 0x01])


def build_pa_enable_command(enable):
    """推动 PA 使能 payload（仅 TX）：[reserved x3][PA_EN]"""
    value = PA_ENABLE if enable else PA_DISABLE
    return b"\x00\x00\x00" + bytes([value & 0x01])


def build_phase_cal_command(phase_offset):
    """整板相位偏移校准 payload：[reserved x3][PS_Align]，PS_Align 0~63"""
    phase_offset = max(0, min(63, phase_offset))
    return b"\x00\x00\x00" + bytes([phase_offset & 0x3F])


def build_id_update_command(new_id):
    """ID 更新 payload：[reserved][ID_new]（数据长度=3，需用公共 ID 0x00 发送）"""
    return b"\x00" + bytes([new_id & 0xFF])


def build_status_query_command():
    """状态查询 payload（空，仅 ADDR）"""
    return b""


# 兼容旧命名
build_tx_enable_command = build_enable_command
build_rx_enable_command = build_enable_command
build_tx_polarization_command = build_polarization_command
build_rx_polarization_command = build_polarization_command
build_rx_phase_cal_command = build_phase_cal_command
build_rx_status_query_command = build_status_query_command


# ============================================================
# 完整帧便捷构建函数（device_id, ...）
# ============================================================


def build_tx_beam_frame(device_id, freq, beam_h, beam_v):
    """构建 TX 波束设置帧"""
    return build_frame(device_id, ADDR_TX_BEAM, build_tx_beam_command(freq, beam_h, beam_v))


def build_tx_enable_frame(device_id, enable):
    """构建 TX 阵列使能帧"""
    return build_frame(device_id, ADDR_TX_ENABLE, build_enable_command(enable))


def build_tx_polarization_frame(device_id, polarization):
    """构建 TX 极化设置帧"""
    return build_frame(device_id, ADDR_TX_POLARIZATION, build_polarization_command(polarization))


def build_pa_enable_frame(device_id, enable):
    """构建推动 PA 使能帧（仅 TX）"""
    return build_frame(device_id, ADDR_PA_ENABLE, build_pa_enable_command(enable))


def build_phase_cal_frame(device_id, phase_offset):
    """构建 TX 整板相位偏移校准帧"""
    return build_frame(device_id, ADDR_PHASE_CAL, build_phase_cal_command(phase_offset))


def build_id_update_frame(device_id, new_id):
    """构建 ID 更新帧（应使用公共 ID 0x00 作为 device_id）"""
    return build_frame(device_id, ADDR_ID_UPDATE, build_id_update_command(new_id))


def build_status_query_frame(device_id):
    """构建 TX 状态查询帧"""
    return build_frame(device_id, ADDR_STATUS_QUERY, build_status_query_command())


def build_rx_beam_frame(device_id, freq, beam_h, beam_v):
    """构建 RX 波束设置帧（参数顺序与 TX 统一）"""
    return build_frame(device_id, ADDR_RX_BEAM, build_rx_beam_command(freq, beam_h, beam_v))


def build_rx_enable_frame(device_id, enable):
    """构建 RX 阵列使能帧"""
    return build_frame(device_id, ADDR_RX_ENABLE, build_enable_command(enable))


def build_rx_polarization_frame(device_id, polarization):
    """构建 RX 极化设置帧"""
    return build_frame(device_id, ADDR_RX_POLARIZATION, build_polarization_command(polarization))


def build_rx_phase_cal_frame(device_id, phase_offset):
    """构建 RX 整板相位偏移校准帧"""
    return build_frame(device_id, ADDR_RX_PHASE_CAL, build_phase_cal_command(phase_offset))


def build_rx_status_query_frame(device_id):
    """构建 RX 状态查询帧"""
    return build_frame(device_id, ADDR_RX_STATUS_QUERY, build_status_query_command())


def build_tx_beam_query_frame(device_id):
    """构建 TX 查询指令2（波束参数）帧（V2.2）"""
    return build_frame(device_id, ADDR_TX_BEAM_QUERY, b"")


def build_rx_beam_query_frame(device_id):
    """构建 RX 查询指令2（波束参数）帧（V2.2）"""
    return build_frame(device_id, ADDR_RX_BEAM_QUERY, b"")


def _code_to_deg(code):
    """12bit 补码波控值 -> 角度（度）。0~2047→0~+180，2048~4095→-180~0。"""
    code &= 0xFFF
    if code < 2048:
        return code * 180.0 / 2048.0
    return (code - 4096) * 180.0 / 2048.0


def beam_code_to_angle(beam_v, beam_h, freq, is_tx=True):
    """由 BeamV/BeamH 码值与频率反算离轴角 θ 与方位角 φ（度）。

    BeamH→Ux, BeamV→Uy；Ux=180×(f/f0)×sinθ×cosφ, Uy=180×(f/f0)×sinθ×sinφ。
    → θ=asin(hypot(Ux,Uy)/k), φ=atan2(Uy,Ux), k=180×f/f0。
    注: 单组 BeamV/BeamH 反解二维角度，θ 取 [0,90]。
    """
    f0 = TX_F0 if is_tx else RX_F0
    ux = _code_to_deg(beam_h)
    uy = _code_to_deg(beam_v)
    k = 180.0 * (freq / f0) if f0 else 0.0
    if k == 0:
        return 0.0, 0.0
    s = max(0.0, min(1.0, math.hypot(ux, uy) / k))
    theta = math.degrees(math.asin(s))
    phi = math.degrees(math.atan2(uy, ux))
    return theta, phi


def parse_beam_query_response(payload, is_tx=True):
    """解析查询指令2（波束参数）返回（V2.2）。

    payload 为去掉末尾指令号(0x5F/0x9F)后的 16 字节(D127~D0, big-endian)：
        Rev(D127~D65) | POL(D64) | EN_ROW(D63~D48) | 0xFFFF(D47~D32)
        | FREQ(D31~D24) | BeamV(D23~D12) | BeamH(D11~D0)
    """
    if len(payload) < 16:
        return None, "波束参数响应长度不足"
    try:
        pol = payload[7] & 0x01
        en_row = (payload[8] << 8) | payload[9]
        freq_code = payload[12]
        beam_v = (payload[13] << 4) | ((payload[14] >> 4) & 0x0F)
        beam_h = ((payload[14] & 0x0F) << 8) | payload[15]
        freq_mhz = (27500 if is_tx else 17700) + 50 * freq_code
        theta, phi = beam_code_to_angle(beam_v, beam_h, freq_mhz, is_tx)
        return {
            "pol": pol,
            "en_row": en_row,
            "freq_code": freq_code,
            "freq_mhz": freq_mhz,
            "beam_v": beam_v,
            "beam_h": beam_h,
            "theta": theta,
            "phi": phi,
        }, "OK"
    except Exception as e:
        return None, f"解析波束参数响应错误: {str(e)}"


# ============================================================
# 查询返回解析（V2.1）
# ============================================================


def parse_status_response(payload):
    """解析 TX 查询返回（V2.1）。

    传入 payload 为 parse_response 去掉末尾指令号(0x5C)后的数据，共 6 字节：
        [Rev][STATE][SysVcc][SysTemp][ATT_Tc][MCU_VER]
    - STATE.B0 = PA_EN
    - SysVcc 实际电压 = 值 × 0.1 V
    - SysTemp 实际温度 = 值 − 80 ℃
    """
    if len(payload) < 6:
        return None, "TX状态响应长度不足"
    try:
        return {
            "raw": payload.hex(),
            "rev": payload[0],
            "state": payload[1],
            "pa_en": payload[1] & 0x01,
            "sys_vcc": payload[2] * 0.1,
            "sys_temp": payload[3] - 80,
            "att_tc": payload[4],
            "mcu_ver": payload[5],
        }, "OK"
    except Exception as e:
        return None, f"解析TX状态响应错误: {str(e)}"


def parse_rx_status_response(payload):
    """解析 RX 查询返回（V2.1）。

    传入 payload 为 parse_response 去掉末尾指令号(0x9C)后的数据，共 5 字节：
        [Rev][SysVcc][SysTemp][ATT_Tc][MCU_VER]
    （RX 无 STATE 字段）
    """
    if len(payload) < 5:
        return None, "RX状态响应长度不足"
    try:
        return {
            "raw": payload.hex(),
            "rev": payload[0],
            "sys_vcc": payload[1] * 0.1,
            "sys_temp": payload[2] - 80,
            "att_tc": payload[3],
            "mcu_ver": payload[4],
        }, "OK"
    except Exception as e:
        return None, f"解析RX状态响应错误: {str(e)}"
