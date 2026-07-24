"""KaUDC004A 字节流分帧与异常字节恢复。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal

from .protocol import FRAME_HEADER, FRAME_SIZE


@dataclass(frozen=True)
class StreamEvent:
    """一次分帧结果；完整候选帧与被丢弃字节均保留，便于调试监视。"""

    kind: Literal["frame", "drop"]
    raw: bytes
    reason: str

    @property
    def is_frame(self) -> bool:
        return self.kind == "frame"


class KaUDCStreamParser:
    """增量解析固定 12 字节帧，支持半帧、粘包和帧前垃圾数据。"""

    def __init__(self) -> None:
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> bytes:
        return bytes(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes) -> List[StreamEvent]:
        if data:
            self._buffer.extend(data)

        events: List[StreamEvent] = []
        header = FRAME_HEADER[:2]

        while len(self._buffer) >= len(header):
            header_index = self._buffer.find(header)
            if header_index < 0:
                # 末尾的 0xAA 可能是跨 chunk 帧头，保留到下一轮。
                keep = 1 if self._buffer[-1] == header[0] else 0
                drop_length = len(self._buffer) - keep
                if drop_length:
                    dropped = bytes(self._buffer[:drop_length])
                    del self._buffer[:drop_length]
                    events.append(StreamEvent("drop", dropped, "未找到帧头"))
                break

            if header_index > 0:
                dropped = bytes(self._buffer[:header_index])
                del self._buffer[:header_index]
                events.append(StreamEvent("drop", dropped, "帧头前异常字节已丢弃"))

            if len(self._buffer) < FRAME_SIZE:
                break

            frame = bytes(self._buffer[:FRAME_SIZE])
            del self._buffer[:FRAME_SIZE]
            events.append(StreamEvent("frame", frame, "完整候选帧"))

        return events


# 通用命名别名，便于工作区统一装配不同设备的 StreamParser。
FrameStreamParser = KaUDCStreamParser
