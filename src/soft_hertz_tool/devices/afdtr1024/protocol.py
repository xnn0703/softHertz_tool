"""AFDT1024/AFDR1024 共用协议实现。

硬件型号分别为 AFDT1024（发射阵列）和 AFDR1024（接收阵列）；
``afdtr1024`` 仅作为内部共用模块目录名。
本模块的地址、字段、端序、求和校验和波束算法保持受控 TX/RX 协议不变。
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional, Tuple, Union

from soft_hertz_tool.devices.afdtr1024.models import BeamSetting, DeviceVariant


FRAME_HEADER = b"\x50\x53\x41"  # "PSA"

# TX 指令地址
ADDR_TX_BEAM = 0x50
ADDR_TX_ENABLE = 0x51
ADDR_TX_POLARIZATION = 0x53
ADDR_PA_ENABLE = 0x56
ADDR_PHASE_CAL = 0x57
ADDR_ID_UPDATE = 0x20
ADDR_STATUS_QUERY = 0x5C
ADDR_TX_BEAM_QUERY = 0x5F

# RX 指令地址
ADDR_RX_BEAM = 0x90
ADDR_RX_ENABLE = 0x91
ADDR_RX_POLARIZATION = 0x93
ADDR_RX_PHASE_CAL = 0x97
ADDR_RX_STATUS_QUERY = 0x9C
ADDR_RX_BEAM_QUERY = 0x9F

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

TX_CONFIG_ADDRS = {
    ADDR_TX_BEAM,
    ADDR_TX_ENABLE,
    ADDR_TX_POLARIZATION,
    ADDR_PA_ENABLE,
    ADDR_PHASE_CAL,
    ADDR_ID_UPDATE,
}
RX_CONFIG_ADDRS = {
    ADDR_RX_BEAM,
    ADDR_RX_ENABLE,
    ADDR_RX_POLARIZATION,
    ADDR_RX_PHASE_CAL,
    ADDR_ID_UPDATE,
}

STATUS_RETURN_ADDRS = {
    ADDR_STATUS_QUERY: DeviceVariant.TX.value,
    ADDR_RX_STATUS_QUERY: DeviceVariant.RX.value,
}
BEAM_QUERY_RETURN_ADDRS = {
    ADDR_TX_BEAM_QUERY: DeviceVariant.TX.value,
    ADDR_RX_BEAM_QUERY: DeviceVariant.RX.value,
}

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
ADDR_NAMES = {
    **ADDR_CMD_NAMES,
    ADDR_STATUS_QUERY: "TX状态查询",
    ADDR_TX_BEAM_QUERY: "TX波束参数查询",
    ADDR_RX_STATUS_QUERY: "RX状态查询",
    ADDR_RX_BEAM_QUERY: "RX波束参数查询",
}

POLARIZATION_LHCP = 0
POLARIZATION_RHCP = 1
ARRAY_ENABLE = 0xFFFF
ARRAY_DISABLE = 0x0000
PA_DISABLE = 0
PA_ENABLE = 1

TX_F0 = 30000
RX_F0 = 20270
TX_MIN_FREQ = 27500
TX_MAX_FREQ = 31000
RX_MIN_FREQ = 17700
RX_MAX_FREQ = 21200
FREQUENCY_STEP_MHZ = 50
MAX_FREQUENCY_CODE = 70

BEAM_CODE_RANGE = 4096
BEAM_CODE_MASK = 0x0FFF


def command_name(addr: int) -> str:
    """返回指令地址的人类可读名称，未知地址按十六进制显示。"""
    return ADDR_NAMES.get(addr, f"0x{addr:02X}")


def calculate_checksum(data: bytes) -> int:
    """返回除 CheckSum 外所有字节求和的低 8 位。"""

    return sum(data) & 0xFF


def build_frame(device_id: int, addr: int, payload: bytes = b"") -> bytes:
    """构建 ``PSA | ID | LEN | payload | ADDR | CheckSum`` 完整帧。"""

    if not 0 <= int(device_id) <= 0xFF:
        raise ValueError("device_id 必须在 0x00~0xFF 范围内")
    if not 0 <= int(addr) <= 0xFF:
        raise ValueError("addr 必须在 0x00~0xFF 范围内")
    payload = bytes(payload)
    data = payload + bytes([int(addr)])
    if len(data) > 0xFF:
        raise ValueError("数据区长度不能超过 255 字节")
    frame = FRAME_HEADER + bytes([int(device_id), len(data)]) + data
    return frame + bytes([calculate_checksum(frame)])


def parse_response(frame: bytes) -> Tuple[Optional[dict[str, Any]], str]:
    """解析配置回显或查询返回帧，payload 不含末尾指令地址。"""

    frame = bytes(frame)
    if frame[:3] != FRAME_HEADER:
        return None, "无效的帧头"
    if len(frame) < 6:
        return None, "长度不匹配"

    length = frame[4]
    if len(frame) != 6 + length:
        return None, "长度不匹配"
    if length == 0:
        return None, "数据区为空"
    if frame[-1] != calculate_checksum(frame[:-1]):
        return None, "校验和错误"

    data = frame[5:-1]
    return {
        "device_id": frame[3],
        "addr": data[-1],
        "payload": data[:-1],
    }, "OK"


def angle_to_code_12bit(angle: float) -> int:
    """角度转换为 12 bit 补码波控值，舍入规则与受控协议一致。"""

    value = angle * 2048.0 / 180.0
    if angle < 0:
        value += BEAM_CODE_RANGE
    return int(math.floor(value + 0.5)) % BEAM_CODE_RANGE


def calculate_beam_values(
    theta: float,
    phi: float,
    freq: float,
    is_tx: bool = True,
) -> tuple[int, int]:
    """根据角度和实际工作频率计算 ``(BeamH, BeamV)``。"""

    f0 = TX_F0 if is_tx else RX_F0
    theta_rad = math.radians(theta)
    phi_rad = math.radians(phi)
    ux = 180.0 * (freq / f0) * math.sin(theta_rad) * math.cos(phi_rad)
    uy = 180.0 * (freq / f0) * math.sin(theta_rad) * math.sin(phi_rad)
    return angle_to_code_12bit(ux), angle_to_code_12bit(uy)


def quantize_frequency(
    frequency_mhz: float,
    variant: Union[DeviceVariant, str],
) -> tuple[int, int]:
    """按 50 MHz 网格量化频率，返回 ``(频率码, 实际频率 MHz)``。"""

    variant = DeviceVariant.coerce(variant)
    value = float(frequency_mhz)
    if not math.isfinite(value):
        raise ValueError("频率必须是有限数值")
    minimum = TX_MIN_FREQ if variant.is_tx else RX_MIN_FREQ
    maximum = TX_MAX_FREQ if variant.is_tx else RX_MAX_FREQ
    if not minimum <= value <= maximum:
        raise ValueError(f"{variant.value} 频率必须在 {minimum}~{maximum} MHz 范围内")
    code = int((value - minimum) / FREQUENCY_STEP_MHZ)
    if not 0 <= code <= MAX_FREQUENCY_CODE:
        raise ValueError("频率码必须在 0~70 范围内")
    return code, minimum + FREQUENCY_STEP_MHZ * code


def make_beam_setting(
    frequency_mhz: float,
    theta: float,
    phi: float,
    variant: Union[DeviceVariant, str],
) -> BeamSetting:
    """先量化频率，再使用实际频率计算波束码。"""

    variant = DeviceVariant.coerce(variant)
    code, actual = quantize_frequency(frequency_mhz, variant)
    beam_h, beam_v = calculate_beam_values(theta, phi, actual, is_tx=variant.is_tx)
    return BeamSetting(float(frequency_mhz), actual, code, beam_h, beam_v)


def _pack_beam_payload(freq: int, beam_h: int, beam_v: int) -> bytes:
    """按协议位布局打包频率码和两个 12 bit 波束码为 4 字节。"""
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


def unpack_beam_payload(payload: bytes) -> tuple[int, int, int]:
    """解析 4 字节波束配置，返回 ``(频率码, BeamH, BeamV)``。"""

    if len(payload) < 4:
        raise ValueError("波束配置 payload 长度不足")
    freq_code = payload[0]
    beam_v = (payload[1] << 4) | ((payload[2] >> 4) & 0x0F)
    beam_h = ((payload[2] & 0x0F) << 8) | payload[3]
    return freq_code, beam_h, beam_v


def build_tx_beam_command(freq: int, beam_h: int, beam_v: int) -> bytes:
    """构造 AFDT1024 波束设置的数据区。"""
    return _pack_beam_payload(freq, beam_h, beam_v)


def build_rx_beam_command(freq: int, beam_h: int, beam_v: int) -> bytes:
    """构造 AFDR1024 波束设置的数据区。"""
    return _pack_beam_payload(freq, beam_h, beam_v)


def build_enable_command(enable: bool) -> bytes:
    """构造阵列开关数据区，返回 4 字节受控协议载荷。"""
    value = ARRAY_ENABLE if enable else ARRAY_DISABLE
    return bytes([(value >> 8) & 0xFF, value & 0xFF, 0xFF, 0xFF])


def build_polarization_command(polarization: int) -> bytes:
    """构造极化数据区；低位 ``0/1`` 分别表示 LHCP/RHCP。"""
    return b"\x00\x00\x00" + bytes([int(polarization) & 0x01])


def build_pa_enable_command(enable: bool) -> bytes:
    """构造仅 AFDT1024 使用的推动 PA 开关数据区。"""
    return b"\x00\x00\x00" + bytes([PA_ENABLE if enable else PA_DISABLE])


def build_phase_cal_command(phase_offset: int) -> bytes:
    """构造相位校准数据区，并将协议值夹紧到 0~63。"""
    phase_offset = max(0, min(63, int(phase_offset)))
    return b"\x00\x00\x00" + bytes([phase_offset & 0x3F])


def build_id_update_command(new_id: int) -> bytes:
    """构造子阵 ID 更新数据区；调用方负责校验目标 ID 范围。"""
    return b"\x00" + bytes([int(new_id) & 0xFF])


def build_status_query_command() -> bytes:
    """返回查询 1 的空数据区。"""
    return b""


# 兼容受控协议文档中的细分函数名称。
build_tx_enable_command = build_enable_command
build_rx_enable_command = build_enable_command
build_tx_polarization_command = build_polarization_command
build_rx_polarization_command = build_polarization_command
build_rx_phase_cal_command = build_phase_cal_command
build_rx_status_query_command = build_status_query_command


def build_tx_beam_frame(device_id: int, freq: int, beam_h: int, beam_v: int) -> bytes:
    """构造发送端 AFDT1024 波束设置完整帧。"""
    return build_frame(device_id, ADDR_TX_BEAM, build_tx_beam_command(freq, beam_h, beam_v))


def build_tx_enable_frame(device_id: int, enable: bool) -> bytes:
    """构造发送端 AFDT1024 阵列使能完整帧。"""
    return build_frame(device_id, ADDR_TX_ENABLE, build_enable_command(enable))


def build_tx_polarization_frame(device_id: int, polarization: int) -> bytes:
    """构造发送端 AFDT1024 极化设置完整帧。"""
    return build_frame(device_id, ADDR_TX_POLARIZATION, build_polarization_command(polarization))


def build_pa_enable_frame(device_id: int, enable: bool) -> bytes:
    """构造发送端 AFDT1024 推动 PA 使能完整帧。"""
    return build_frame(device_id, ADDR_PA_ENABLE, build_pa_enable_command(enable))


def build_phase_cal_frame(device_id: int, phase_offset: int) -> bytes:
    """构造发送端 AFDT1024 相位校准完整帧。"""
    return build_frame(device_id, ADDR_PHASE_CAL, build_phase_cal_command(phase_offset))


def build_id_update_frame(device_id: int, new_id: int) -> bytes:
    """构造 ID 更新完整帧；广播更新时 ``device_id`` 应为 ``0``。"""
    return build_frame(device_id, ADDR_ID_UPDATE, build_id_update_command(new_id))


def build_status_query_frame(device_id: int) -> bytes:
    """构造发送端 AFDT1024 查询 1 完整帧。"""
    return build_frame(device_id, ADDR_STATUS_QUERY)


def build_rx_beam_frame(device_id: int, freq: int, beam_h: int, beam_v: int) -> bytes:
    """构造接收端 AFDR1024 波束设置完整帧。"""
    return build_frame(device_id, ADDR_RX_BEAM, build_rx_beam_command(freq, beam_h, beam_v))


def build_rx_enable_frame(device_id: int, enable: bool) -> bytes:
    """构造接收端 AFDR1024 阵列使能完整帧。"""
    return build_frame(device_id, ADDR_RX_ENABLE, build_enable_command(enable))


def build_rx_polarization_frame(device_id: int, polarization: int) -> bytes:
    """构造接收端 AFDR1024 极化设置完整帧。"""
    return build_frame(device_id, ADDR_RX_POLARIZATION, build_polarization_command(polarization))


def build_rx_phase_cal_frame(device_id: int, phase_offset: int) -> bytes:
    """构造接收端 AFDR1024 相位校准完整帧。"""
    return build_frame(device_id, ADDR_RX_PHASE_CAL, build_phase_cal_command(phase_offset))


def build_rx_status_query_frame(device_id: int) -> bytes:
    """构造接收端 AFDR1024 查询 1 完整帧。"""
    return build_frame(device_id, ADDR_RX_STATUS_QUERY)


def build_tx_beam_query_frame(device_id: int) -> bytes:
    """构造发送端 AFDT1024 查询 2 完整帧。"""
    return build_frame(device_id, ADDR_TX_BEAM_QUERY)


def build_rx_beam_query_frame(device_id: int) -> bytes:
    """构造接收端 AFDR1024 查询 2 完整帧。"""
    return build_frame(device_id, ADDR_RX_BEAM_QUERY)


def build_beam_frame(
    device_id: int,
    setting: BeamSetting,
    variant: Union[DeviceVariant, str],
) -> bytes:
    """根据 AFDT1024/AFDR1024 变体选择波束帧地址并构造完整帧。"""
    variant = DeviceVariant.coerce(variant)
    builder = build_tx_beam_frame if variant.is_tx else build_rx_beam_frame
    return builder(device_id, setting.frequency_code, setting.beam_h, setting.beam_v)


def build_enable_frame(
    device_id: int,
    enable: bool,
    variant: Union[DeviceVariant, str],
) -> bytes:
    """根据 AFDT1024/AFDR1024 变体构造阵列使能完整帧。"""
    variant = DeviceVariant.coerce(variant)
    builder = build_tx_enable_frame if variant.is_tx else build_rx_enable_frame
    return builder(device_id, enable)


def build_polarization_frame(
    device_id: int,
    polarization: int,
    variant: Union[DeviceVariant, str],
) -> bytes:
    """根据 AFDT1024/AFDR1024 变体构造极化设置完整帧。"""
    variant = DeviceVariant.coerce(variant)
    builder = build_tx_polarization_frame if variant.is_tx else build_rx_polarization_frame
    return builder(device_id, polarization)


def build_query_frames(
    device_id: int,
    variant: Union[DeviceVariant, str],
) -> tuple[bytes, bytes]:
    """构建查询 1/查询 2 帧。"""

    variant = DeviceVariant.coerce(variant)
    if variant.is_tx:
        return build_status_query_frame(device_id), build_tx_beam_query_frame(device_id)
    return build_rx_status_query_frame(device_id), build_rx_beam_query_frame(device_id)


def _code_to_deg(code: int) -> float:
    """将 12 bit 补码波控值还原为等效相位角，单位为度。"""
    code &= BEAM_CODE_MASK
    if code < 2048:
        return code * 180.0 / 2048.0
    return (code - 4096) * 180.0 / 2048.0


def beam_code_to_angle(
    beam_v: int,
    beam_h: int,
    freq: float,
    is_tx: bool = True,
) -> tuple[float, float]:
    """由波束码反算 ``(theta, phi)``，角度单位为度。

    ``is_tx`` 决定采用 AFDT1024 或 AFDR1024 的标称频率。
    """
    f0 = TX_F0 if is_tx else RX_F0
    ux = _code_to_deg(beam_h)
    uy = _code_to_deg(beam_v)
    factor = 180.0 * (freq / f0) if f0 else 0.0
    if factor == 0:
        return 0.0, 0.0
    sine = max(0.0, min(1.0, math.hypot(ux, uy) / factor))
    return math.degrees(math.asin(sine)), math.degrees(math.atan2(uy, ux))


def parse_beam_query_response(
    payload: bytes,
    is_tx: bool = True,
) -> Tuple[Optional[dict[str, Any]], str]:
    """解析查询 2 的 16 字节有效载荷。

    Args:
        payload: 不含指令地址的响应数据区。
        is_tx: ``True`` 按 AFDT1024 频率基准换算，否则按 AFDR1024。

    Returns:
        成功时返回字段字典和 ``"OK"``；长度不足时返回 ``(None, 原因)``。
    """
    if len(payload) < 16:
        return None, "波束参数响应长度不足"
    pol = payload[7] & 0x01
    en_row = (payload[8] << 8) | payload[9]
    freq_code = payload[12]
    beam_v = (payload[13] << 4) | ((payload[14] >> 4) & 0x0F)
    beam_h = ((payload[14] & 0x0F) << 8) | payload[15]
    freq_mhz = (TX_MIN_FREQ if is_tx else RX_MIN_FREQ) + FREQUENCY_STEP_MHZ * freq_code
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


def parse_status_response(payload: bytes) -> Tuple[Optional[dict[str, Any]], str]:
    """解析 AFDT1024 查询 1 响应，电压单位 V、温度单位摄氏度。"""
    if len(payload) < 6:
        return None, "TX状态响应长度不足"
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


def parse_rx_status_response(payload: bytes) -> Tuple[Optional[dict[str, Any]], str]:
    """解析 AFDR1024 查询 1 响应，电压单位 V、温度单位摄氏度。"""
    if len(payload) < 5:
        return None, "RX状态响应长度不足"
    return {
        "raw": payload.hex(),
        "rev": payload[0],
        "sys_vcc": payload[1] * 0.1,
        "sys_temp": payload[2] - 80,
        "att_tc": payload[3],
        "mcu_ver": payload[4],
    }, "OK"


def build_tx_status_response_frame(
    device_id: int,
    *,
    rev: int = 0x01,
    state: int = 0x01,
    sys_vcc_raw: int = 0x74,
    sys_temp_raw: int = 0x74,
    att_tc: int = 0x01,
    mcu_ver: int = 0x02,
) -> bytes:
    """构造供模拟器和测试使用的 AFDT1024 查询 1 响应完整帧。"""
    payload = bytes([rev, state, sys_vcc_raw, sys_temp_raw, att_tc, mcu_ver])
    return build_frame(device_id, ADDR_STATUS_QUERY, payload)


def build_rx_status_response_frame(
    device_id: int,
    *,
    rev: int = 0x4A,
    sys_vcc_raw: int = 0x74,
    sys_temp_raw: int = 0x83,
    att_tc: int = 0x04,
    mcu_ver: int = 0x02,
) -> bytes:
    """构造供模拟器和测试使用的 AFDR1024 查询 1 响应完整帧。"""
    payload = bytes([rev, sys_vcc_raw, sys_temp_raw, att_tc, mcu_ver])
    return build_frame(device_id, ADDR_RX_STATUS_QUERY, payload)


def build_beam_query_response_frame(
    device_id: int,
    variant: Union[DeviceVariant, str],
    state: Mapping[str, int],
) -> bytes:
    """按状态映射构造 AFDT1024/AFDR1024 查询 2 响应完整帧。

    ``device_id`` 保持调用方提供的字节值，以便模拟 ``+0x80`` 单阵寻址响应。
    """
    variant = DeviceVariant.coerce(variant)
    pol = int(state.get("pol", 0)) & 0x01
    en_row = int(state.get("en_row", 0)) & 0xFFFF
    freq_code = int(state.get("freq_code", 0)) & 0xFF
    beam_v = int(state.get("beam_v", 0)) & BEAM_CODE_MASK
    beam_h = int(state.get("beam_h", 0)) & BEAM_CODE_MASK
    payload = bytes(
        [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            pol,
            (en_row >> 8) & 0xFF,
            en_row & 0xFF,
            0xFF,
            0xFF,
            freq_code,
            (beam_v >> 4) & 0xFF,
            ((beam_v & 0x0F) << 4) | ((beam_h >> 8) & 0x0F),
            beam_h & 0xFF,
        ]
    )
    addr = ADDR_TX_BEAM_QUERY if variant.is_tx else ADDR_RX_BEAM_QUERY
    return build_frame(device_id, addr, payload)
