# AFDT1024 协议处理模块

# 帧头定义
FRAME_HEADER = b"\x50\x53\x41"  # "PSA"

# 指令地址定义
# TX设备指令
ADDR_TX_BEAM = 0x50  # TX波束设置
ADDR_TX_ENABLE = 0x51  # TX阵列使能
ADDR_TX_POLARIZATION = 0x53  # TX极化设置
ADDR_PA_ENABLE = 0x56  # 推动PA使能
ADDR_PHASE_CAL = 0x57  # 整板相位偏移校准
ADDR_ID_UPDATE = 0x20  # ID更新
ADDR_STATUS_QUERY = 0x5C  # 状态查询

# RX设备指令
ADDR_RX_BEAM = 0x90  # RX波束设置
ADDR_RX_ENABLE = 0x91  # RX阵列使能
ADDR_RX_POLARIZATION = 0x93  # RX极化设置
ADDR_RX_PHASE_CAL = 0x97  # RX整板相位偏移校准
ADDR_RX_STATUS_QUERY = 0x9C  # RX状态查询

# 配置命令地址映射（用于回显检测时显示命令名称）
ADDR_CMD_NAMES = {
    ADDR_TX_BEAM: "TX波束",
    ADDR_TX_ENABLE: "TX阵列使能",
    ADDR_TX_POLARIZATION: "TX极化",
    ADDR_PA_ENABLE: "PA使能",
    ADDR_RX_BEAM: "RX波束",
    ADDR_RX_ENABLE: "RX阵列使能",
    ADDR_RX_POLARIZATION: "RX极化",
}

# 极化设置定义
POLARIZATION_LHCP = 0
POLARIZATION_RHCP = 1

# 阵列使能定义
ARRAY_ENABLE = 0xFFFF
ARRAY_DISABLE = 0x0000

# PA使能定义
PA_DISABLE = 0
PA_ENABLE = 1

# 频率参考值
TX_F0 = 30000  # TX参考频率，单位MHz
RX_F0 = 20270  # RX参考频率，单位MHz

# 角度到beam值转换常量
MAX_BEAM_VALUE = 4095
HALF_BEAM_VALUE = 2048

# 角度范围常量
MIN_ANGLE = -180.0
MAX_ANGLE = 180.0

# 角度步进常量
ANGLE_STEP = 360.0 / MAX_BEAM_VALUE


def calculate_checksum(data):
    """计算校验和"""
    checksum = sum(data)
    return checksum & 0xFF


def build_frame(device_id, addr, payload):
    """构建AFDT1024协议帧"""
    # 构建数据部分（DATA + ADDR）
    data = payload + bytes([addr])

    # 计算长度（包含payload和addr的总长度）
    length = len(data)

    # 构建帧
    frame = FRAME_HEADER + bytes([device_id]) + bytes([length]) + data

    # 计算校验和
    checksum = calculate_checksum(frame)

    # 完整帧
    frame += bytes([checksum])

    return frame


def parse_response(frame, has_rx_status_bug=False):
    """解析AFDT1024协议响应帧
    has_rx_status_bug: RX设备状态查询回复的校验和不包含mcu_ver字段
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

        if has_rx_status_bug and len(data) >= 5:
            expected_checksum = calculate_checksum(frame[:-2])
        else:
            expected_checksum = calculate_checksum(frame[:-1])
        if checksum != expected_checksum:
            return None, "校验和错误"

        # 判断是配置命令回复还是状态查询回复
        # 关键: 检查 data[-1] 是否为已知命令地址
        known_addrs = [
            ADDR_TX_BEAM,
            ADDR_TX_ENABLE,
            ADDR_TX_POLARIZATION,
            ADDR_PA_ENABLE,
            ADDR_RX_BEAM,
            ADDR_RX_ENABLE,
            ADDR_RX_POLARIZATION,
        ]

        if data[-1] in known_addrs:
            # 配置命令 Echo 回复 - data[-1] 是 addr
            addr = data[-1]
            payload = data[:-1]
        else:
            # 状态查询回复 - data 是纯状态数据
            addr = None
            payload = data

        return {"device_id": device_id, "addr": addr, "payload": payload}, "OK"
    except Exception as e:
        return None, f"解析错误: {str(e)}"


def build_tx_beam_command(freq, beam_h, beam_v):
    """构建TX波束设置命令
    freq: 0~70
    beam_h: 12位补码
    beam_v: 12位补码
    """
    # 确保参数在有效范围内
    freq = max(0, min(70, freq))
    beam_h = beam_h & 0xFFF  # 12位
    beam_v = beam_v & 0xFFF  # 12位

    # 构建payload: [freq][BeamV_H][BeamV_L(4位) + BeamH_H(4位)][BeamH_L]
    payload = bytes([freq])
    payload += (beam_v >> 8).to_bytes(1, "big")  # BeamV_H
    payload += (((beam_v & 0xFF) >> 4) << 4 | (beam_h >> 8)).to_bytes(
        1, "big"
    )  # BeamV_L(4位) + BeamH_H(4位)
    payload += (beam_h & 0xFF).to_bytes(1, "big")  # BeamH_L

    return payload


def build_tx_enable_command(enable):
    """构建TX阵列使能命令
    enable: True/False
    """
    value = ARRAY_ENABLE if enable else ARRAY_DISABLE
    # 构建payload [TX_EN_ROW_H][TX_EN_ROW_L][0xFF][0xFF]
    payload = (value >> 8).to_bytes(1, "big")  # TX_EN_ROW_H
    payload += (value & 0xFF).to_bytes(1, "big")  # TX_EN_ROW_L
    payload += b"\xff\xff"  # 固定值
    return payload


def build_tx_polarization_command(polarization):
    """构建TX极化设置命令
    polarization: 0=LHCP, 1=RHCP
    """
    # 构建payload [0x00][0x00][0x00][POL]

    payload = b"\x00\x00\x00"  # reserved填充
    payload += bytes([polarization])
    return payload


def build_pa_enable_command(enable):
    """构建推动PA使能命令
    enable: True/False
    """
    value = PA_ENABLE if enable else PA_DISABLE
    # 构建payload [0x00][0x00][0x00][0x00][PA_EN]
    payload = b"\x00\x00\x00"  # reserved填充
    payload += bytes([value])
    return payload


def build_phase_cal_command(phase_offset):
    """构建整板相位偏移校准命令
    phase_offset: 0~63
    """
    phase_offset = max(0, min(63, phase_offset))
    # 构建payload [PS_Align][0x00][0x00][0x00]

    payload = b"\x00\x00\x00"  # reserved填充
    payload += bytes([phase_offset])
    return payload


def build_id_update_command(new_id):
    """构建ID更新命令
    new_id: 新的子阵ID
    """
    # 构建payload [0x00][ID_new]

    payload = b"\x00"  # reserved填充
    payload += bytes([new_id])
    return payload


def build_status_query_command():
    """构建状态查询命令"""
    return b""


def build_rx_beam_command(freq, beam_v, beam_h):
    """构建RX波束设置命令
    freq: 0~70
    beam_v: 12位补码
    beam_h: 12位补码
    """
    # 确保参数在有效范围内
    freq = max(0, min(70, freq))
    beam_v = beam_v & 0xFFF  # 12位
    beam_h = beam_h & 0xFFF  # 12位

    # 构建payload: [freq][BeamV_H][BeamV_L(4位) + BeamH_H(4位)][BeamH_L]
    payload = bytes([freq])
    payload += (beam_v >> 8).to_bytes(1, "big")  # BeamV_H
    payload += (((beam_v & 0xFF) >> 4) << 4 | (beam_h >> 8)).to_bytes(
        1, "big"
    )  # BeamV_L(4位) + BeamH_H(4位)
    payload += (beam_h & 0xFF).to_bytes(1, "big")  # BeamH_L

    return payload


def build_rx_enable_command(enable):
    """构建RX阵列使能命令
    enable: True/False
    """
    value = ARRAY_ENABLE if enable else ARRAY_DISABLE
    # 构建payload [RX_EN_ROW_H][RX_EN_ROW_L][0xFF][0xFF]
    payload = (value >> 8).to_bytes(1, "big")  # RX_EN_ROW_H
    payload += (value & 0xFF).to_bytes(1, "big")  # RX_EN_ROW_L
    payload += b"\xff\xff"  # 固定值

    return payload


def build_rx_polarization_command(polarization):
    """构建RX极化设置命令
    polarization: 0=LHCP, 1=RHCP
    """
    # 构建payload [0x00][0x00][0x00][POL]

    payload = b"\x00\x00\x00"  # 固定值
    payload += bytes([polarization])

    return payload


def build_rx_phase_cal_command(phase_offset):
    """构建RX整板相位偏移校准命令
    phase_offset: 0~63
    """
    phase_offset = max(0, min(63, phase_offset))
    # 构建payload [0x00][0x00][0x00][PS_Align]
    payload = b"\x00\x00\x00"  # 固定值
    payload += bytes([phase_offset])

    return payload


def build_rx_status_query_command():
    """构建RX状态查询命令"""
    # 构建payload（空）
    return b""


def parse_status_response(payload):
    """解析状态查询响应
    返回字典包含状态信息
    格式: [Rev][state][SysVcc][SysTemp][ATT_Tc][MCU_VER] (5-6字节)
    - SysVcc: value × 0.1 V
    - SysTemp: value - 80 (℃)
    """
    if len(payload) < 5:
        return None, "状态响应长度不足"

    try:
        result = {}
        result["raw"] = payload.hex()

        result["rev"] = payload[0]
        result["state"] = payload[1] if len(payload) > 1 else 0
        result["sys_vcc"] = payload[2] * 0.1
        result["sys_temp"] = payload[3] - 80
        result["att_tc"] = payload[4]
        result["mcu_ver"] = payload[5] if len(payload) > 5 else 0

        return result, "OK"
    except Exception as e:
        return None, f"解析状态响应错误: {str(e)}"


def parse_rx_status_response(payload):
    """解析RX状态响应
    返回字典包含状态信息
    格式: [Rev][SysVcc][SysTemp][ATT_Tc] (4字节) 或 5字节
    - SysVcc: value × 0.1 V
    - SysTemp: value - 80 (℃)
    """
    if len(payload) < 4:
        return None, "RX状态响应长度不足"

    try:
        result = {}
        result["raw"] = payload.hex()

        result["rev"] = payload[0]
        result["sys_vcc"] = payload[1] * 0.1
        result["sys_temp"] = payload[2] - 80
        result["att_tc"] = payload[3]
        result["mcu_ver"] = payload[4] if len(payload) > 4 else 0

        return result, "OK"
    except Exception as e:
        return None, f"解析RX状态响应错误: {str(e)}"


# 角度转换函数
def angle_to_beam(angle):
    """将角度转换为12位补码的beam值
    angle: 角度值，范围-180.0到180.0
    返回: 12位补码的beam值，范围0-4095
    """
    # 限制角度范围
    angle = max(MIN_ANGLE, min(MAX_ANGLE, angle))

    # 转换为beam值
    if angle >= 0:
        beam = int(angle / ANGLE_STEP)
    else:
        beam = int((angle + 360.0) / ANGLE_STEP)

    # 确保在0-4095范围内
    return beam & 0xFFF


def calculate_beam_values(theta, phi, freq, is_tx=True):
    """根据theta和phi角度计算beamH和beamV
    theta: 俯仰角，范围-180.0到180.0
    phi: 方位角，范围-180.0到180.0
    freq: 当前工作频率，单位MHz
    is_tx: 是否为TX设备，True为TX，False为RX
    返回: (beam_h, beam_v) 元组
    """
    import math

    # 选择参考频率
    f0 = TX_F0 if is_tx else RX_F0

    # 转换角度为弧度
    theta_rad = math.radians(theta)
    phi_rad = math.radians(phi)

    # 计算归一化相位
    ux = 180.0 * (freq / f0) * math.sin(theta_rad) * math.cos(phi_rad)
    uy = 180.0 * (freq / f0) * math.sin(theta_rad) * math.sin(phi_rad)

    # 转换为beam值
    beam_h = angle_to_beam(ux)
    beam_v = angle_to_beam(uy)

    return beam_h, beam_v


# 便捷函数
def build_tx_beam_frame(device_id, freq, beam_h, beam_v):
    """构建TX波束设置帧"""
    payload = build_tx_beam_command(freq, beam_h, beam_v)
    return build_frame(device_id, ADDR_TX_BEAM, payload)


def build_tx_enable_frame(device_id, enable):
    """构建TX阵列使能帧"""
    payload = build_tx_enable_command(enable)
    return build_frame(device_id, ADDR_TX_ENABLE, payload)


def build_tx_polarization_frame(device_id, polarization):
    """构建TX极化设置帧"""
    payload = build_tx_polarization_command(polarization)
    return build_frame(device_id, ADDR_TX_POLARIZATION, payload)


def build_pa_enable_frame(device_id, enable):
    """构建推动PA使能帧"""
    payload = build_pa_enable_command(enable)
    return build_frame(device_id, ADDR_PA_ENABLE, payload)


def build_phase_cal_frame(device_id, phase_offset):
    """构建整板相位偏移校准帧"""
    payload = build_phase_cal_command(phase_offset)
    return build_frame(device_id, ADDR_PHASE_CAL, payload)


def build_id_update_frame(device_id, new_id):
    """构建ID更新帧"""
    payload = build_id_update_command(new_id)
    return build_frame(device_id, ADDR_ID_UPDATE, payload)


def build_status_query_frame(device_id):
    """构建状态查询帧"""
    payload = build_status_query_command()
    return build_frame(device_id, ADDR_STATUS_QUERY, payload)


# RX设备便捷函数
def build_rx_beam_frame(device_id, freq, beam_v, beam_h):
    """构建RX波束设置帧"""
    payload = build_rx_beam_command(freq, beam_v, beam_h)
    return build_frame(device_id, ADDR_RX_BEAM, payload)


def build_rx_enable_frame(device_id, enable):
    """构建RX阵列使能帧"""
    payload = build_rx_enable_command(enable)
    return build_frame(device_id, ADDR_RX_ENABLE, payload)


def build_rx_polarization_frame(device_id, polarization):
    """构建RX极化设置帧"""
    payload = build_rx_polarization_command(polarization)
    return build_frame(device_id, ADDR_RX_POLARIZATION, payload)


def build_rx_phase_cal_frame(device_id, phase_offset):
    """构建RX整板相位偏移校准帧"""
    payload = build_rx_phase_cal_command(phase_offset)
    return build_frame(device_id, ADDR_RX_PHASE_CAL, payload)


def build_rx_status_query_frame(device_id):
    """构建RX状态查询帧"""
    payload = build_rx_status_query_command()
    return build_frame(device_id, ADDR_RX_STATUS_QUERY, payload)
