"""KuR512B 设备领域模型与状态聚合。"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Mapping, Optional


class Polarity(str, Enum):
    """KuR512B 极化方式：线极化 0..180 / LHCP(254) / RHCP(255)。"""

    LINEAR = "LINEAR"
    LHCP = "LHCP"
    RHCP = "RHCP"

    @classmethod
    def coerce(cls, value: "Polarity | str") -> "Polarity":
        """将枚举或不区分大小写文本规范为极化枚举。"""
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).upper())
        except ValueError as exc:
            raise ValueError(f"不支持的极化类型: {value}") from exc


class ChartWindow(int, Enum):
    """实时曲线显示窗口（秒）。"""

    MIN_1 = 60
    MIN_5 = 300
    MIN_15 = 900

    @property
    def label(self) -> str:
        """UI 显示文本。"""
        return f"{self.value // 60} min"


@dataclass(frozen=True)
class BeamSetting:
    """一次波束设置经设备频率量化后的实际参数。"""

    requested_frequency_mhz: float
    actual_frequency_mhz: int
    frequency_code: int
    beam_h: int
    beam_v: int
    polarity: Polarity = Polarity.LINEAR
    pol_value: int = 0


@dataclass
class SubarrayStatus:
    """同一子阵最近一次状态查询的合并状态。"""

    device_id: int
    rev: Optional[int] = None
    sys_vcc: Optional[float] = None
    sys_temp: Optional[int] = None
    mcu_ver: Optional[int] = None
    last_ts_ns: Optional[int] = None
    last_raw_hex: Optional[str] = None

    def update(self, values: Mapping[str, Any]) -> None:
        """只合并已知且非空字段，避免查询 1/2 互相覆盖。"""

        known = {item.name for item in fields(self)}
        for name, value in values.items():
            if name in known and value is not None:
                setattr(self, name, value)

    def as_dict(self) -> dict[str, Any]:
        """返回适合 Qt Signal 传递的非空字段字典。"""

        return {
            item.name: value
            for item in fields(self)
            if (value := getattr(self, item.name)) is not None
        }


@dataclass
class SimulatorState:
    """模拟器为每个子阵保存的可回读配置。"""

    freq_code: int = 0
    pol_byte: int = 0
    beam_v: int = 0
    beam_h: int = 0
    en_row: int = 0
    ps_align: int = 0


__all__ = [
    "BeamSetting",
    "ChartWindow",
    "Polarity",
    "SimulatorState",
    "SubarrayStatus",
]
