"""KuR512B PSA 字节流拆帧器。

与 ``afdtr1024`` 帧头一致（PSA），但命令字段位宽不同；为避免协议常量耦合，
KuR512B 维护独立的拆帧器，行为包括：

- 半帧、粘包、垃圾前缀恢复
- 非法帧长度仅前移 1 字节
- 坏校验丢弃并继续解析
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from soft_hertz_tool.devices.kur512.protocol import FRAME_HEADER


@dataclass(frozen=True)
class StreamEvent:
    """增量解析产生的完整帧或被丢弃字节及其原因。"""

    kind: Literal["frame", "drop"]
    raw: bytes
    reason: str = ""

    @property
    def is_frame(self) -> bool:
        """判断该事件是否携带可交给协议层的完整帧。"""
        return self.kind == "frame"


class KUR512StreamParser:
    """支持半帧、粘包、前导垃圾和零长度坏帧的增量解析器。"""

    def __init__(self, max_data_length: int = 0xFF):
        """创建解析器。

        Args:
            max_data_length: 帧数据区最大长度，必须为 1~255。

        Raises:
            ValueError: 最大长度不在协议单字节长度范围内。
        """
        if not 1 <= max_data_length <= 0xFF:
            raise ValueError("max_data_length 必须在 1~255 范围内")
        self.max_data_length = max_data_length
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> bytes:
        """返回尚不能构成完整帧的缓存副本。"""
        return bytes(self._buffer)

    def reset(self) -> bytes:
        """清空解析缓存并返回未完成帧字节，供断开诊断使用。"""
        pending = bytes(self._buffer)
        self._buffer.clear()
        return pending

    def feed(self, data: bytes) -> list[StreamEvent]:
        """增量输入字节并返回完整帧或恢复过程中的丢弃事件。"""
        if data:
            self._buffer.extend(data)
        events: list[StreamEvent] = []

        while self._buffer:
            start = self._buffer.find(FRAME_HEADER)
            if start < 0:
                keep = self._header_suffix_length()
                drop_count = len(self._buffer) - keep
                if drop_count:
                    events.append(StreamEvent("drop", bytes(self._buffer[:drop_count]), "未找到帧头"))
                    del self._buffer[:drop_count]
                break

            if start:
                events.append(StreamEvent("drop", bytes(self._buffer[:start]), "异常字节已丢弃"))
                del self._buffer[:start]

            if len(self._buffer) < 5:
                break

            length = self._buffer[4]
            if length == 0 or length > self.max_data_length:
                events.append(StreamEvent("drop", bytes(self._buffer[:1]), "非法帧长度"))
                del self._buffer[:1]
                continue

            total_length = 6 + length
            if len(self._buffer) < total_length:
                break

            frame = bytes(self._buffer[:total_length])
            del self._buffer[:total_length]
            events.append(StreamEvent("frame", frame))

        return events

    def _header_suffix_length(self) -> int:
        """保留可能成为下一段帧头的 ``P`` 或 ``PS`` 后缀。"""
        maximum = min(len(self._buffer), len(FRAME_HEADER) - 1)
        for size in range(maximum, 0, -1):
            if self._buffer[-size:] == FRAME_HEADER[:size]:
                return size
        return 0


StreamParser = KUR512StreamParser


__all__ = ["KUR512StreamParser", "StreamEvent", "StreamParser"]
