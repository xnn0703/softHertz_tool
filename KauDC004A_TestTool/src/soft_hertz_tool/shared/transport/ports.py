"""串口枚举。"""

from __future__ import annotations

from typing import List


def list_serial_ports() -> List[str]:
    import serial.tools.list_ports

    return [item.device for item in serial.tools.list_ports.comports()]
