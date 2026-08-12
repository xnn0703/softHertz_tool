"""AFD01_QS V1.7 串口协议编解码。

该模块不依赖 Qt 或串口，设备 Driver、模拟器和单元测试共用同一份协议真值。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


FRAME_MAGIC = 0x55
MAX_PAYLOAD = 1024

CMD_NAMES = {
    0x01: "SNR_REPORT",
    0x02: "BEAM_CONFIG",
    0x03: "TRANSMIT_SWITCH",
    0x04: "HEADING_SCAN_ANGLE",
    0x05: "TRACK_MODE",
    0x06: "HEADING_ALIGN_ANGLE",
    0x07: "BEAM_ANGLE_TX",
    0x08: "TLE_CONFIG",
    0x09: "BEAM_ANGLE_RX",
    0x0A: "BEAM_ANGLE_ALL",
    0x0B: "ARRAY_CONFIG",
    0xA0: "REAL_TIME_REPORT",
    0xA1: "ARRAY_STATUS",
}


@dataclass(frozen=True)
class ArrayLevelProfile:
    """一个客户阵列档位及其有效子阵显示参数。

    Attributes:
        level: 0x0B/A1 线协议中的客户档位。
        subarray_edge: 客户可见有效子阵的单边数量。
    """

    level: int
    subarray_edge: int

    @property
    def active_cells(self) -> int:
        """返回该档位有效子阵单元总数。"""

        return self.subarray_edge * self.subarray_edge


# 0x0B/A1 只公开客户档位和有效子阵规模；内部器件布局不进入 UI 或日志语义。
ARRAY_LEVEL_PROFILES = {
    1: ArrayLevelProfile(1, 8),
    2: ArrayLevelProfile(2, 10),
    3: ArrayLevelProfile(3, 12),
    4: ArrayLevelProfile(4, 14),
    5: ArrayLevelProfile(5, 16),
}


def get_array_level_profile(level: int) -> ArrayLevelProfile:
    """查询客户阵列档位的显式 Profile。

    Args:
        level: 0x0B/A1 档位值。

    Returns:
        对应的客户有效子阵 Profile。

    Raises:
        ValueError: 档位不属于 1～5。
    """

    try:
        return ARRAY_LEVEL_PROFILES[level]
    except KeyError:
        raise ValueError(f"阵列档位应为 1~5，实际 {level}") from None


def format_array_level(level: int) -> str:
    """生成客户界面和日志共用的档位说明。

    Args:
        level: 0x0B/A1 档位值。

    Returns:
        例如 ``档位4（14×14子阵）`` 的客户可见文本。
    """

    profile = get_array_level_profile(level)
    return f"档位{profile.level}（{profile.subarray_edge}×{profile.subarray_edge}子阵）"


def checksum(data: bytes) -> int:
    """计算协议体的 16 位无符号累加和。

    Args:
        data: 不含帧头和末尾校验字段的协议字节。

    Returns:
        对 0x10000 取模的校验和。
    """
    return sum(data) & 0xFFFF


def build_frame(command: int, payload: bytes = b"") -> bytes:
    """构建带帧头、大端长度和校验和的完整 QS 帧。

    Args:
        command: uint8 QS 命令号。
        payload: 命令载荷，长度不能超过 ``MAX_PAYLOAD``。

    Returns:
        可直接送入串口的完整协议帧。

    Raises:
        ValueError: 命令号不在 uint8 范围或载荷过长。
    """
    if not 0 <= command <= 0xFF:
        raise ValueError("指令号超出 uint8 范围")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("载荷过长")
    body = bytes([command]) + struct.pack(">H", len(payload)) + payload
    return bytes([FRAME_MAGIC]) + body + struct.pack(">H", checksum(body))


def parse_frame(frame: bytes) -> Tuple[Optional[Dict[str, Any]], str]:
    """校验并解码一个已完整收集的 QS 帧。

    Args:
        frame: 含帧头、长度、载荷和校验和的完整原始帧。

    Returns:
        成功时返回解码字典和 ``OK``；失败时返回 ``None`` 与诊断文本。
    """
    if len(frame) < 6:
        return None, "帧长度不足"
    if frame[0] != FRAME_MAGIC:
        return None, "帧头错误"

    length = int.from_bytes(frame[2:4], "big")
    if length > MAX_PAYLOAD or len(frame) != length + 6:
        return None, "长度不匹配"

    expected = int.from_bytes(frame[-2:], "big")
    actual = checksum(frame[1:-2])
    if expected != actual:
        return None, f"校验和错误: 0x{expected:04X} != 0x{actual:04X}"

    command = frame[1]
    payload = frame[4:-2]
    try:
        decoded = decode_payload(command, payload)
    except (ValueError, struct.error) as exc:
        return None, str(exc)

    return {
        "command": command,
        "name": CMD_NAMES.get(command, f"UNKNOWN_0x{command:02X}"),
        "payload": payload,
        "decoded": decoded,
    }, "OK"


def _require(payload: bytes, length: int, command: int) -> None:
    """确认载荷长度与指定命令的固定格式一致。

    Args:
        payload: 待检查的载荷字节。
        length: 协议规定的精确载荷长度。
        command: 命令号，用于错误诊断。

    Raises:
        ValueError: 载荷长度不匹配。
    """
    if len(payload) != length:
        raise ValueError(f"0x{command:02X} 载荷长度应为 {length}，实际 {len(payload)}")


def decode_payload(command: int, payload: bytes) -> Dict[str, Any]:
    """解码 0x0B、A0、A1 语义字段，或保留其他命令的原始载荷。

    Args:
        command: QS 命令号。
        payload: 已通过帧级校验的命令载荷。

    Returns:
        0x0B 返回档位请求，A0 返回含物理量的字典且角度单位为度，
        A1 只返回当前 TX/RX 客户阵列档位；其他命令返回十六进制载荷。

    Raises:
        ValueError: 0x0B、A0、A1 的固定载荷长度或 A1 档位不正确。
        struct.error: 载荷无法按协议字段解包。
    """
    if command == 0xA0:
        _require(payload, 42, command)
        values = struct.unpack(">BhhHffffBBhhhhhBBBI", payload)
        keys = (
            "gps_lock",
            "lon",
            "lat",
            "alt",
            "rx_freq",
            "tx_freq",
            "rx_lo",
            "tx_lo",
            "power",
            "polar",
            "pitch",
            "roll",
            "heading",
            "theta",
            "phi",
            "mode",
            "tle_mode",
            "status",
            "time",
        )
        decoded = dict(zip(keys, values))
        for key in ("lon", "lat", "pitch", "roll", "heading", "theta", "phi"):
            decoded[key] /= 100.0
        return decoded

    if command == 0x0B:
        _require(payload, 3, command)
        operation, tx_level, rx_level = payload
        tx_profile = ARRAY_LEVEL_PROFILES.get(tx_level)
        rx_profile = ARRAY_LEVEL_PROFILES.get(rx_level)
        return {
            "operation": operation,
            "tx_level": tx_level,
            "rx_level": rx_level,
            "tx_subarray_edge": tx_profile.subarray_edge if tx_profile else None,
            "rx_subarray_edge": rx_profile.subarray_edge if rx_profile else None,
        }

    if command == 0xA1:
        _require(payload, 2, command)
        tx_level, rx_level = payload
        try:
            get_array_level_profile(tx_level)
        except ValueError:
            raise ValueError(f"0xA1 TX 档位应为 1~5，实际 {tx_level}") from None
        try:
            get_array_level_profile(rx_level)
        except ValueError:
            raise ValueError(f"0xA1 RX 档位应为 1~5，实际 {rx_level}") from None
        return {
            "tx_level": tx_level,
            "rx_level": rx_level,
        }

    # 控制指令仅需保留原始载荷，方便日志、模拟器和后续扩展观察。
    return {"hex": payload.hex(" ").upper()}


def build_snr_report(snr: float, indicator: int, power: int, reboot: int) -> bytes:
    """构建 0x01 SNR 与电源/重启状态上报帧。

    Args:
        snr: 信噪比浮点值。
        indicator: uint8 指示值。
        power: uint8 电源状态。
        reboot: uint8 重启状态。

    Returns:
        按大端字段编码且带校验和的完整 QS 帧。
    """
    return build_frame(0x01, struct.pack(">fBBB", snr, indicator, power, reboot))


def build_beam_config(lon_deg: float, polar: int, rx_freq: float, tx_freq: float) -> bytes:
    """构建 0x02 卫星经度、极化和收发频率配置帧。

    Args:
        lon_deg: 卫星经度，单位为度，编码精度 0.01 度。
        polar: uint8 极化值。
        rx_freq: 接收频率，单位 MHz。
        tx_freq: 发射频率，单位 MHz。

    Returns:
        完整 QS 帧。

    Raises:
        ValueError: 经度超出 -180 至 180 度。
    """
    lon = round(lon_deg * 100)
    if not -18000 <= lon <= 18000:
        raise ValueError("卫星经度必须在 -180~180°")
    return build_frame(0x02, struct.pack(">hBff", lon, polar, rx_freq, tx_freq))


def build_u8_command(command: int, value: int) -> bytes:
    """构建载荷为单个 uint8 的控制帧。

    Args:
        command: QS 命令号。
        value: 要编码的 uint8 值。

    Returns:
        完整 QS 帧。

    Raises:
        ValueError: value 不在 uint8 范围内。
    """
    if not 0 <= value <= 0xFF:
        raise ValueError("参数超出 uint8 范围")
    return build_frame(command, struct.pack("B", value))


def build_angle_command(command: int, angle_deg: float) -> bytes:
    """构建以 0.01 度编码的航向角控制帧。

    Args:
        command: QS 命令号。
        angle_deg: 角度，单位为度，范围 0 至 360。

    Returns:
        完整 QS 帧。

    Raises:
        ValueError: 角度超出协议范围。
    """
    value = round(angle_deg * 100)
    if not 0 <= value <= 36000:
        raise ValueError("角度必须在 0~360°")
    return build_frame(command, struct.pack(">H", value))


def build_beam_angle(command: int, theta_deg: float, phi_deg: float) -> bytes:
    """构建 TX、RX 或共同波束角命令。

    Args:
        command: 0x07（TX）、0x09（RX）或 0x0A（共同）。
        theta_deg: 俯仰角，单位为度，范围 0 至 90。
        phi_deg: 方位角，单位为度，范围 0 至 360。

    Returns:
        以 0.01 度大端编码的完整 QS 帧。

    Raises:
        ValueError: 命令号或角度范围非法。
    """
    theta = round(theta_deg * 100)
    phi = round(phi_deg * 100)
    if command not in (0x07, 0x09, 0x0A):
        raise ValueError("无效的波束角指令")
    if not 0 <= theta <= 9000 or not 0 <= phi <= 36000:
        raise ValueError("波束角范围应为 theta 0~90°，phi 0~360°")
    return build_frame(command, struct.pack(">HH", theta, phi))


def build_tle(line1: str, line2: str) -> bytes:
    """构建 0x08 固定 69 ASCII 字节双行 TLE 配置帧。

    Args:
        line1: 第一行 TLE。
        line2: 第二行 TLE。

    Returns:
        完整 QS 帧；不足 69 字节的行以空格补齐。

    Raises:
        UnicodeEncodeError: 输入包含非 ASCII 字符。
        ValueError: 任一行超过 69 个 ASCII 字节。
    """
    def fixed(line: str) -> bytes:
        """把单行 TLE 转为定长 ASCII 字段。

        Args:
            line: 待编码的单行 TLE。

        Returns:
            右侧空格补齐到 69 字节的 ASCII 字段。

        Raises:
            UnicodeEncodeError: 输入包含非 ASCII 字符。
            ValueError: 编码结果超过 69 字节。
        """
        encoded = line.encode("ascii", errors="strict")
        if len(encoded) > 69:
            raise ValueError("TLE 单行不能超过 69 个 ASCII 字符")
        return encoded.ljust(69, b" ")

    return build_frame(0x08, fixed(line1) + fixed(line2))


def build_array_query() -> bytes:
    """构建 0x0B 有效子阵档位查询帧。

    Returns:
        操作码为查询、TX/RX 字段均为零的完整 QS 帧。
    """
    return build_frame(0x0B, b"\x00\x00\x00")


def build_array_set(tx_level: Optional[int], rx_level: Optional[int]) -> bytes:
    """构建 0x0B TX/RX 有效子阵档位设置帧。

    Args:
        tx_level: TX 档位 1～5；``None`` 编码为 0xFF，表示保持当前值。
        rx_level: RX 档位 1～5；``None`` 编码为 0xFF，表示保持当前值。

    Returns:
        操作码为设置的完整 QS 帧。

    Raises:
        ValueError: 非保持值不属于档位 1～5。
    """
    tx = 0xFF if tx_level is None else tx_level
    rx = 0xFF if rx_level is None else rx_level
    if tx != 0xFF and tx not in ARRAY_LEVEL_PROFILES:
        raise ValueError("TX 阵列档位只支持 1~5")
    if rx != 0xFF and rx not in ARRAY_LEVEL_PROFILES:
        raise ValueError("RX 阵列档位只支持 1~5")
    return build_frame(0x0B, bytes([1, tx, rx]))


def describe(parsed: Optional[Dict[str, Any]], message: str) -> str:
    """为帧监视器生成简短、低开销的可读摘要。

    Args:
        parsed: 已解码帧；解析失败时为 ``None``。
        message: 帧解析结果或错误文本。

    Returns:
        0x0B、A0、A1 的关键状态摘要，或普通命令名/错误文本。
    """
    if parsed is None:
        return message
    command = parsed["command"]
    decoded = parsed["decoded"]
    if command == 0xA0:
        return (
            f"A0 GPS={decoded['gps_lock']} mode={decoded['mode']} "
            f"beam=({decoded['theta']:.2f},{decoded['phi']:.2f}) status=0x{decoded['status']:02X}"
        )
    if command == 0x0B:
        if decoded["operation"] == 0:
            return "0B 查询阵列档位"
        if decoded["operation"] != 1:
            return f"0B 非法操作码 0x{decoded['operation']:02X}"

        def request_value_text(level: int) -> str:
            """把设置字段转换为客户档位、保持或非法值说明。"""

            if level == 0xFF:
                return "保持"
            try:
                return format_array_level(level)
            except ValueError:
                return f"非法档位({level})"

        return (
            f"0B 设置 TX={request_value_text(decoded['tx_level'])} "
            f"RX={request_value_text(decoded['rx_level'])}"
        )
    if command == 0xA1:
        return (
            f"A1 当前 TX={format_array_level(decoded['tx_level'])} "
            f"RX={format_array_level(decoded['rx_level'])}"
        )
    return parsed["name"]
