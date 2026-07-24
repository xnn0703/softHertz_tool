#!/usr/bin/env python3
"""AFD01_QS 模拟器旧启动路径兼容层。"""

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from soft_hertz_tool.devices.afd01_qs.simulator import QSDeviceSimulator, main  # noqa: E402,F401

__all__ = ["QSDeviceSimulator", "main"]


if __name__ == "__main__":
    main()
