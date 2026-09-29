"""KuR512B（Ku 波段 512 单元接收子阵，无变频）控制协议实现。

本模块的帧头、地址、字段位宽、校验和波束算法均来自受控原件
``docs/protocols/controlled-originals/KuR512B(无变频)控制接口协议_V3.1_20260511.pdf``。
``kur512`` 与 ``afdtr1024`` 帧头一致但字段位宽与命令集不同，不得共用协议常量。
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional, Tuple, Union

from soft_hertz_tool.devices.kur512.models import BeamSetting, Polarity


FRAME_HEADER = b"\x50\x53\x41"  # "PSA"

# 命令地址
ADDR_RX_BEAM = 0x90
ADDR_RX_ENABLE = 0x91
ADDR_RX_PHASE_CAL = 0x97
ADDR_ID_UPDATE = 0x20
ADDR_STATUS_QUERY = 0x9C

# 0x91 响应回显配置地址集合
CONFIG_ECHO_ADDRS = {
    ADDR_RX_BEAM,
    ADDR_RX_ENABLE,
    ADDR_RX_PHASE_CAL,
    ADDR_ID_UPDATE,
}

# 状态查询响应地址映射（只有一个变体，保留扩展空间）
STATUS_RETURN_ADDRS = {ADDR_STATUS_QUERY: "RX"}

# 命令可读名称
ADDR_NAMES = {
    ADDR_RX_BEAM: "RX 波束",
    ADDR_RX_ENABLE: "RX 阵列使能",
    ADDR_RX_PHASE_CAL: "RX 相位校准",
    ADDR_ID_UPDATE: "ID 更新",
    ADDR_STATUS_QUERY: "RX 状态查询",
}

# 物理量与位宽
MIN_FREQUENCY_MHZ = 10700
MAX_FREQUENCY_MHZ = 12750
FREQUENCY_STEP_MHZ = 50
MAX_FREQUENCY_CODE = 41

RX_F0 = 12500  # 标称频率 (MHz)

BEAM_CODE_RANGE = 4096
BEAM_CODE_MASK = 0x0FFF

# 极化字节取值
POL_LINEAR_MAX = 180
POL_LHCP = 254
POL_RHCP = 255

# 阵列使能 16 bit（受控原件 D27~D12 位布局）；低 12 bit 固定为 0xFFF
RX_EN_ROW_MASK = 0xFFFF
RX_EN_HIGH_BITS = 0xFFF

ARRAY_ENABLE = 0xFFFF
ARRAY_DISABLE = 0x0000

# 整板相位校准
PHASE_CAL_MIN = 0
PHASE_CAL_MAX = 63
PHASE_CAL_STEP_DEG = 5.625

# 默认极化（线极化 0°）
DEFAULT_POLARITY_VALUE = 0


def command_name(addr: int) -> str:
    """返回指令地址的人类可读名称；未知地址按十六进制显示。"""
    return ADDR_NAMES.get(addr, f"0x{addr:02X}")


def calculate_checksum(data: bytes) -> int:
    """返回除 CheckSum 外所有字节求和的低 8 位。"""
    return sum(data) & 0xFF


def build_frame(device_id: int, addr: int, payload: bytes = b"") -> bytes:
    """构建 ``PSA | ID | LEN | payload | ADDR | CheckSum`` 完整帧。

    Args:
        device_id: 目标 ID，范围 0x00..0xFF。
        addr: 命令地址，0x00..0xFF。
        payload: 不含末尾 ADDR 的数据字节；与 ADDR 拼成 LEN 计数字段。

    Raises:
        ValueError: 设备 ID、地址或数据长度越界。
    """
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
    """解析配置回显或查询返回帧；payload 不含末尾指令地址。

    Returns:
        ``(None, reason)`` 当帧头/长度/校验错误；
        ``(dict, "OK")`` 成功时字典包含 ``device_id/addr/payload``。
    """
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
    f0: float = RX_F0,
) -> tuple[int, int]:
    """根据角度与实际工作频率计算 ``(BeamH, BeamV)``。

    与 AFDR1024 公式一致，但 f0 不同；不在此处硬编码，便于测试覆盖。
    """
    theta_rad = math.radians(theta)
    phi_rad = math.radians(phi)
    ux = 180.0 * (freq / f0) * math.sin(theta_rad) * math.cos(phi_rad)
    uy = 180.0 * (freq / f0) * math.sin(theta_rad) * math.sin(phi_rad)
    return angle_to_code_12bit(ux), angle_to_code_12bit(uy)


def quantize_frequency(frequency_mhz: float) -> tuple[int, int]:
    """按 50 MHz 网格量化频率，返回 ``(频率码, 实际频率 MHz)``。"""
    value = float(frequency_mhz)
    if not math.isfinite(value):
        raise ValueError("频率必须是有限数值")
    if not MIN_FREQUENCY_MHZ <= value <= MAX_FREQUENCY_MHZ:
        raise ValueError(f"频率必须在 {MIN_FREQUENCY_MHZ}~{MAX_FREQUENCY_MHZ} MHz 范围内")
    code = int((value - MIN_FREQUENCY_MHZ) / FREQUENCY_STEP_MHZ)
    if not 0 <= code <= MAX_FREQUENCY_CODE:
        raise ValueError("频率码必须在 0~41 范围内")
    return code, MIN_FREQUENCY_MHZ + FREQUENCY_STEP_MHZ * code


def _polarity_to_byte(polarity: Polarity, value: int) -> int:
    """根据 Polarity 枚举得到构帧用的极化字节。"""
    if polarity is Polarity.LHCP:
        return POL_LHCP
    if polarity is Polarity.RHCP:
        return POL_RHCP
    if not 0 <= int(value) <= POL_LINEAR_MAX:
        raise ValueError("线极化角度必须在 0..180 范围内")
    return int(value)


def _pack_beam_payload(freq: int, pol: int, beam_h: int, beam_v: int) -> bytes:
    """按协议位布局打包 freq + pol + BeamV/H 为 5 字节。"""
    freq &= 0xFF
    pol &= 0xFF
    beam_v &= BEAM_CODE_MASK
    beam_h &= BEAM_CODE_MASK
    return bytes(
        [
            freq,
            pol,
            (beam_v >> 4) & 0xFF,
            ((beam_v & 0x0F) << 4) | ((beam_h >> 8) & 0x0F),
            beam_h & 0xFF,
        ]
    )


def unpack_beam_payload(payload: bytes) -> tuple[int, int, int, int]:
    """解析 5 字节波束配置，返回 ``(freq_code, pol_byte, beam_h, beam_v)``。"""
    if len(payload) < 5:
        raise ValueError("波束配置 payload 长度不足")
    freq_code = payload[0]
    pol_byte = payload[1]
    beam_v = (payload[2] << 4) | ((payload[3] >> 4) & 0x0F)
    beam_h = ((payload[3] & 0x0F) << 8) | payload[4]
    return freq_code, pol_byte, beam_h, beam_v


def build_beam_command(
    freq: int,
    polarity: Polarity,
    pol_value: int,
    beam_h: int,
    beam_v: int,
) -> bytes:
    """构造 KuR512B 波束（含 POL）数据区。"""
    pol_byte = _polarity_to_byte(polarity, pol_value)
    return _pack_beam_payload(freq, pol_byte, beam_h, beam_v)


def build_enable_command(enable: bool) -> bytes:
    """构造阵列使能数据区；16 bit en_row + 12 bit 0xFFF（4 字节）。

    按受控原件 D31..D28 reserved、D27..D12 RX_EN_ROW[15:0]、D11..D0 0xFFF 打包。
    """
    en_row = ARRAY_ENABLE if enable else ARRAY_DISABLE
    return bytes(
        [
            (en_row >> 12) & 0x0F,
            (en_row >> 4) & 0xFF,
            ((en_row & 0x0F) << 4) | ((RX_EN_HIGH_BITS >> 8) & 0x0F),
            RX_EN_HIGH_BITS & 0xFF,
        ]
    )


def build_phase_cal_command(phase_offset: int) -> bytes:
    """构造整板相位校准数据区；6 bit PS_Align，步进 5.625°（4 字节）。"""
    if not PHASE_CAL_MIN <= int(phase_offset) <= PHASE_CAL_MAX:
        raise ValueError("PS_Align 必须在 0..63 范围内")
    return bytes([0, 0, 0, int(phase_offset) & 0x3F])


def build_id_update_command(new_id: int) -> bytes:
    """构造子阵 ID 更新数据区；调用方负责校验目标 ID 范围。"""
    return b"\x00" + bytes([int(new_id) & 0xFF])


def build_status_query_command() -> bytes:
    """返回 0x9C 状态查询的空数据区。"""
    return b""


def make_beam_setting(
    frequency_mhz: float,
    theta: float,
    phi: float,
    polarity: Polarity = Polarity.LINEAR,
    pol_value: int = 0,
) -> BeamSetting:
    """先量化频率，再使用实际频率计算波束码。"""
    code, actual = quantize_frequency(frequency_mhz)
    beam_h, beam_v = calculate_beam_values(theta, phi, actual)
    return BeamSetting(
        requested_frequency_mhz=float(frequency_mhz),
        actual_frequency_mhz=actual,
        frequency_code=code,
        beam_h=beam_h,
        beam_v=beam_v,
        polarity=polarity,
        pol_value=int(pol_value) if polarity is Polarity.LINEAR else 0,
    )


def build_beam_frame(device_id: int, setting: BeamSetting) -> bytes:
    """构造 KuR512B 波束设置完整帧。"""
    return build_frame(
        device_id,
        ADDR_RX_BEAM,
        build_beam_command(
            setting.frequency_code,
            setting.polarity,
            setting.pol_value,
            setting.beam_h,
            setting.beam_v,
        ),
    )


def build_enable_frame(device_id: int, enable: bool) -> bytes:
    """构造 KuR512B 阵列使能完整帧。"""
    return build_frame(device_id, ADDR_RX_ENABLE, build_enable_command(enable))


def build_phase_cal_frame(device_id: int, phase_offset: int) -> bytes:
    """构造 KuR512B 整板相位校准完整帧。"""
    return build_frame(device_id, ADDR_RX_PHASE_CAL, build_phase_cal_command(phase_offset))


def build_id_update_frame(device_id: int, new_id: int) -> bytes:
    """构造 ID 更新完整帧；广播更新时 ``device_id`` 应为 ``0``。"""
    return build_frame(device_id, ADDR_ID_UPDATE, build_id_update_command(new_id))


def build_status_query_frame(device_id: int) -> bytes:
    """构造 KuR512B 状态查询完整帧。"""
    return build_frame(device_id, ADDR_STATUS_QUERY)


def parse_status_response(payload: bytes) -> Tuple[Optional[dict[str, Any]], str]:
    """解析 KuR512B 状态查询响应。

    支持两种载荷格式：
        - 4 字节：``[Rev, SysVcc, SysTemp, MCU_VER]``（设备实测格式，无尾部 ADDR）
        - 5 字节：``[Rev, SysVcc, SysTemp, MCU_VER, 0x9C]``（V3.1 PDF 受控原件格式）

    返回字段：
        - ``rev``: 原始 Rev 字节
        - ``sys_vcc``: 实际电压（V），单位 0.1 V
        - ``sys_temp``: 实际温度（℃），原始值减 80
        - ``mcu_ver``: 系统版本号
    """
    if len(payload) == 5 and payload[-1] == ADDR_STATUS_QUERY:
        payload = payload[:4]
    if len(payload) < 4:
        return None, "KuR512B 状态响应长度不足"
    return {
        "raw": payload.hex(),
        "rev": payload[0],
        "sys_vcc": payload[1] * 0.1,
        "sys_temp": payload[2] - 80,
        "mcu_ver": payload[3],
    }, "OK"


def build_status_response_frame(
    device_id: int,
    *,
    rev: int = 0,
    sys_vcc_raw: int = 119,
    sys_temp_raw: int = 110,
    mcu_ver: int = 1,
) -> bytes:
    """构造供模拟器和测试使用的 KuR512B 状态查询响应完整帧。"""
    payload = bytes([rev & 0xFF, sys_vcc_raw & 0xFF, sys_temp_raw & 0xFF, mcu_ver & 0xFF])
    return build_frame(device_id, ADDR_STATUS_QUERY, payload)


def parse_polarity(pol_byte: int) -> tuple[Polarity, int]:
    """从协议极化字节反解为 ``(Polarity, value)``。"""
    value = int(pol_byte) & 0xFF
    if value == POL_LHCP:
        return Polarity.LHCP, 0
    if value == POL_RHCP:
        return Polarity.RHCP, 0
    return Polarity.LINEAR, value


def parse_beam_response(payload: bytes) -> Tuple[Optional[dict[str, Any]], str]:
    """解析配置回显中的 5 字节波束字段，便于面板回读验证。"""
    try:
        freq_code, pol_byte, beam_h, beam_v = unpack_beam_payload(payload)
    except ValueError as exc:
        return None, str(exc)
    polarity, pol_value = parse_polarity(pol_byte)
    freq_mhz = MIN_FREQUENCY_MHZ + FREQUENCY_STEP_MHZ * freq_code
    return {
        "freq_code": freq_code,
        "freq_mhz": freq_mhz,
        "pol_byte": pol_byte,
        "polarity": polarity,
        "pol_value": pol_value,
        "beam_h": beam_h,
        "beam_v": beam_v,
    }, "OK"


def beam_code_to_angle(
    beam_v: int,
    beam_h: int,
    freq: float,
    f0: float = RX_F0,
) -> tuple[float, float]:
    """由波束码反算 ``(theta, phi)``，角度单位为度。"""
    if not f0:
        return 0.0, 0.0
    factor = 180.0 * (freq / f0)

    def to_deg(code: int) -> float:
        """将 12 bit 补码波控值还原为等效相位角，单位为度。"""
        code &= BEAM_CODE_MASK
        if code < 2048:
            return code * 180.0 / 2048.0
        return (code - 4096) * 180.0 / 2048.0

    ux = to_deg(beam_h)
    uy = to_deg(beam_v)
    sine = max(0.0, min(1.0, math.hypot(ux, uy) / factor))
    return math.degrees(math.asin(sine)), math.degrees(math.atan2(uy, ux))


# 旧字段名兼容（与 AFDR1024 共享的 beam 命令别名，方便 Driver 内部统一）。
build_rx_beam_command = build_beam_command
build_rx_enable_command = build_enable_command
build_rx_phase_cal_command = build_phase_cal_command
build_rx_status_query_command = build_status_query_command


__all__ = [
    "ADDR_ID_UPDATE",
    "ADDR_NAMES",
    "ADDR_RX_BEAM",
    "ADDR_RX_ENABLE",
    "ADDR_RX_PHASE_CAL",
    "ADDR_STATUS_QUERY",
    "ARRAY_DISABLE",
    "ARRAY_ENABLE",
    "BEAM_CODE_MASK",
    "BEAM_CODE_RANGE",
    "CONFIG_ECHO_ADDRS",
    "DEFAULT_POLARITY_VALUE",
    "FRAME_HEADER",
    "FREQUENCY_STEP_MHZ",
    "MAX_FREQUENCY_CODE",
    "MAX_FREQUENCY_MHZ",
    "MIN_FREQUENCY_MHZ",
    "PHASE_CAL_MAX",
    "PHASE_CAL_MIN",
    "PHASE_CAL_STEP_DEG",
    "POL_LHCP",
    "POL_LINEAR_MAX",
    "POL_RHCP",
    "RX_EN_HIGH_BITS",
    "RX_EN_ROW_MASK",
    "RX_F0",
    "STATUS_RETURN_ADDRS",
    "angle_to_code_12bit",
    "beam_code_to_angle",
    "build_beam_command",
    "build_beam_frame",
    "build_enable_command",
    "build_enable_frame",
    "build_frame",
    "build_id_update_command",
    "build_id_update_frame",
    "build_phase_cal_command",
    "build_phase_cal_frame",
    "build_rx_beam_command",
    "build_rx_enable_command",
    "build_rx_phase_cal_command",
    "build_rx_status_query_command",
    "build_status_query_command",
    "build_status_query_frame",
    "build_status_response_frame",
    "calculate_beam_values",
    "calculate_checksum",
    "command_name",
    "make_beam_setting",
    "parse_beam_response",
    "parse_polarity",
    "parse_response",
    "parse_status_response",
    "quantize_frequency",
    "unpack_beam_payload",
]
