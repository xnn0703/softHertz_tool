"""AFD01_QS 串口字节流分帧。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from soft_hertz_tool.devices.afd01_qs.protocol import FRAME_MAGIC, MAX_PAYLOAD, parse_frame


@dataclass(frozen=True)
class StreamEvent:
    kind: str
    data: bytes
    parsed: Optional[Dict[str, Any]] = None
    message: str = ""


class FrameStreamParser:
    """支持分包、粘包和异常字节恢复的增量分帧器。"""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> List[StreamEvent]:
        self.buffer.extend(data)
        events: List[StreamEvent] = []

        while self.buffer:
            if self.buffer[0] != FRAME_MAGIC:
                try:
                    next_magic = self.buffer.index(FRAME_MAGIC)
                except ValueError:
                    next_magic = len(self.buffer)
                garbage = bytes(self.buffer[:next_magic])
                del self.buffer[:next_magic]
                events.append(StreamEvent("garbage", garbage, message="异常字节已丢弃"))
                continue

            if len(self.buffer) < 4:
                break

            length = int.from_bytes(self.buffer[2:4], "big")
            if length > MAX_PAYLOAD:
                bad = bytes(self.buffer[:4])
                # 只移除当前帧头，让后续字节仍有机会被重新同步。
                del self.buffer[0]
                events.append(StreamEvent("bad_length", bad, message=f"非法载荷长度 {length}"))
                continue

            total = length + 6
            if len(self.buffer) < total:
                break

            frame = bytes(self.buffer[:total])
            del self.buffer[:total]
            parsed, message = parse_frame(frame)
            events.append(StreamEvent("frame" if parsed else "bad_frame", frame, parsed, message))

        return events

    def reset(self) -> None:
        self.buffer.clear()
