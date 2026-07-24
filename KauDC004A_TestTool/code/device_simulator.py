#!/usr/bin/env python3
"""AFDT1024/AFDR1024 模拟器旧启动路径兼容层。"""

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from soft_hertz_tool.devices.afdtr1024.simulator import *  # noqa: F401,F403,E402
from soft_hertz_tool.devices.afdtr1024.simulator import main  # noqa: E402


if __name__ == "__main__":
    main()
