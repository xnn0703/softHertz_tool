"""AFD01_QS 页面旧导入路径兼容层。"""

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from soft_hertz_tool.devices.afd01_qs.driver import Afd01QsDriver, QSSerialWorker  # noqa: E402,F401
from soft_hertz_tool.devices.afd01_qs.models import ReportRateMeter  # noqa: E402,F401
from soft_hertz_tool.devices.afd01_qs.panel import Afd01QsPanel, QSPanel  # noqa: E402,F401
from soft_hertz_tool.devices.afd01_qs.widgets import ArrayGridWidget  # noqa: E402,F401

__all__ = [
    "Afd01QsDriver",
    "Afd01QsPanel",
    "ArrayGridWidget",
    "QSPanel",
    "QSSerialWorker",
    "ReportRateMeter",
]
