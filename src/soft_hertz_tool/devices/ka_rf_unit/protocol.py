"""KA_RF_UNIT 串口协议编解码（不依赖 Qt 或 pyserial）。

帧格式（设备侧 ``doc/customer_protocol.md``，客户协议 V2 / App 0.3.0）：

* 物理层：RS485、8N1、无流控；460800。
* 帧头 ``50 53 41``（ASCII ``PSA``） + 协议版本（当前 ``0x02``）+ 命令字 +
  载荷长度 + 载荷 + CRC-16/CCITT-FALSE。
* 字节序：大端（网络字节序）。
* CRC 计算范围：帧头开始到 payload 末；末端 CRC 字段不参与计算。
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


FRAME_MAGIC = b"PSA"  # 50 53 41
PROTOCOL_VERSION = 0x02
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
CMD_SET_CONV_FREQ_FREE = 0x16
CMD_STATUS_QUERY = 0x20
RES_STATUS = 0xA0
CMD_SET_PA = 0x40
CMD_SET_TX_IF = 0x41
CMD_SET_RX_IF = 0x42
CMD_SET_ARRAY_MASK = 0x43
CMD_SET_BEAM_ANGLES = 0x44
CMD_GET_INTERNAL_STATUS = 0x45
RES_INTERNAL_STATUS = 0xC5
CMD_SET_ARRAY_ATT = 0x46
CMD_GET_ARRAY_ATT = 0x47
CMD_SET_CONV_ATT_PERSIST = 0x48
RES_CONV_ATT_PERSIST = 0xC8
RES_ARRAY_ATT = 0xC7
ARRAY_ATT_FIELDS = ("result", "snapshot_version", "bf_valid_mask", "tx_bf", "rx_bf",
                    "attenuation_sent_valid_mask", "tx_common", "tx_branch", "rx_common", "rx_branch")
INTERNAL_STATUS_FIELDS = (
    "result", "snapshot_version", "requested_flags", "sent_valid_flags", "sent_value_flags",
    "tx_requested_rows", "tx_requested_cols", "rx_requested_rows", "rx_requested_cols",
    "tx_sent_rows", "tx_sent_cols", "rx_sent_rows", "rx_sent_cols",
)

# 响应命令号（命令字 | 0x80）。
RES_SET_CONV_FREQ = 0x90
RES_SET_CONV_ATT = 0x91
RES_SET_TX_EN = 0x92
RES_SET_RX_EN = 0x93
RES_SET_BEAM = 0x94
RES_SET_EXT_REF = 0x95
RES_SET_CONV_FREQ_FREE = 0x96

# OTA 命令字（V0.3.0；响应 = 请求 | 0x80）。
CMD_OTA_BEGIN = 0x21
CMD_OTA_ABORT = 0x23
CMD_OTA_STATUS = 0x24
RES_OTA_BEGIN = CMD_OTA_BEGIN | 0x80  # 0xA1
RES_OTA_ABORT = CMD_OTA_ABORT | 0x80  # 0xA3
RES_OTA_STATUS = CMD_OTA_STATUS | 0x80  # 0xA4

# OTA 阶段码（设备侧 STATUS 响应汇报）。
OTA_PHASE_IDLE = 0
OTA_PHASE_RECEIVING = 1
OTA_PHASE_VERIFYING = 2
OTA_PHASE_COMMITTING = 3

# App 启动健康状态。
OTA_BOOT_PENDING = 0
OTA_BOOT_STABLE = 1
OTA_BOOT_GRACEFUL_REBOOT = 2

# 结果码。
RESULT_OK = 0x00
RESULT_BAD_VERSION = 0x01
RESULT_BAD_LENGTH = 0x02
RESULT_OUT_OF_RANGE = 0x03
RESULT_UNSUPPORTED = 0x04
RESULT_PERSISTENCE_FAILED = 0x05
RESULT_BUSY = 0x06
RESULT_INVALID_STATE = 0x07
RESULT_CANDIDATE_EXISTS = 0x08
RESULT_IMAGE_MISMATCH = 0x09
RESULT_VERIFY_FAILED = 0x0A
RESULT_IO_FAILED = 0x0B
RESULT_UNAVAILABLE = 0x0C

# OTA 边界常量。
OTA_FILENAME_MAX = 63
OTA_APP_MAX_SIZE = 0xC0000  # 786432 bytes = 768 KiB

# YMODEM 块大小（设备侧 ymodem_cfg 支持 SOH 128 / STX 1024 双包头）。
YMODEM_BLOCK_MIN = 128
YMODEM_BLOCK_MAX = 1024
YMODEM_MAX_RETRANSMIT = 10

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

# V2 0xA0：result + 45 字节缓存快照，温度位于 payload[30:36]。
STATUS_REPORT_PAYLOAD_LEN = 46
_STATUS_REPORT_FORMAT = ">BIHBBB" + "H" * 10 + "hhhHHHHBB"

# 字段名（用于 STATUS_REPORT 解码）。
STATUS_REPORT_FIELDS = (
    "result",
    "uptime_ms",
    "conv_lock_mask",
    "pa_enable",
    "tx_enable",
    "rx_enable",
    "fw_major",
    "fw_minor",
    "fw_revision",
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
    CMD_SET_CONV_FREQ_FREE: "SET_CONV_FREQ_FREE",
    CMD_STATUS_QUERY: "STATUS_QUERY",
    CMD_SET_PA: "INTERNAL_SET_PA",
    CMD_SET_TX_IF: "INTERNAL_SET_TX_IF",
    CMD_SET_RX_IF: "INTERNAL_SET_RX_IF",
    CMD_SET_ARRAY_MASK: "INTERNAL_SET_ARRAY_MASK",
    CMD_SET_BEAM_ANGLES: "INTERNAL_SET_BEAM_ANGLES",
    CMD_GET_INTERNAL_STATUS: "INTERNAL_GET_STATUS",
    CMD_SET_ARRAY_ATT: "INTERNAL_SET_ARRAY_ATT",
    CMD_GET_ARRAY_ATT: "INTERNAL_GET_ARRAY_ATT",
    CMD_SET_CONV_ATT_PERSIST: "SET_CONV_ATT_PERSIST",
}
CMD_NAMES.update({cmd | 0x80: name + "_RESULT" for cmd, name in tuple(CMD_NAMES.items())})
# OTA 命令命名（不参与 _RESULT 后缀派生，因响应命令字独立注册）。
CMD_NAMES[CMD_OTA_BEGIN] = "OTA_BEGIN"
CMD_NAMES[CMD_OTA_ABORT] = "OTA_ABORT"
CMD_NAMES[CMD_OTA_STATUS] = "OTA_STATUS"
CMD_NAMES[RES_OTA_BEGIN] = "OTA_BEGIN_RESP"
CMD_NAMES[RES_OTA_ABORT] = "OTA_ABORT_RESP"
CMD_NAMES[RES_OTA_STATUS] = "OTA_STATUS_RESP"

RESULT_NAMES = {
    RESULT_OK: "OK",
    RESULT_BAD_VERSION: "BAD_VERSION",
    RESULT_BAD_LENGTH: "BAD_LENGTH",
    RESULT_OUT_OF_RANGE: "OUT_OF_RANGE",
    RESULT_UNSUPPORTED: "UNSUPPORTED",
    RESULT_PERSISTENCE_FAILED: "PERSISTENCE_FAILED",
    RESULT_BUSY: "BUSY",
    RESULT_INVALID_STATE: "INVALID_STATE",
    RESULT_CANDIDATE_EXISTS: "CANDIDATE_EXISTS",
    RESULT_IMAGE_MISMATCH: "IMAGE_MISMATCH",
    RESULT_VERIFY_FAILED: "VERIFY_FAILED",
    RESULT_IO_FAILED: "IO_FAILED",
    RESULT_UNAVAILABLE: "UNAVAILABLE",
}

RESULT_MESSAGES = {
    0: "请求成功（不代表物理执行或安装完成）", 1: "协议版本错误，需要 V2 固件",
    2: "载荷长度错误", 3: "参数超范围", 4: "设备或文件类型不支持", 5: "持久化失败",
    6: "设备资源忙", 7: "当前阶段不允许", 8: "已存在候选，请先查询处理",
    9: "镜像名称或大小不匹配", 10: "镜像校验失败", 11: "存储读写失败", 12: "服务尚未就绪",
}


def result_text(result: int) -> str:
    """保留线上结果名，同时给操作员可读中文原因。"""
    return f"{RESULT_NAMES.get(result, str(result))}（{RESULT_MESSAGES.get(result, '未知结果')}）"


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

    用途：KA_RF_UNIT 协议帧层（含 OTA BEGIN/ABORT/STATUS）。
    注意：YMODEM 块层 CRC16 使用 ``crc16_ccitt_ymodem``，初始值为 ``0x0000``。

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


def crc16_ccitt_ymodem(data: bytes) -> int:
    """计算 CRC-16/CCITT（YMODEM 用）。

    算法参数：``init=0x0000``、``refin/refout=false``、``xorout=0x0000``、
    多项式 ``0x1021``。与协议帧层 ``crc16_ccitt_false`` (``init=0xFFFF``) 不同；
    YMODEM 协议族约定初始值为 ``0x0000``。参考向量：``ASCII "123456789" -> 0x31C3``。

    用途：YMODEM block0 与数据块（SOH 128B / STX 1024B payload）末尾 2 字节 CRC16_BE。

    Args:
        data: 待校验字节。

    Returns:
        16 位 CRC 值。
    """

    crc = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def crc32_iso_hdlc(data: bytes) -> int:
    """计算 CRC-32/ISO-HDLC（标准 zlib/PNG/Ethernet）。

    等价 ``zlib.crc32(data) & 0xFFFFFFFF``。
    参考向量：``ASCII "123456789" -> 0xCBF43926``。
    用途：本地诊断及测试参考；V2 无 COMMIT 或预期 CRC32 请求。

    Args:
        data: 完整 .bin 有效字节。

    Returns:
        32 位 CRC 值。
    """

    return zlib.crc32(data) & 0xFFFFFFFF


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
        10 MHz 或 50 MHz 时为 ``True``。
    """

    return ref_mhz in (10, 50)


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

    if command == RES_STATUS:
        if len(payload) == 1 and payload[0] in RESULT_NAMES and payload[0] != RESULT_OK:
            return {"result": payload[0], "name": RESULT_NAMES[payload[0]]}
        if len(payload) != STATUS_REPORT_PAYLOAD_LEN:
            raise ValueError(
                f"0x{command:02X} 载荷长度应为 {STATUS_REPORT_PAYLOAD_LEN}，实际 {len(payload)}"
            )
        values = struct.unpack(_STATUS_REPORT_FORMAT, payload)
        decoded = dict(zip(STATUS_REPORT_FIELDS, values))
        if decoded["result"] != RESULT_OK:
            raise ValueError("状态查询失败响应只能有一个结果字节")
        decoded["name"] = "OK"
        decoded["conv_lock"] = decode_lock_mask(decoded["conv_lock_mask"])
        return decoded

    if command == RES_ARRAY_ATT and len(payload) == 10:
        values = dict(zip(ARRAY_ATT_FIELDS, payload))
        if payload[0] != RESULT_OK or payload[1] != 1 or payload[2] & ~3 or payload[5] & ~3:
            raise ValueError("阵列衰减快照版本或有效位非法")
        for side in range(2):
            if payload[2] & (1 << side) and payload[3 + side] not in (0, 1):
                raise ValueError("阵列 BF 类型非法")
            if payload[5] & (1 << side) and (payload[6 + side * 2] > 16 or payload[7 + side * 2] > 15):
                raise ValueError("阵列衰减发送值越界")
        values["name"] = "OK"
        return values
    if command == RES_INTERNAL_STATUS and len(payload) == 13:
        values = dict(zip(INTERNAL_STATUS_FIELDS, payload))
        if values["result"] != RESULT_OK or values["snapshot_version"] != 1:
            raise ValueError("内部状态结果或快照版本无效")
        if any(values[key] & ~0x1F for key in ("requested_flags", "sent_valid_flags", "sent_value_flags")):
            raise ValueError("内部状态标志含保留位")
        values["name"] = "OK"
        return values
    if command in (RES_SET_CONV_FREQ, RES_SET_CONV_ATT, RES_SET_TX_EN, RES_SET_RX_EN,
                   RES_SET_BEAM, RES_SET_EXT_REF, RES_SET_CONV_FREQ_FREE) or 0xC0 <= command <= 0xC8:
        if len(payload) != 1:
            raise ValueError(f"0x{command:02X} 响应载荷长度应为 1，实际 {len(payload)}")
        result = payload[0]
        if result not in RESULT_NAMES:
            raise ValueError(f"非法结果码 0x{result:02X}")
        if command == RES_INTERNAL_STATUS and result == RESULT_OK:
            raise ValueError("内部状态成功响应必须包含 13 字节快照")
        if command == RES_ARRAY_ATT and result == RESULT_OK:
            raise ValueError("阵列衰减成功响应必须包含 10 字节快照")
        return {"result": result, "name": RESULT_NAMES[result]}

    if command == RES_OTA_STATUS:
        return decode_ota_status_response(payload)
    if command in (RES_OTA_BEGIN, RES_OTA_ABORT):
        if len(payload) != 1:
            raise ValueError(f"0x{command:02X} 响应载荷长度应为 1，实际 {len(payload)}")
        result = payload[0]
        if result not in RESULT_NAMES:
            raise ValueError(f"非法结果码 0x{result:02X}")
        return {"result": result, "name": RESULT_NAMES[result]}

    return {"hex": payload.hex(" ").upper()}


def validate_internal_payload(command: int, payload: bytes) -> int:
    """验证内部请求长度和字段；只验证选中阵面的角度，返回正式 result。"""
    lengths = {CMD_SET_PA: 1, CMD_SET_TX_IF: 1, CMD_SET_RX_IF: 1,
               CMD_SET_ARRAY_MASK: 5, CMD_SET_BEAM_ANGLES: 9, CMD_GET_INTERNAL_STATUS: 0,
               CMD_SET_ARRAY_ATT: 5, CMD_GET_ARRAY_ATT: 0, CMD_SET_CONV_ATT_PERSIST: 4}
    if command not in lengths:
        return RESULT_UNSUPPORTED
    if len(payload) != lengths[command]:
        return RESULT_BAD_LENGTH
    if command == CMD_SET_CONV_ATT_PERSIST:
        return RESULT_OK if all(conv_att_valid(be16_read(payload, offset)) for offset in (0, 2)) else RESULT_OUT_OF_RANGE
    if command in (CMD_GET_INTERNAL_STATUS, CMD_GET_ARRAY_ATT):
        return RESULT_OK
    if command <= CMD_SET_RX_IF:
        return RESULT_OK if payload[0] <= 1 else RESULT_OUT_OF_RANGE
    if payload[0] not in (1, 2, 3):
        return RESULT_OUT_OF_RANGE
    if command == CMD_SET_ARRAY_ATT:
        for side in range(2):
            if payload[0] & (1 << side) and (payload[1 + side * 2] > 16 or payload[2 + side * 2] > 15):
                return RESULT_OUT_OF_RANGE
    if command == CMD_SET_BEAM_ANGLES:
        for side in range(2):
            if payload[0] & (1 << side):
                if be16_read(payload, 1 + side * 4) > 9000 or be16_read(payload, 3 + side * 4) > 35999:
                    return RESULT_OUT_OF_RANGE
    return RESULT_OK


def build_internal_switch(command: int, enabled: bool) -> bytes:
    """构建独立 PA/TX IF/RX IF 开关；非法命令或非 0/1 值抛出 ValueError。"""
    if command not in (CMD_SET_PA, CMD_SET_TX_IF, CMD_SET_RX_IF) or enabled not in (False, True):
        raise ValueError("内部开关仅接受 PA/TX IF/RX IF 和 0/1")
    return encode_frame(command, bytes([int(enabled)]))


def build_array_mask(target: int, tx_rows: int, tx_cols: int, rx_rows: int, rx_cols: int) -> bytes:
    """构建 0x43；行列为各 8 位芯片 mask，保留未选中阵面。"""
    if target not in (1, 2, 3) or any(not isinstance(v, int) or not 0 <= v <= 255
                                   for v in (tx_rows, tx_cols, rx_rows, rx_cols)):
        raise ValueError("阵面目标须为 1/2/3，行列 mask 须为 0..255")
    return encode_frame(CMD_SET_ARRAY_MASK, bytes([target, tx_rows, tx_cols, rx_rows, rx_cols]))


def build_beam_angles(target: int, tx_theta: float, tx_phi: float, rx_theta: float, rx_phi: float) -> bytes:
    """发送 0x44 角度请求；输入度，量化到 0.01°，由固件按当前 RF 换算。"""
    if target not in (1, 2, 3):
        raise ValueError("阵面目标须为 1/2/3")
    values = [0, 0, 0, 0]
    for side, pair in enumerate(((tx_theta, tx_phi), (rx_theta, rx_phi))):
        if not target & (1 << side):
            continue
        for axis, (value, maximum) in enumerate(zip(pair, (90.0, 359.99))):
            if not math.isfinite(value) or not 0 <= value <= maximum:
                raise ValueError("θ 范围 0..90°，φ 范围 0..359.99°")
            values[side * 2 + axis] = math.floor(value * 100 + 0.5)
    return encode_frame(CMD_SET_BEAM_ANGLES, struct.pack(">BHHHH", target, *values))


def build_internal_status_query() -> bytes:
    """查询内部请求和主控最近发送快照，无载荷。"""
    return encode_frame(CMD_GET_INTERNAL_STATUS, b"")


def array_attenuation_valid(bf: int, common_step: int, branch_step: int) -> bool:
    """按 BF0/BF1 校验 0.5 dB 整数步数；未知 BF 返回 False。"""
    return (0 <= branch_step <= 15 and
            ((bf == 0 and common_step in (0, 16)) or (bf == 1 and 0 <= common_step <= 15)))


def build_array_attenuation(target: int, tx_common: float, tx_branch: float,
                            rx_common: float, rx_branch: float) -> bytes:
    """输入 dB 构建 0x46；只检查选中侧，最终 BF 范围由固件校验。"""
    if target not in (1, 2, 3):
        raise ValueError("阵面目标须为 1/2/3")
    values = [0, 0, 0, 0]
    for side, pair in enumerate(((tx_common, tx_branch), (rx_common, rx_branch))):
        if target & (1 << side):
            for axis, value in enumerate(pair):
                if not math.isfinite(value) or not 0 <= value <= (8 if axis == 0 else 7.5) or value * 2 != round(value * 2):
                    raise ValueError("阵列干路 0..8 dB、支路 0..7.5 dB，步进 0.5 dB；干路还须符合实际 BF 类型")
                values[side * 2 + axis] = round(value * 2)
    return encode_frame(CMD_SET_ARRAY_ATT, bytes([target, *values]))


def build_array_attenuation_query() -> bytes:
    """查询当前 BF 类型和最近衰减发送记录。"""
    return encode_frame(CMD_GET_ARRAY_ATT, b"")


def fixed_lo(rf_mhz: int, *, tx: bool) -> int:
    """按客户 RF 分段返回固定 LO（MHz）；非法 RF 抛出 ValueError。"""
    if not (tx_rf_valid(rf_mhz) if tx else rx_rf_valid(rf_mhz)):
        raise ValueError("RF 超出允许范围")
    bands = ((28350, 26550), (29000, 27400), (30000, 28050), (31001, 29050)) if tx else (
        (18200, 16750), (19200, 17250), (20200, 18250), (21201, 19250))
    return next(lo for upper, lo in bands if rf_mhz < upper)


def build_set_conv_freq(
    rx_rf_mhz: int, rx_lo_mhz: int, tx_rf_mhz: int, tx_lo_mhz: int,
    rx_polar: int, tx_polar: int,
) -> bytes:
    """构建 0x10 固定配置；LO 必须匹配 RF 分段，含 AUTO 在内的不匹配值抛出 ValueError。"""
    if rx_lo_mhz != fixed_lo(rx_rf_mhz, tx=False) or tx_lo_mhz != fixed_lo(tx_rf_mhz, tx=True):
        raise ValueError("0x10 LO 必须与 RF 分段匹配，不支持 AUTO；自由配置请用 0x16")
    free_frame = build_set_conv_freq_free(rx_rf_mhz, rx_lo_mhz, tx_rf_mhz, tx_lo_mhz, rx_polar, tx_polar)
    return encode_frame(CMD_SET_CONV_FREQ, free_frame[6:-2])


def build_set_conv_freq_free(
    rx_rf_mhz: int,
    rx_lo_mhz: int,
    tx_rf_mhz: int,
    tx_lo_mhz: int,
    rx_polar: int,
    tx_polar: int,
) -> bytes:
    """构建 ``0x16 SET_CONV_FREQ_FREE`` 帧。

    Args:
        rx_rf_mhz: 接收 RF 频率，``17700~21200``。
        rx_lo_mhz: 接收 LO 频率，``0 表示 AUTO``，否则 ``16750~19250`` 偶数。
        tx_rf_mhz: 发射 RF 频率，``27500~31000``。
        tx_lo_mhz: 发射 LO 频率，``0 表示 AUTO``，否则 ``26550~29050`` 偶数。
        rx_polar: RX 极化，0=左旋、1=右旋。
        tx_polar: TX 极化，0=左旋、1=右旋。

    Returns:
        完整 ``0x16`` 请求帧。

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
    return encode_frame(CMD_SET_CONV_FREQ_FREE, payload)


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


def build_set_conv_att_persist(rx_att_db: float, tx_att_db: float) -> bytes:
    """构建0x48双侧变频衰减保存请求；0..31.5 dB、0.5步进，非法值抛ValueError。"""
    values = (rx_att_db, tx_att_db)
    if any(not 0 <= value <= 31.5 or value * 2 != int(value * 2) for value in values):
        raise ValueError("变频衰减应为0..31.5 dB，步进0.5")
    payload = be16_write(int(rx_att_db * 10)) + be16_write(int(tx_att_db * 10))
    return encode_frame(CMD_SET_CONV_ATT_PERSIST, payload)


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
        ref_mhz: 外部参考频率，仅支持 10 或 50 MHz。

    Returns:
        完整 ``0x15`` 请求帧。

    Raises:
        ValueError: ref_mhz 不在支持列表。
    """

    if not ext_ref_valid(ref_mhz):
        raise ValueError(f"外参仅支持 10 或 50 MHz，实际 {ref_mhz}")
    return encode_frame(CMD_SET_EXT_REF, be16_write(ref_mhz))


def build_status_query() -> bytes:
    """构建 V2 0x20 空载荷状态查询。"""
    return encode_frame(CMD_STATUS_QUERY, b"")


def build_status_report(
    *,
    uptime_ms: int,
    conv_lock_mask: int,
    pa_enable: bool,
    tx_enable: bool,
    rx_enable: bool,
    fw_major: int,
    fw_minor: int,
    fw_revision: int,
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
    """构造一个完整的 ``0xA0 STATUS_REPORT`` 帧。

    主要供设备侧模拟器和单元测试使用；上位机不会发出该帧。

    Args:
        *: 各字段意义参见 :data:`STATUS_REPORT_FIELDS`。

    Returns:
        完整 ``0xA0`` 帧。
    """

    payload = struct.pack(
        _STATUS_REPORT_FORMAT,
        RESULT_OK,
        uptime_ms,
        conv_lock_mask,
        1 if pa_enable else 0,
        1 if tx_enable else 0,
        1 if rx_enable else 0,
        fw_major,
        fw_minor,
        fw_revision,
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
    return encode_frame(RES_STATUS, payload)


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
    if command == RES_STATUS and "uptime_ms" in decoded:
        lock = decoded["conv_lock"]
        return (
            f"0xA0 uptime={decoded['uptime_ms']}ms "
            f"RX_LO={'L' if lock.rx_lo_lock else 'U'}/"
            f"TX_LO={'L' if lock.tx_lo_lock else 'U'}/"
            f"REF={'V' if lock.ref_valid else 'I'} "
            f"TX={decoded['tx_enable']} RX={decoded['rx_enable']} "
            f"RF={decoded['rx_rf_mhz']}/{decoded['tx_rf_mhz']}MHz"
        )
    if "result" in decoded:
        return f"0x{command:02X} {decoded['name']}"
    return parsed["name"]


# ----------------------------------------------------------------------------
# V0.3.0 OTA 客户控制器：payload 编解码 + 完整构帧器。
#
# 设备侧 ``doc/customer_protocol.md`` V2。命令 0x21/0x23/0x24，0x22 未定义。
# STATUS 响应 payload 布局：
#   result(1) + phase(1) + fw_major(2BE) + fw_minor(2BE) + fw_revision(2BE)
#   + app_boot_state(1) + update_requested(1) + candidate_present(1) + last_result(1)
#   + [size(4BE) + crc32(4BE) + name_len(1) + name(N) 仅当 candidate_present==1]
# 多字节字段全部大端；filename 1..63 字节 ASCII 0x21..0x7E，无线上 NUL。
# size 上限 OTA_APP_MAX_SIZE (768 KiB)；结果码 0x00..0x0C。
# ----------------------------------------------------------------------------


def _validate_ota_filename(name: str) -> bytes:
    """校验 OTA 文件名并返回 ASCII 字节。

    规则：1..63 字节、每个字节 0x21..0x7E、禁止 ``/`` 与 ``\\``。

    Raises:
        ValueError: 不满足上述任一规则。
    """

    if not isinstance(name, str):
        raise ValueError("OTA 文件名必须是 str")
    raw = name.encode("ascii")
    if len(raw) == 0 or len(raw) > OTA_FILENAME_MAX:
        raise ValueError(f"OTA 文件名长度应在 1..{OTA_FILENAME_MAX}，实际 {len(raw)}")
    for byte in raw:
        if byte < 0x21 or byte > 0x7E:
            raise ValueError(f"OTA 文件名字节越界 0x{byte:02X}")
        if byte in (0x2F, 0x5C):  # '/' '\\'
            raise ValueError(f"OTA 文件名禁止 '/' 或 '\\\\'")
    return raw


def encode_ota_begin() -> bytes:
    """V2 BEGIN 仅接受空载荷，元数据放入 YMODEM block0。"""
    return b""


def encode_ota_abort() -> bytes:
    """编码 0x23 ABORT 请求 payload：空。"""

    return b""


def encode_ota_status() -> bytes:
    """编码 0x24 STATUS 请求 payload：空。"""

    return b""


def decode_ota_status_response(payload: bytes) -> Dict[str, Any]:
    """解码 V2 A4：12 字节基础快照，可选 size/CRC32/name；所有整数大端。"""
    if not payload or payload[0] not in RESULT_NAMES:
        raise ValueError("OTA STATUS 结果码无效")
    result = payload[0]
    if result != RESULT_OK:
        if len(payload) != 1:
            raise ValueError("OTA STATUS 失败响应只能含结果码")
        return {"result": result, "name": RESULT_NAMES[result]}
    if len(payload) < 12:
        raise ValueError("OTA STATUS 成功响应不足 12 字节")
    if payload[1] > 3 or payload[8] > 2 or payload[9] > 1 or payload[10] > 1:
        raise ValueError("OTA STATUS 阶段或标志非法")
    if payload[11] not in (0, 5, 9, 10, 11):
        raise ValueError("OTA STATUS last_result 非法")
    decoded = dict(zip(
        ("result", "phase", "fw_major", "fw_minor", "fw_revision",
         "app_boot_state", "update_requested", "candidate_present", "last_result"),
        struct.unpack(">BBHHHBBBB", payload[:12])))
    decoded["name"] = "OK"
    if not decoded["candidate_present"]:
        if len(payload) != 12:
            raise ValueError("OTA STATUS 无候选长度必须为 12")
    else:
        if len(payload) < 22 or not 1 <= payload[20] <= OTA_FILENAME_MAX or len(payload) != 21 + payload[20]:
            raise ValueError("OTA STATUS 候选字段长度错误")
        name = payload[21:].decode("ascii")
        _validate_ota_filename(name)
        size, crc = struct.unpack(">II", payload[12:20])
        if not 1 <= size <= OTA_APP_MAX_SIZE:
            raise ValueError("OTA STATUS 候选大小越界")
        decoded.update(size=size, crc32=crc, filename=name, name_len=payload[20])
    return decoded


def build_ota_begin() -> bytes:
    """构造 V2 空 BEGIN，接受后由设备在传输完成时自动安装。"""
    return encode_frame(CMD_OTA_BEGIN, encode_ota_begin())


def build_ota_abort() -> bytes:
    """构 0x23 ABORT 完整帧（带帧头、CRC）。"""

    return encode_frame(CMD_OTA_ABORT, encode_ota_abort())


def build_ota_status() -> bytes:
    """构 0x24 STATUS 完整帧（带帧头、CRC）。"""

    return encode_frame(CMD_OTA_STATUS, encode_ota_status())


def be32_read(data: bytes, offset: int = 0) -> int:
    """从大端字节读取 uint32。"""

    return (
        (data[offset] << 24)
        | (data[offset + 1] << 16)
        | (data[offset + 2] << 8)
        | data[offset + 3]
    )
