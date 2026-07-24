"""设备无关的串口帧事件模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class FrameRecord:
    """单条设备帧事件；``model`` 表示实际设备型号，不表示 workspace key。"""

    model: str
    port: str
    direction: str
    command: str
    raw: bytes
    result: str
    level: str = "INFO"
    timestamp: datetime = field(default_factory=datetime.now)

    def to_line(self) -> str:
        time_text = self.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        raw_text = self.raw.hex(" ").upper() or "-"
        return (
            f"{time_text} | {self.model:<12} | {self.port:<18} | {self.direction:<7} | "
            f"{self.command:<22} | {raw_text} | {self.level}: {self.result}"
        )
