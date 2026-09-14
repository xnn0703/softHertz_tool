"""AFD01 Debug RF schema 1；独立于 KA_RF_UNIT PSA 协议。

Debug envelope: AA55 0D command length:u16le data CRC16:u16le EE。
CRC16/CCITT-FALSE 初值 FFFF，覆盖从 AA 到 data 末尾。
请求 data: schema:u8=1, id:u32le, op:u8, target:u8(0 TX/1 RX), a/b/c:f32le。
MHz、dB、角度均使用实际单位，保留参数为 0。状态字段按固件 wire 顺序显式解码。
"""

from __future__ import annotations
import binascii
import math
import struct
from enum import IntEnum

REQUEST, RESPONSE, STATUS = 0x30, 0x31, 0x32


class Op(IntEnum):
    """schema 1 操作编号，与固件 RF 枚举逐项一致。"""

    QUERY = 0
    MANUAL = 1
    CONV_FREQ = 2
    CONV_ATT = 3
    IF = 4
    REFERENCE = 5
    ARRAY_FREQ = 6
    BEAM = 7
    POLAR = 8
    MODE = 9
    ARRAY_ATT = 10
    SIZE = 11
    ARRAY_ENABLE = 12
    PA = 13


RESULTS = {
    0: "请求已接受",
    1: "指令发送成功",
    2: "参数错误",
    3: "命令槽忙",
    4: "型号不支持",
    5: "需要手动模式",
    6: "执行失败",
    7: "服务未就绪",
}


def valid(operation: int, target: int, a: float, b: float, c: float) -> bool:
    """校验 schema 1 的值域和保留字段；与固件 codec 合同一致。"""
    if target not in (0, 1) or not all(math.isfinite(v) for v in (a, b, c)):
        return False

    def integer(v: float, lo: float, hi: float) -> bool:
        """检查数值为指定闭区间内的整数。"""
        return lo <= v <= hi and v == math.floor(v)

    lo, hi = (27500, 31000) if target == 0 else (17700, 21200)
    if operation in (Op.QUERY, Op.MANUAL):
        return target == 0 and a == b == c == 0
    if operation == Op.CONV_FREQ:
        return integer(a, 1, 40000) and integer(b, lo, hi) and c == 0
    if operation == Op.CONV_ATT:
        return integer(a * 2, 0, 63) and b == c == 0
    if operation in (Op.IF, Op.POLAR, Op.ARRAY_ENABLE):
        return integer(a, 0, 1) and b == c == 0
    if operation == Op.PA:
        return target == 0 and integer(a, 0, 1) and b == c == 0
    if operation == Op.REFERENCE:
        return target == 0 and integer(a / 10, 1, 25) and b == c == 0
    if operation == Op.ARRAY_FREQ:
        return integer(a, lo, hi) and b == c == 0
    if operation == Op.BEAM:
        return -90 <= a <= 90 and -360 <= b <= 360 and c == 0
    if operation == Op.MODE:
        return integer(a, 0, 2) and b == c == 0
    if operation == Op.ARRAY_ATT:
        return integer(a * 2, 0, 16) and integer(b * 2, 0, 15) and c == 0
    if operation == Op.SIZE:
        return integer(a / 2, 4, 8) and b == c == 0
    return False


def frame(command: int, data: bytes) -> bytes:
    """生成 Debug 帧；长度不超过本测试协议所需的 160 字节。"""
    if len(data) > 160:
        raise ValueError("载荷过长")
    body = b"\xaa\x55\x0d" + struct.pack("<BH", command, len(data)) + data
    return body + struct.pack("<H", binascii.crc_hqx(body, 0xFFFF)) + b"\xee"


def request(
    request_id: int,
    operation: int,
    target: int = 0,
    a: float = 0,
    b: float = 0,
    c: float = 0,
) -> bytes:
    """构造完整请求，拒绝无效参数及零请求编号。"""
    if not 0 < request_id <= 0xFFFFFFFF or not valid(operation, target, a, b, c):
        raise ValueError("请求参数越界")
    return frame(
        REQUEST, struct.pack("<BIBBfff", 1, request_id, operation, target, a, b, c)
    )


def unpack(raw: bytes) -> tuple[int, bytes]:
    """严格校验一个 UDP 数据报内的一帧；截断、CRC 或尾标记错误均拒绝。"""
    if len(raw) < 9 or raw[:3] != b"\xaa\x55\x0d" or raw[-1] != 0xEE:
        raise ValueError("Debug 帧格式错误")
    command, length = struct.unpack_from("<BH", raw, 3)
    if (
        len(raw) != length + 9
        or binascii.crc_hqx(raw[:-3], 0xFFFF)
        != struct.unpack_from("<H", raw, len(raw) - 3)[0]
    ):
        raise ValueError("长度或 CRC 错误")
    return command, raw[6:-3]


def response(data: bytes) -> dict:
    """解码控制响应；ACCEPTED 不等于 owner 已执行。"""
    if len(data) != 7:
        raise ValueError("响应长度错误")
    schema, rid, op, result = struct.unpack("<BIBB", data)
    if schema != 1 or result not in RESULTS or op not in list(Op):
        raise ValueError("响应 schema/结果错误")
    return dict(id=rid, operation=op, result=result)


def status(data: bytes) -> dict:
    """解码 144 字节 owner 状态；flags 的可用位必须先于数值解释。"""
    if len(data) != 144 or data[0] != 1:
        raise ValueError("状态 schema/长度错误")
    schema, rid, model, mode, caps = struct.unpack_from("<BI16sBI", data)
    offset = 26
    converter = dict(
        zip(
            (
                "tx_lo",
                "tx_rf",
                "rx_lo",
                "rx_rf",
                "tx_att",
                "rx_att",
                "flags",
                "temperature",
            ),
            struct.unpack_from("<IIIIffHh", data, offset),
        )
    )
    offset += 28
    completions = []
    for _ in range(2):
        fields = struct.unpack_from("<IBBfffB", data, offset)
        offset += 19
        completions.append(
            dict(zip(("id", "operation", "target", "a", "b", "c", "result"), fields))
        )
    arrays = []
    for _ in range(2):
        fields = struct.unpack_from("<IffffHBBh", data, offset)
        offset += 26
        arrays.append(
            dict(
                zip(
                    (
                        "frequency",
                        "theta",
                        "phi",
                        "common",
                        "branch",
                        "flags",
                        "polar",
                        "size",
                        "temperature",
                    ),
                    fields,
                )
            )
        )
    return dict(
        id=rid,
        model=model.split(b"\0", 1)[0].decode("ascii"),
        mode=mode,
        capabilities=caps,
        converter=converter,
        completions=completions,
        arrays=arrays,
    )
