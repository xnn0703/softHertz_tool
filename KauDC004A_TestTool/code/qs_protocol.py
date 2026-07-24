"""AFD01_QS 协议旧导入路径兼容层。"""

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from soft_hertz_tool.devices.afd01_qs.protocol import *  # noqa: F401,F403,E402
from soft_hertz_tool.devices.afd01_qs.stream import FrameStreamParser, StreamEvent  # noqa: E402,F401
