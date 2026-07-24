"""串口枚举。"""

from __future__ import annotations

from typing import List


def list_serial_ports() -> List[str]:
    """枚举当前系统可见的串口设备名。

    Returns:
        pyserial 按系统枚举顺序提供的端口名列表；无可用端口时返回空列表。
    """

    import serial.tools.list_ports

    return [item.device for item in serial.tools.list_ports.comports()]
