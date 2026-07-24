"""KaUDC004A 固定帧协议。

该模块只负责字节帧的构建、校验和字段解码，不依赖串口或 Qt。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


FRAME_HEADER = b"\xAA\x55\x0C\x00"
FRAME_SIZE = 12
PAYLOAD_SIZE = 6

CMD_RESET = 0x0A
CMD_VERSION = 0x0B
CMD_TEMP_QUERY = 0x0C
CMD_RX_LO = 0x0E
CMD_TX_LO = 0x12
CMD_LO_QUERY = 0x13
CMD_TX_ATT = 0x14
CMD_RX_ATT = 0x15
CMD_ATT_QUERY = 0x16

ATT_MIN = 0
ATT_MAX = 300
ATT_STEP = 0.1

COMMAND_NAMES = {
    CMD_RESET: "复位",
    CMD_VERSION: "版本回读",
    CMD_TEMP_QUERY: "温度查询",
    CMD_RX_LO: "接收本振设置",
    CMD_TX_LO: "发射本振设置",
    CMD_LO_QUERY: "本振查询",
    CMD_TX_ATT: "发射衰减设置",
    CMD_RX_ATT: "接收衰减设置",
    CMD_ATT_QUERY: "衰减查询",
}


def crc16_ccitt(data: bytes, poly: int = 0x1021, init_val: int = 0xFFFF) -> int:
    """计算 CRC-16/CCITT，覆盖帧头和 payload。"""
    crc = init_val
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ poly
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def build_frame(payload: bytes) -> bytes:
    """用 6 字节 payload 构建 12 字节完整帧。"""
    if len(payload) != PAYLOAD_SIZE:
        raise ValueError(f"payload 必须为 {PAYLOAD_SIZE} 字节，实际为 {len(payload)} 字节")
    body = FRAME_HEADER + bytes(payload)
    return body + crc16_ccitt(body).to_bytes(2, "big")


def parse_response(frame: bytes) -> Tuple[Optional[bytes], str]:
    """校验完整响应帧，成功时返回 6 字节 payload。"""
    if len(frame) != FRAME_SIZE:
        return None, f"帧长度错误: 期望{FRAME_SIZE}字节, 收到{len(frame)}字节"
    if frame[:2] != FRAME_HEADER[:2]:
        return None, "帧头错误: 期望 AA 55"
    if frame[2:4] != FRAME_HEADER[2:4]:
        return None, f"帧头错误: 期望 0C 00, 收到 {frame[2:4].hex()}"

    crc_received = int.from_bytes(frame[-2:], "big")
    crc_calculated = crc16_ccitt(frame[:-2])
    if crc_received != crc_calculated:
        return None, f"CRC错误: 计算={crc_calculated:04X}, 接收={crc_received:04X}"
    return frame[4:10], "OK"


def command_name(command: int) -> str:
    """返回便于 UI 与日志显示的命令名称。"""
    return COMMAND_NAMES.get(command, f"0x{command:02X}")


def decode_temperature(byte_value: int) -> int:
    """返回温度响应原始字节。

    当前固件联调约定不应用历史上的 ``0x80 = 0 ℃`` 偏移规则；
    只有协议经硬件确认后才能改变此行为。
    """
    if not 0 <= byte_value <= 0xFF:
        raise ValueError("温度原始值必须在 0..255 范围内")
    return byte_value


def decode_att_db(value: int) -> float:
    """将协议衰减整数换算为 dB。"""
    return value * ATT_STEP


def _build_empty_command(command: int) -> bytes:
    return build_frame(bytes([command, 0x00, 0x00, 0x00, 0x00, 0x00]))


def _uint16_bytes(value: int, field_name: str) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"{field_name} 必须在 0..65535 范围内")
    return value.to_bytes(2, "big")


def build_reset_frame() -> bytes:
    return _build_empty_command(CMD_RESET)


def build_version_query_frame() -> bytes:
    return _build_empty_command(CMD_VERSION)


def build_temp_query_frame() -> bytes:
    return _build_empty_command(CMD_TEMP_QUERY)


def build_rx_lo_frame(freq_mhz: int) -> bytes:
    return build_frame(bytes([CMD_RX_LO, 0x00, 0x00, 0x00]) + _uint16_bytes(freq_mhz, "接收本振频率"))


def build_tx_lo_frame(freq_mhz: int) -> bytes:
    return build_frame(bytes([CMD_TX_LO, 0x00, 0x00, 0x00]) + _uint16_bytes(freq_mhz, "发射本振频率"))


def build_lo_query_frame() -> bytes:
    return _build_empty_command(CMD_LO_QUERY)


def _validate_attenuation(value: int) -> None:
    if not ATT_MIN <= value <= ATT_MAX:
        raise ValueError(f"衰减值必须在 {ATT_MIN}..{ATT_MAX} 范围内")


def build_tx_att_frame(value: int) -> bytes:
    _validate_attenuation(value)
    return build_frame(bytes([CMD_TX_ATT, 0x00, 0x00, 0x00]) + value.to_bytes(2, "big"))


def build_rx_att_frame(value: int) -> bytes:
    _validate_attenuation(value)
    return build_frame(bytes([CMD_RX_ATT, 0x00, 0x00, 0x00]) + value.to_bytes(2, "big"))


def build_att_query_frame() -> bytes:
    return _build_empty_command(CMD_ATT_QUERY)


def parse_response_data(payload: bytes) -> Dict[str, Any]:
    """把已通过 CRC 校验的 6 字节 payload 解码为结构化状态。"""
    if len(payload) != PAYLOAD_SIZE:
        raise ValueError(f"payload 必须为 {PAYLOAD_SIZE} 字节，实际为 {len(payload)} 字节")

    command = payload[0]
    result: Dict[str, Any] = {"cmd": command, "command_name": command_name(command)}

    if command == CMD_RESET:
        result["status"] = "reset_complete" if payload[1] == 0xFF else "reset_failed"
    elif command == CMD_VERSION:
        result["version"] = payload[1]
    elif command == CMD_TEMP_QUERY:
        raw_value = decode_temperature(payload[1])
        result["temperature_raw"] = raw_value
        result["temperature"] = raw_value
    elif command == CMD_RX_LO:
        result["rx_lo"] = int.from_bytes(payload[4:6], "big")
    elif command == CMD_TX_LO:
        result["tx_lo"] = int.from_bytes(payload[4:6], "big")
    elif command == CMD_LO_QUERY:
        lock_status = payload[5]
        result.update(
            {
                "tx_lo": int.from_bytes(payload[1:3], "big"),
                "rx_lo": int.from_bytes(payload[3:5], "big"),
                "lock_status": lock_status,
                "rx_locked": bool(lock_status & 0x01),
                "tx_locked": bool(lock_status & 0x02),
                "ref_locked": bool(lock_status & 0x04),
            }
        )
    elif command == CMD_TX_ATT:
        value = int.from_bytes(payload[4:6], "big")
        result.update({"tx_att": value, "tx_att_db": decode_att_db(value)})
    elif command == CMD_RX_ATT:
        value = int.from_bytes(payload[4:6], "big")
        result.update({"rx_att": value, "rx_att_db": decode_att_db(value)})
    elif command == CMD_ATT_QUERY:
        tx_value = int.from_bytes(payload[1:3], "big")
        rx_value = int.from_bytes(payload[3:5], "big")
        result.update(
            {
                "tx_att": tx_value,
                "rx_att": rx_value,
                "tx_att_db": decode_att_db(tx_value),
                "rx_att_db": decode_att_db(rx_value),
            }
        )
    return result


class KaUDCProtocol:
    """便于 Driver 注入或外部统一引用的协议门面。"""

    build_reset_frame = staticmethod(build_reset_frame)
    build_version_query_frame = staticmethod(build_version_query_frame)
    build_temp_query_frame = staticmethod(build_temp_query_frame)
    build_rx_lo_frame = staticmethod(build_rx_lo_frame)
    build_tx_lo_frame = staticmethod(build_tx_lo_frame)
    build_lo_query_frame = staticmethod(build_lo_query_frame)
    build_tx_att_frame = staticmethod(build_tx_att_frame)
    build_rx_att_frame = staticmethod(build_rx_att_frame)
    build_att_query_frame = staticmethod(build_att_query_frame)
    parse_response = staticmethod(parse_response)
    parse_response_data = staticmethod(parse_response_data)
