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
        """判断事件是否为待协议层校验的完整候选帧。

        Returns:
            ``kind`` 为 ``frame`` 时返回 ``True``；否则表示应记录为 ``DROP``。
        """
        return self.kind == "frame"


class KaUDCStreamParser:
    """增量解析固定 12 字节帧，支持半帧、粘包和帧前垃圾数据。"""

    def __init__(self) -> None:
        """创建空缓冲区的增量固定帧解析器。"""
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> bytes:
        """返回尚不足一个完整帧的缓存副本。

        Returns:
            不可变字节副本；仅用于诊断和测试，不可用于修改解析器状态。
        """
        return bytes(self._buffer)

    def reset(self) -> None:
        """丢弃未完成半帧，在断开或确认停止后恢复初始状态。"""
        self._buffer.clear()

    def feed(self, data: bytes) -> List[StreamEvent]:
        """增量输入串口字节并提取完整候选帧与可诊断丢弃事件。

        Args:
            data: 任意长度的串口读取块，可包含半帧、粘包或帧前垃圾字节。

        Returns:
            按接收顺序排列的完整候选帧和 ``DROP`` 事件。CRC 校验由协议层完成。

        状态:
            数据不足 12 字节时保留到下一次调用；找不到帧头时保留末尾单个 ``0xAA``，
            使跨读取块的 ``AA 55`` 帧头不会被误丢弃。
        """
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
