"""AFD01_QS V1.6 串口协议编解码。

该模块不依赖 Qt 或串口，设备 Driver、模拟器和单元测试共用同一份协议真值。
"""

from __future__ import annotations

import struct
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

# KA256 的阵列规模与有效行列位掩码。
ARRAY_MASKS = {8: 0xFF, 7: 0xFE, 6: 0x7E, 5: 0x7C, 4: 0x3C}


def checksum(data: bytes) -> int:
    """计算协议 16 bit 累加和。"""
    return sum(data) & 0xFFFF


def build_frame(command: int, payload: bytes = b"") -> bytes:
    """构建完整 QS 帧。"""
    if not 0 <= command <= 0xFF:
        raise ValueError("指令号超出 uint8 范围")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("载荷过长")
    body = bytes([command]) + struct.pack(">H", len(payload)) + payload
    return bytes([FRAME_MAGIC]) + body + struct.pack(">H", checksum(body))


def parse_frame(frame: bytes) -> Tuple[Optional[Dict[str, Any]], str]:
    """校验并解码一个完整帧。"""
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
    if len(payload) != length:
        raise ValueError(f"0x{command:02X} 载荷长度应为 {length}，实际 {len(payload)}")


def decode_payload(command: int, payload: bytes) -> Dict[str, Any]:
    """解码设备主动上报的 A0/A1 载荷。"""
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
        result = dict(zip(keys, values))
        for key in ("lon", "lat", "pitch", "roll", "heading", "theta", "phi"):
            result[key] /= 100.0
        return result

    if command == 0xA1:
        _require(payload, 5, command)
        result, tx_size, rx_size, power_flags, apply_flags = payload
        return {
            "result": result,
            "tx_size": tx_size,
            "rx_size": rx_size,
            "power_flags": power_flags,
            "apply_flags": apply_flags,
        }

    # 控制指令仅需保留原始载荷，方便日志、模拟器和后续扩展观察。
    return {"hex": payload.hex(" ").upper()}


def build_snr_report(snr: float, indicator: int, power: int, reboot: int) -> bytes:
    return build_frame(0x01, struct.pack(">fBBB", snr, indicator, power, reboot))


def build_beam_config(lon_deg: float, polar: int, rx_freq: float, tx_freq: float) -> bytes:
    lon = round(lon_deg * 100)
    if not -18000 <= lon <= 18000:
        raise ValueError("卫星经度必须在 -180~180°")
    return build_frame(0x02, struct.pack(">hBff", lon, polar, rx_freq, tx_freq))


def build_u8_command(command: int, value: int) -> bytes:
    if not 0 <= value <= 0xFF:
        raise ValueError("参数超出 uint8 范围")
    return build_frame(command, struct.pack("B", value))


def build_angle_command(command: int, angle_deg: float) -> bytes:
    value = round(angle_deg * 100)
    if not 0 <= value <= 36000:
        raise ValueError("角度必须在 0~360°")
    return build_frame(command, struct.pack(">H", value))


def build_beam_angle(command: int, theta_deg: float, phi_deg: float) -> bytes:
    theta = round(theta_deg * 100)
    phi = round(phi_deg * 100)
    if command not in (0x07, 0x09, 0x0A):
        raise ValueError("无效的波束角指令")
    if not 0 <= theta <= 9000 or not 0 <= phi <= 36000:
        raise ValueError("波束角范围应为 theta 0~90°，phi 0~360°")
    return build_frame(command, struct.pack(">HH", theta, phi))


def build_tle(line1: str, line2: str) -> bytes:
    def fixed(line: str) -> bytes:
        encoded = line.encode("ascii", errors="strict")
        if len(encoded) > 69:
            raise ValueError("TLE 单行不能超过 69 个 ASCII 字符")
        return encoded.ljust(69, b" ")

    return build_frame(0x08, fixed(line1) + fixed(line2))


def build_array_query() -> bytes:
    return build_frame(0x0B, b"\x00\x00\x00")


def build_array_set(tx_size: Optional[int], rx_size: Optional[int]) -> bytes:
    tx = 0xFF if tx_size is None else tx_size
    rx = 0xFF if rx_size is None else rx_size
    if tx != 0xFF and tx not in ARRAY_MASKS:
        raise ValueError("TX 阵列规模只支持 4~8")
    if rx != 0xFF and rx not in ARRAY_MASKS:
        raise ValueError("RX 阵列规模只支持 4~8")
    return build_frame(0x0B, bytes([1, tx, rx]))


def describe(parsed: Optional[Dict[str, Any]], message: str) -> str:
    """为帧监视器生成简短、低开销摘要。"""
    if parsed is None:
        return message
    command = parsed["command"]
    decoded = parsed["decoded"]
    if command == 0xA0:
        return (
            f"A0 GPS={decoded['gps_lock']} mode={decoded['mode']} "
            f"beam=({decoded['theta']:.2f},{decoded['phi']:.2f}) status=0x{decoded['status']:02X}"
        )
    if command == 0xA1:
        return (
            f"A1 result=0x{decoded['result']:02X} TX={decoded['tx_size']} RX={decoded['rx_size']} "
            f"power=0x{decoded['power_flags']:02X} apply=0x{decoded['apply_flags']:02X}"
        )
    return parsed["name"]
