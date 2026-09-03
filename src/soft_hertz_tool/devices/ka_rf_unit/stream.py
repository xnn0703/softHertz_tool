"""KA_RF_UNIT 串口字节流分帧器（无 Qt/serial 依赖）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from soft_hertz_tool.devices.ka_rf_unit.protocol import (
    FRAME_MAGIC,
    FRAME_HEADER_SIZE,
    FRAME_CRC_SIZE,
    MAX_FRAME_SIZE,
    parse_response,
)


@dataclass(frozen=True)
class StreamEvent:
    """增量拆帧产生的完整帧或丢弃事件。

    Attributes:
        kind: 事件类别，如 ``frame``、``garbage``、``bad_length``、``bad_frame``。
        data: 对应原始字节。
        parsed: 完整且校验通过时的协议解码结果。
        message: 诊断信息。
    """

    kind: str
    data: bytes
    parsed: Optional[Dict[str, Any]] = None
    message: str = ""


class FrameStreamParser:
    """支持分包、粘包和异常字节恢复的增量分帧器。"""

    def __init__(self) -> None:
        """创建空接收缓冲区。"""
        self.buffer = bytearray()

    def feed(self, data: bytes) -> List[StreamEvent]:
        """接收任意字节块并产出可解析帧与恢复诊断。

        Args:
            data: 新到达的串口字节，可为分包、粘包或含异常字节的数据。

        Returns:
            本次可确定的帧或丢弃事件；不完整尾帧保留到下一次调用。
        """
        self.buffer.extend(data)
        events: List[StreamEvent] = []

        while self.buffer:
            if self.buffer[:3] != FRAME_MAGIC:
                try:
                    next_magic = self.buffer.index(FRAME_MAGIC)
                except ValueError:
                    next_magic = len(self.buffer)
                garbage = bytes(self.buffer[:next_magic])
                del self.buffer[:next_magic]
                events.append(StreamEvent("garbage", garbage, message="异常字节已丢弃"))
                continue

            if len(self.buffer) < FRAME_HEADER_SIZE:
                break

            length = self.buffer[5]
            total = FRAME_HEADER_SIZE + length + FRAME_CRC_SIZE
            if total > MAX_FRAME_SIZE:
                bad = bytes(self.buffer[:FRAME_HEADER_SIZE])
                # 仅丢当前 magic，保留后续字节用于重新同步。
                del self.buffer[:3]
                events.append(
                    StreamEvent(
                        "bad_length",
                        bad,
                        message=f"非法载荷长度 {length}",
                    )
                )
                continue

            if len(self.buffer) < total:
                break

            frame = bytes(self.buffer[:total])
            del self.buffer[:total]
            parsed, message = parse_response(frame)
            events.append(
                StreamEvent(
                    "frame" if parsed else "bad_frame",
                    frame,
                    parsed,
                    message,
                )
            )

        return events

    def reset(self) -> None:
        """丢弃尚未完成的接收缓冲区。"""
        self.buffer.clear()