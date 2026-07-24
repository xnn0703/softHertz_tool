"""AFDT1024/AFDR1024 共用实现的领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Mapping, Optional, Union


class DeviceVariant(str, Enum):
    """共用实现内部的收发变体。"""

    TX = "TX"
    RX = "RX"

    @classmethod
    def coerce(cls, value: Union["DeviceVariant", str]) -> "DeviceVariant":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).upper())
        except ValueError as exc:
            raise ValueError(f"不支持的 AFDT1024/AFDR1024 变体: {value}") from exc

    @property
    def is_tx(self) -> bool:
        return self is DeviceVariant.TX

    @property
    def model_name(self) -> str:
        """返回硬件铭牌型号，而不是内部共用模块名。"""

        return "AFDT1024" if self.is_tx else "AFDR1024"


# 对外使用更简洁的名称，同时保留语义明确的类名。
Variant = DeviceVariant


@dataclass(frozen=True)
class BeamSetting:
    """一次波束设置经设备频率量化后的实际参数。"""

    requested_frequency_mhz: float
    actual_frequency_mhz: int
    frequency_code: int
    beam_h: int
    beam_v: int


@dataclass
class SubarrayStatus:
    """同一子阵的查询 1/查询 2 合并状态。"""

    device_id: int
    rev: Optional[int] = None
    state: Optional[int] = None
    pa_en: Optional[int] = None
    sys_vcc: Optional[float] = None
    sys_temp: Optional[int] = None
    att_tc: Optional[int] = None
    mcu_ver: Optional[int] = None
    pol: Optional[int] = None
    en_row: Optional[int] = None
    freq_code: Optional[int] = None
    freq_mhz: Optional[int] = None
    beam_v: Optional[int] = None
    beam_h: Optional[int] = None
    theta: Optional[float] = None
    phi: Optional[float] = None

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

    pol: int = 0
    en_row: int = 0
    freq_code: int = 0
    beam_v: int = 0
    beam_h: int = 0
    pa_en: int = 1
