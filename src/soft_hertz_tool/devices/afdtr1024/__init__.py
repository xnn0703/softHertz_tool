"""AFDT1024/AFDR1024 共用设备模块公开接口。"""

from soft_hertz_tool.devices.afdtr1024.driver import AFDTR1024Driver, Driver
from soft_hertz_tool.devices.afdtr1024.models import BeamSetting, DeviceVariant, Variant
from soft_hertz_tool.devices.afdtr1024.panel import AFDTR1024Panel, Panel, RXPanel, TXPanel
from soft_hertz_tool.devices.afdtr1024.stream import AFDTR1024StreamParser, StreamParser

__all__ = [
    "AFDTR1024Driver",
    "AFDTR1024Panel",
    "AFDTR1024StreamParser",
    "BeamSetting",
    "DeviceVariant",
    "Driver",
    "Panel",
    "RXPanel",
    "StreamParser",
    "TXPanel",
    "Variant",
]
