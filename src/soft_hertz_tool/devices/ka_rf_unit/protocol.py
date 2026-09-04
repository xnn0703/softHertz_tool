"""KA_RF_UNIT 串口协议编解码（不依赖 Qt 或 pyserial）。

帧格式（参见 ``Ka波段射频单元控制接口协议-20260803``）：

* 物理层：RS422、8N1、无流控；默认 460800，可配 921600。
* 帧头 ``50 53 41``（ASCII ``PSA``） + 协议版本（当前 ``0x01``）+ 命令字 +
  载荷长度 + 载荷 + CRC-16/CCITT-FALSE。
* 字节序：大端（网络字节序）。
* CRC 计算范围：帧头开始到 payload 末；末端 CRC 字段不参与计算。
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


FRAME_MAGIC = b"PSA"  # 50 53 41
PROTOCOL_VERSION = 0x01
FRAME_HEADER_SIZE = 6
FRAME_CRC_SIZE = 2
MAX_FRAME_SIZE = 256
MAX_PAYLOAD = MAX_FRAME_SIZE - FRAME_HEADER_SIZE - FRAME_CRC_SIZE

# 控制命令号。
CMD_SET_CONV_FREQ = 0x10
CMD_SET_CONV_ATT = 0x11
CMD_SET_TX_EN = 0x12
CMD_SET_RX_EN = 0x13
CMD_SET_BEAM = 0x14
CMD_SET_EXT_REF = 0x15
CMD_SET_REPORT_HZ = 0x20
CMD_STATUS_REPORT = 0x30

# 响应命令号（命令字 | 0x80）。
RES_SET_CONV_FREQ = 0x90
RES_SET_CONV_ATT = 0x91
RES_SET_TX_EN = 0x92
RES_SET_RX_EN = 0x93
RES_SET_BEAM = 0x94
RES_SET_EXT_REF = 0x95
RES_SET_REPORT_HZ = 0xA0
RES_STATUS_REPORT = 0xB0

# 结果码。
RESULT_OK = 0x00
RESULT_BAD_VERSION = 0x01
RESULT_BAD_LENGTH = 0x02
RESULT_OUT_OF_RANGE = 0x03
RESULT_UNSUPPORTED = 0x04

# 0x14 目标掩码。
BEAM_TARGET_TX = 0x01
BEAM_TARGET_RX = 0x02
BEAM_TARGET_ALL = BEAM_TARGET_TX | BEAM_TARGET_RX

# 0x10 极化。
POLAR_LEFT_CIRCLE = 0  # 左旋圆极化
POLAR_RIGHT_CIRCLE = 1  # 右旋圆极化

# 0x14 波束原始码范围。
BEAM_CODE_MAX = 4095
BEAM_CODE_RANGE = 4096  # 12 bit 补码回绕
# 0x10 极化与 0x14 波束角度（度）边界。
THETA_MIN_DEG = 0.0
THETA_MAX_DEG = 90.0
PHI_MIN_DEG = 0.0
PHI_MAX_DEG = 360.0
# 0x14 波束换算中心频率（MHz），与协议文档中 Tx_f0/Rx_f0 一致。
TX_BEAM_F0 = 30000
RX_BEAM_F0 = 20270
# 0x10 射频（MHz）允许范围。
RX_RF_MIN_MHZ = 17700
RX_RF_MAX_MHZ = 21200
TX_RF_MIN_MHZ = 27500
TX_RF_MAX_MHZ = 31000

# 0x30 STATUS_REPORT 固定 payload 长度。
STATUS_REPORT_PAYLOAD_LEN = 43
# STATUS_REPORT payload 字段及大端格式串。
_STATUS_REPORT_FORMAT = ">IHBBBH" + "H" * 12 + "hhh" + "BB"

# 字段名（用于 STATUS_REPORT 解码）。
STATUS_REPORT_FIELDS = (
    "uptime_ms",
    "conv_lock_mask",
    "pa_enable",
    "tx_enable",
    "rx_enable",
    "status_report_rate_hz",
    "unit_sw",
    "rx_rf_mhz",
    "rx_lo_mhz",
    "tx_rf_mhz",
    "tx_lo_mhz",
    "rx_conv_att_x10",
    "tx_conv_att_x10",
    "ext_ref_mhz",
    "conv_temp_x10",
    "tx_array_temp_x10",
    "rx_array_temp_x10",
    "tx_beam_h",
    "tx_beam_v",
    "rx_beam_h",
    "rx_beam_v",
    "rx_polar",
    "tx_polar",
)

CMD_NAMES = {
    CMD_SET_CONV_FREQ: "SET_CONV_FREQ",
    CMD_SET_CONV_ATT: "SET_CONV_ATT",
    CMD_SET_TX_EN: "SET_TX_EN",
    CMD_SET_RX_EN: "SET_RX_EN",
    CMD_SET_BEAM: "SET_BEAM",
    CMD_SET_EXT_REF: "SET_EXT_REF",
    CMD_SET_REPORT_HZ: "SET_REPORT_HZ",
    CMD_STATUS_REPORT: "STATUS_REPORT",
}

RESULT_NAMES = {
    RESULT_OK: "OK",
    RESULT_BAD_VERSION: "BAD_VERSION",
    RESULT_BAD_LENGTH: "BAD_LENGTH",
    RESULT_OUT_OF_RANGE: "OUT_OF_RANGE",
    RESULT_UNSUPPORTED: "UNSUPPORTED",
}


@dataclass(frozen=True)
class LockMask:
    """``conv_lock_mask`` 位含义。

    Attributes:
        ref_valid: bit0，外部参考是否有效。
        rx_lo_lock: bit1，RX LO 是否锁定。
        tx_lo_lock: bit2，TX LO 是否锁定。
    """

    ref_valid: bool
    rx_lo_lock: bool
    tx_lo_lock: bool


def decode_lock_mask(mask: int) -> LockMask:
    """解码 ``conv_lock_mask`` 16 位字段。

    Args:
        mask: 协议上报的 16 位锁位掩码。

    Returns:
        三位关键状态；其余保留位忽略。
    """

    return LockMask(
        ref_valid=bool(mask & 0x0001),
        rx_lo_lock=bool(mask & 0x0002),
        tx_lo_lock=bool(mask & 0x0004),
    )


def crc16_ccitt_false(data: bytes) -> int:
    """计算 CRC-16/CCITT-FALSE。

    算法参数：``init=0xFFFF``、``refin/refout=false``、``xorout=0x0000``、
    多项式 ``0x1021``。参考向量：``ASCII "123456789" -> 0x29B1``。

    Args:
        data: 待校验字节。

    Returns:
        16 位 CRC 值。
    """

    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def be16_read(data: bytes, offset: int = 0) -> int:
    """从大端字节读取 uint16。

    Args:
        data: 输入字节。
        offset: 起始偏移。

    Returns:
        解码后的主机字节序 uint16。

    Raises:
        IndexError: 偏移越界。
    """

    return (data[offset] << 8) | data[offset + 1]


def be16_write(value: int) -> bytes:
    """将 uint16 编码为大端 2 字节。

    Args:
        value: 主机字节序 uint16。

    Returns:
        大端字节串。

    Raises:
        ValueError: 不在 0..0xFFFF 范围。
    """

    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"uint16 越界: {value}")
    return bytes([(value >> 8) & 0xFF, value & 0xFF])


def be32_write(value: int) -> bytes:
    """将 uint32 编码为大端 4 字节。

    Args:
        value: 主机字节序 uint32。

    Returns:
        大端字节串。

    Raises:
        ValueError: 不在 0..0xFFFFFFFF 范围。
    """

    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"uint32 越界: {value}")
    return bytes([(value >> 24) & 0xFF, (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF])


def _validate_mhz(value: int, *, minimum: int, maximum: int, name: str) -> None:
    """确认 MHz 字段在闭区间范围内，否则抛出诊断。"""
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 应在 {minimum}~{maximum} MHz，实际 {value}")


def rx_rf_valid(rf_mhz: int) -> bool:
    """接收 RF 是否在协议允许频段。

    Args:
        rf_mhz: RF 频率，单位 MHz。

    Returns:
        ``17700~21200 MHz``（含端点）。
    """

    return 17700 <= rf_mhz <= 21200


def tx_rf_valid(rf_mhz: int) -> bool:
    """发射 RF 是否在协议允许频段。

    Args:
        rf_mhz: RF 频率，单位 MHz。

    Returns:
        ``27500~31000 MHz``（含端点）。
    """

    return 27500 <= rf_mhz <= 31000


def rx_lo_valid(lo_mhz: int) -> bool:
    """接收 LO 是否合法。

    Args:
        lo_mhz: LO 频率，0 表示 AUTO；其它必须为 ``16750~19250`` 偶数 MHz。

    Returns:
        满足自动或范围偶数时为 ``True``。
    """

    if lo_mhz == 0:
        return True
    return 16750 <= lo_mhz <= 19250 and lo_mhz % 2 == 0


def tx_lo_valid(lo_mhz: int) -> bool:
    """发射 LO 是否合法。

    Args:
        lo_mhz: LO 频率，0 表示 AUTO；其它必须为 ``26550~29050`` 偶数 MHz。

    Returns:
        满足自动或范围偶数时为 ``True``。
    """

    if lo_mhz == 0:
        return True
    return 26550 <= lo_mhz <= 29050 and lo_mhz % 2 == 0


def conv_att_valid(att_x10: int) -> bool:
    """变频衰减是否合法。

    Args:
        att_x10: 衰减值，单位 ``0.1 dB``。

    Returns:
        ``0~31.5 dB`` 且步进为 ``0.5 dB`` 时为 ``True``。
    """

    return 0 <= att_x10 <= 315 and att_x10 % 5 == 0


def ext_ref_valid(ref_mhz: int) -> bool:
    """外部参考频率是否合法。

    Args:
        ref_mhz: 外部参考时钟频率。

    Returns:
        10 MHz 或 100 MHz 时为 ``True``。
    """

    return ref_mhz in (10, 100)


def encode_frame(
    command: int,
    payload: bytes = b"",
    *,
    protocol_version: int = PROTOCOL_VERSION,
) -> bytes:
    """编码完整 KA_RF_UNIT 帧（含 magic、CRC）。

    Args:
        command: 命令字。
        payload: 命令载荷；为空时允许 ``None`` 字节。
        protocol_version: 写入帧头的协议版本，默认 ``0x01``。

    Returns:
        可直接送入串口的完整协议帧。

    Raises:
        ValueError: 命令字、载荷长度或协议版本越界。
    """

    if not 0 <= command <= 0xFF:
        raise ValueError(f"命令字越界: 0x{command:X}")
    if not 0 <= protocol_version <= 0xFF:
        raise ValueError(f"协议版本越界: 0x{protocol_version:X}")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"载荷过长: {len(payload)} > {MAX_PAYLOAD}")
    payload_bytes = bytes(payload)
    length = len(payload_bytes)
    header = FRAME_MAGIC + bytes([protocol_version, command, length])
    body = header + payload_bytes
    crc = crc16_ccitt_false(body)
    return body + be16_write(crc)


def parse_response(frame: bytes) -> Tuple[Optional[Dict[str, Any]], str]:
    """校验并解码一个完整 KA_RF_UNIT 响应帧。

    Args:
        frame: 含帧头、长度、载荷和 CRC 的完整原始字节。

    Returns:
        成功时返回含 ``command``、``name``、``payload``、``decoded`` 的字典与
        ``"OK"``；失败时返回 ``None`` 与诊断文本。
    """

    if len(frame) < FRAME_HEADER_SIZE + FRAME_CRC_SIZE:
        return None, f"帧长度不足 {len(frame)}"
    if frame[:3] != FRAME_MAGIC:
        return None, "帧头错误"
    protocol_version = frame[3]
    if protocol_version != PROTOCOL_VERSION:
        return None, f"协议版本不匹配: 0x{protocol_version:02X}"
    command = frame[4]
    length = frame[5]
    expected = FRAME_HEADER_SIZE + length + FRAME_CRC_SIZE
    if expected > MAX_FRAME_SIZE or len(frame) != expected:
        return None, f"长度不匹配: 期望 {expected} 实际 {len(frame)}"
    payload = frame[FRAME_HEADER_SIZE:FRAME_HEADER_SIZE + length]
    crc_bytes = frame[FRAME_HEADER_SIZE + length:]
    expected_crc = be16_read(crc_bytes, 0)
    actual_crc = crc16_ccitt_false(frame[:FRAME_HEADER_SIZE + length])
    if expected_crc != actual_crc:
        return None, f"CRC 错误: 0x{expected_crc:04X} != 0x{actual_crc:04X}"
    try:
        decoded = decode_payload(command, payload)
    except ValueError as exc:
        return None, str(exc)
    return {
        "command": command,
        "name": CMD_NAMES.get(command, f"UNKNOWN_0x{command:02X}"),
        "payload": payload,
        "decoded": decoded,
    }, "OK"


def decode_payload(command: int, payload: bytes) -> Dict[str, Any]:
    """按命令字解码载荷。

    Args:
        command: 命令字。
        payload: 已通过帧级校验的载荷字节。

    Returns:
        含 ``result`` 或字段的字典；STATUS_REPORT 返回 ``STATUS_REPORT_FIELDS``
        全部字段及 ``conv_lock`` 三位状态；控制响应返回 ``result`` 字段；
        其它命令返回 ``hex`` 文本。

    Raises:
        ValueError: 固定载荷长度不匹配或结果码非法。
    """

    if command == CMD_STATUS_REPORT:
        if len(payload) != STATUS_REPORT_PAYLOAD_LEN:
            raise ValueError(
                f"0x{command:02X} 载荷长度应为 {STATUS_REPORT_PAYLOAD_LEN}，实际 {len(payload)}"
            )
        values = struct.unpack(_STATUS_REPORT_FORMAT, payload)
        decoded = dict(zip(STATUS_REPORT_FIELDS, values))
        decoded["conv_lock"] = decode_lock_mask(decoded["conv_lock_mask"])
        return decoded

    if command in (RES_SET_CONV_FREQ, RES_SET_CONV_ATT, RES_SET_TX_EN, RES_SET_RX_EN,
                   RES_SET_BEAM, RES_SET_EXT_REF, RES_SET_REPORT_HZ):
        if len(payload) != 1:
            raise ValueError(f"0x{command:02X} 响应载荷长度应为 1，实际 {len(payload)}")
        result = payload[0]
        if result not in RESULT_NAMES:
            raise ValueError(f"非法结果码 0x{result:02X}")
        return {"result": result, "name": RESULT_NAMES[result]}

    return {"hex": payload.hex(" ").upper()}


def build_set_conv_freq(
    rx_rf_mhz: int,
    rx_lo_mhz: int,
    tx_rf_mhz: int,
    tx_lo_mhz: int,
    rx_polar: int,
    tx_polar: int,
) -> bytes:
    """构建 ``0x10 SET_CONV_FREQ`` 帧。

    Args:
        rx_rf_mhz: 接收 RF 频率，``17700~21200``。
        rx_lo_mhz: 接收 LO 频率，``0 表示 AUTO``，否则 ``16750~19250`` 偶数。
        tx_rf_mhz: 发射 RF 频率，``27500~31000``。
        tx_lo_mhz: 发射 LO 频率，``0 表示 AUTO``，否则 ``26550~29050`` 偶数。
        rx_polar: RX 极化，0=左旋、1=右旋。
        tx_polar: TX 极化，0=左旋、1=右旋。

    Returns:
        完整 ``0x10`` 请求帧。

    Raises:
        ValueError: 任一字段超出协议范围。
    """

    if not rx_rf_valid(rx_rf_mhz):
        raise ValueError(f"RX RF 应在 17700~21200 MHz，实际 {rx_rf_mhz}")
    if not tx_rf_valid(tx_rf_mhz):
        raise ValueError(f"TX RF 应在 27500~31000 MHz，实际 {tx_rf_mhz}")
    if not rx_lo_valid(rx_lo_mhz):
        raise ValueError(f"RX LO 应为 0 或 16750~19250 偶数，实际 {rx_lo_mhz}")
    if not tx_lo_valid(tx_lo_mhz):
        raise ValueError(f"TX LO 应为 0 或 26550~29050 偶数，实际 {tx_lo_mhz}")
    if rx_polar not in (POLAR_LEFT_CIRCLE, POLAR_RIGHT_CIRCLE):
        raise ValueError(f"RX 极化应为 0 或 1，实际 {rx_polar}")
    if tx_polar not in (POLAR_LEFT_CIRCLE, POLAR_RIGHT_CIRCLE):
        raise ValueError(f"TX 极化应为 0 或 1，实际 {tx_polar}")

    payload = (
        be16_write(rx_rf_mhz)
        + be16_write(rx_lo_mhz)
        + be16_write(tx_rf_mhz)
        + be16_write(tx_lo_mhz)
        + bytes([rx_polar, tx_polar])
    )
    return encode_frame(CMD_SET_CONV_FREQ, payload)


def build_set_conv_att(rx_att_db: float, tx_att_db: float) -> bytes:
    """构建 ``0x11 SET_CONV_ATT`` 帧。

    Args:
        rx_att_db: RX 衰减，``0.0~31.5 dB``，步进 ``0.5``。
        tx_att_db: TX 衰减，``0.0~31.5 dB``，步进 ``0.5``。

    Returns:
        完整 ``0x11`` 请求帧。

    Raises:
        ValueError: 衰减超出范围或不是 0.5 步进。
    """

    rx_x10 = int(round(rx_att_db * 10))
    tx_x10 = int(round(tx_att_db * 10))
    if not conv_att_valid(rx_x10):
        raise ValueError(f"RX 衰减应为 0~31.5 dB 步进 0.5，实际 {rx_att_db}")
    if not conv_att_valid(tx_x10):
        raise ValueError(f"TX 衰减应为 0~31.5 dB 步进 0.5，实际 {tx_att_db}")
    payload = be16_write(rx_x10) + be16_write(tx_x10)
    return encode_frame(CMD_SET_CONV_ATT, payload)


def build_set_tx_en(enabled: bool) -> bytes:
    """构建 ``0x12 SET_TX_EN`` 帧。

    Args:
        enabled: True 表示开启 TX 阵列。

    Returns:
        完整 ``0x12`` 请求帧。
    """

    return encode_frame(CMD_SET_TX_EN, bytes([1 if enabled else 0]))


def build_set_rx_en(enabled: bool) -> bytes:
    """构建 ``0x13 SET_RX_EN`` 帧。

    Args:
        enabled: True 表示开启 RX 阵列。

    Returns:
        完整 ``0x13`` 请求帧。
    """

    return encode_frame(CMD_SET_RX_EN, bytes([1 if enabled else 0]))


def build_set_beam(
    target_mask: int,
    tx_beam_h: int,
    tx_beam_v: int,
    rx_beam_h: int,
    rx_beam_v: int,
) -> bytes:
    """构建 ``0x14 SET_BEAM`` 帧。

    Args:
        target_mask: bit0=TX、bit1=RX，至少设置一位。
        tx_beam_h: TX BeamH 原始码，``0~4095``。
        tx_beam_v: TX BeamV 原始码，``0~4095``。
        rx_beam_h: RX BeamH 原始码，``0~4095``。
        rx_beam_v: RX BeamV 原始码，``0~4095``。

    Returns:
        完整 ``0x14`` 请求帧。

    Raises:
        ValueError: target_mask 为 0 或任一波束码越界。
    """

    if target_mask & ~BEAM_TARGET_ALL or target_mask == 0:
        raise ValueError(f"target_mask 仅允许 bit0/1，至少 1 位，实际 0x{target_mask:02X}")
    for name, value in (
        ("TX BeamH", tx_beam_h),
        ("TX BeamV", tx_beam_v),
        ("RX BeamH", rx_beam_h),
        ("RX BeamV", rx_beam_v),
    ):
        if not 0 <= value <= BEAM_CODE_MAX:
            raise ValueError(f"{name} 应在 0~{BEAM_CODE_MAX}，实际 {value}")
    payload = bytes([target_mask]) + (
        be16_write(tx_beam_h)
        + be16_write(tx_beam_v)
        + be16_write(rx_beam_h)
        + be16_write(rx_beam_v)
    )
    return encode_frame(CMD_SET_BEAM, payload)


def angle_u_to_code(u: float) -> int:
    """将有限相位 ``u``（度）转换为 12 bit 补码波控值。

    算法与 KA256 V2 固件一致：``lroundf(u * 2048 / 180) mod 4096``。
    半码按远离零方向舍入；相位超过一个半周时仍按 12 bit 协议回绕。

    Args:
        u: 角度，单位度。

    Returns:
        12 bit 补码（0~4095）。

    Raises:
        ValueError: ``u`` 非有限数。
    """

    if not math.isfinite(u):
        raise ValueError(f"相位角必须是有限数，实际 {u}")
    scaled = u * 2048.0 / 180.0
    rounded = math.floor(scaled + 0.5) if scaled >= 0.0 else math.ceil(scaled - 0.5)
    return int(rounded) % BEAM_CODE_RANGE


def compute_beam_pair(
    theta_deg: float,
    phi_deg: float,
    *,
    freq_mhz: float,
    f0: int,
) -> Tuple[int, int]:
    """根据角度和实际工作频率计算 ``(BeamH, BeamV)``。

    协议公式：``u_x = 180 * (f/f0) * sinθ * cosφ``，
    ``u_y = 180 * (f/f0) * sinθ * sinφ``；再由 :func:`angle_u_to_code` 编码。

    Args:
        theta_deg: 离轴角（俯仰），单位度，``0~90``。
        phi_deg: 方位角，单位度，``0~360``。
        freq_mhz: 实际工作载波中心频率，单位 MHz。
        f0: 标称中心频率，TX 为 30000，RX 为 20270。

    Returns:
        ``(BeamH, BeamV)`` 12 bit 补码。

    Raises:
        ValueError: 角度或频率非法。
    """

    if not math.isfinite(theta_deg) or not (THETA_MIN_DEG - 1e-6 <= theta_deg <= THETA_MAX_DEG + 1e-6):
        raise ValueError(f"θ 必须在 {THETA_MIN_DEG}~{THETA_MAX_DEG} 度，实际 {theta_deg}")
    if not math.isfinite(phi_deg) or not (PHI_MIN_DEG - 1e-6 <= phi_deg <= PHI_MAX_DEG + 1e-6):
        raise ValueError(f"φ 必须在 {PHI_MIN_DEG}~{PHI_MAX_DEG} 度，实际 {phi_deg}")
    if not math.isfinite(freq_mhz) or freq_mhz <= 0:
        raise ValueError(f"频率必须为正数，实际 {freq_mhz} MHz")
    if f0 <= 0:
        raise ValueError(f"f0 必须为正数，实际 {f0}")
    ratio = freq_mhz / f0
    theta_rad = math.radians(theta_deg)
    phi_rad = math.radians(phi_deg)
    ux = 180.0 * ratio * math.sin(theta_rad) * math.cos(phi_rad)
    uy = 180.0 * ratio * math.sin(theta_rad) * math.sin(phi_rad)
    return angle_u_to_code(ux), angle_u_to_code(uy)


def build_set_beam_from_angles(
    target_mask: int,
    theta_deg: float,
    phi_deg: float,
    *,
    tx_rf_mhz: float,
    rx_rf_mhz: float,
) -> bytes:
    """按 (θ, φ) 角度与当前载波频率生成 ``0x14 SET_BEAM`` 帧。

    协议公式：``u_x/u_y = 180 * (f/f0) * sinθ * cosφ/sinφ``，再编码为 12 bit 补码。

    Args:
        target_mask: ``0x14`` 目标掩码，bit0=TX、bit1=RX，至少 1 位。
        theta_deg: 离轴角，单位度，``0~90``。
        phi_deg: 方位角，单位度，``0~360``。
        tx_rf_mhz: 发射实际工作载波频率，单位 MHz。
        rx_rf_mhz: 接收实际工作载波频率，单位 MHz。

    Returns:
        完整 ``0x14`` 请求帧。

    Raises:
        ValueError: 目标掩码非法、角度或频率非法、换算结果超 12 bit 补码范围。
    """

    if target_mask & ~BEAM_TARGET_ALL or target_mask == 0:
        raise ValueError(f"target_mask 仅允许 bit0/1，至少 1 位，实际 0x{target_mask:02X}")
    tx_bh, tx_bv = compute_beam_pair(theta_deg, phi_deg, freq_mhz=tx_rf_mhz, f0=TX_BEAM_F0)
    rx_bh, rx_bv = compute_beam_pair(theta_deg, phi_deg, freq_mhz=rx_rf_mhz, f0=RX_BEAM_F0)
    return build_set_beam(target_mask, tx_bh, tx_bv, rx_bh, rx_bv)


def build_set_ext_ref(ref_mhz: int) -> bytes:
    """构建 ``0x15 SET_EXT_REF`` 帧。

    Args:
        ref_mhz: 外部参考频率，仅支持 10 或 100 MHz。

    Returns:
        完整 ``0x15`` 请求帧。

    Raises:
        ValueError: ref_mhz 不在支持列表。
    """

    if not ext_ref_valid(ref_mhz):
        raise ValueError(f"外参仅支持 10 或 100 MHz，实际 {ref_mhz}")
    return encode_frame(CMD_SET_EXT_REF, be16_write(ref_mhz))


def build_set_report_hz(rate_hz: int) -> bytes:
    """构建 ``0x20 SET_REPORT_HZ`` 帧。

    Args:
        rate_hz: 主动上报频率，0~200 Hz；0 表示关闭。

    Returns:
        完整 ``0x20`` 请求帧。

    Raises:
        ValueError: 频率越界。
    """

    if not 0 <= rate_hz <= 200:
        raise ValueError(f"上报频率应在 0~200 Hz，实际 {rate_hz}")
    return encode_frame(CMD_SET_REPORT_HZ, be16_write(rate_hz))


def build_status_report(
    *,
    uptime_ms: int,
    conv_lock_mask: int,
    pa_enable: bool,
    tx_enable: bool,
    rx_enable: bool,
    status_report_rate_hz: int,
    unit_sw: int,
    rx_rf_mhz: int,
    rx_lo_mhz: int,
    tx_rf_mhz: int,
    tx_lo_mhz: int,
    rx_conv_att_x10: int,
    tx_conv_att_x10: int,
    ext_ref_mhz: int,
    conv_temp_x10: int,
    tx_array_temp_x10: int,
    rx_array_temp_x10: int,
    tx_beam_h: int,
    tx_beam_v: int,
    rx_beam_h: int,
    rx_beam_v: int,
    rx_polar: int,
    tx_polar: int,
) -> bytes:
    """构造一个完整的 ``0x30 STATUS_REPORT`` 帧。

    主要供设备侧模拟器和单元测试使用；上位机不会发出该帧。

    Args:
        *: 各字段意义参见 :data:`STATUS_REPORT_FIELDS`。

    Returns:
        完整 ``0x30`` 帧。
    """

    payload = struct.pack(
        _STATUS_REPORT_FORMAT,
        uptime_ms,
        conv_lock_mask,
        1 if pa_enable else 0,
        1 if tx_enable else 0,
        1 if rx_enable else 0,
        status_report_rate_hz,
        unit_sw,
        rx_rf_mhz,
        rx_lo_mhz,
        tx_rf_mhz,
        tx_lo_mhz,
        rx_conv_att_x10,
        tx_conv_att_x10,
        ext_ref_mhz,
        conv_temp_x10,
        tx_array_temp_x10,
        rx_array_temp_x10,
        tx_beam_h,
        tx_beam_v,
        rx_beam_h,
        rx_beam_v,
        rx_polar & 0xFF,
        tx_polar & 0xFF,
    )
    return encode_frame(CMD_STATUS_REPORT, payload)


def describe(parsed: Optional[Dict[str, Any]], message: str) -> str:
    """为报文监视器生成可读、低开销的摘要。

    Args:
        parsed: 已解码帧；解析失败时为 ``None``。
        message: 解析结果或错误文本。

    Returns:
        含命令名/结果或关键状态的短文本。
    """

    if parsed is None:
        return message
    command = parsed["command"]
    decoded = parsed["decoded"]
    if command == CMD_STATUS_REPORT:
        lock = decoded["conv_lock"]
        return (
            f"0x30 uptime={decoded['uptime_ms']}ms "
            f"RX_LO={'L' if lock.rx_lo_lock else 'U'}/"
            f"TX_LO={'L' if lock.tx_lo_lock else 'U'}/"
            f"REF={'V' if lock.ref_valid else 'I'} "
            f"TX={decoded['tx_enable']} RX={decoded['rx_enable']} "
            f"RF={decoded['rx_rf_mhz']}/{decoded['tx_rf_mhz']}MHz"
        )
    if "result" in decoded:
        return f"0x{command:02X} {decoded['name']}"
    return parsed["name"]
