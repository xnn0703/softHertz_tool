"""报文监视器旧导入路径兼容层。"""

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from soft_hertz_tool.shared.observability import AsyncFrameLogger, FrameRecord  # noqa: E402,F401
from soft_hertz_tool.shared.ui.frame_monitor import FrameMonitorWidget  # noqa: E402,F401

__all__ = ["AsyncFrameLogger", "FrameMonitorWidget", "FrameRecord"]
