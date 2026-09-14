"""KA_RF_UNIT 串口字节流分帧器（无 Qt/serial 依赖）。"""

from __future__ import annotations

from dataclasses import dataclass
import time
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

    def __init__(self, clock=time.monotonic) -> None:
        """创建空接收缓冲区。"""
        self.buffer = bytearray()
        self._clock = clock
        self._last_byte = 0.0

    def feed(self, data: bytes) -> List[StreamEvent]:
        """接收任意字节块并产出可解析帧与恢复诊断。

        Args:
            data: 新到达的串口字节，可为分包、粘包或含异常字节的数据。

        Returns:
            本次可确定的帧或丢弃事件；不完整尾帧保留到下一次调用。
        """
        events: List[StreamEvent] = []
        now = self._clock()
        if self.buffer and now - self._last_byte > 0.1:
            events.append(StreamEvent("timeout", bytes(self.buffer), message="半帧间隔超过 100 ms"))
            self.buffer.clear()
        if data:
            self._last_byte = now
        self.buffer.extend(data)

        while self.buffer:
            if self.buffer[:3] != FRAME_MAGIC:
                try:
                    next_magic = self.buffer.index(FRAME_MAGIC)
                except ValueError:
                    # 保留分包末尾的 P/PS，下一块可能接成 PSA。
                    keep = 2 if self.buffer.endswith(FRAME_MAGIC[:2]) else 1 if self.buffer.endswith(FRAME_MAGIC[:1]) else 0
                    next_magic = len(self.buffer) - keep
                if next_magic == 0:
                    break
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
            parsed, message = parse_response(frame)
            # CRC/长度损坏可能吞入下一帧；只滑过一个字节后重新找帧头。
            del self.buffer[:total if parsed else 1]
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
