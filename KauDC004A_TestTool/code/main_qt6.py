#!/usr/bin/env python3
"""旧启动路径兼容层；正式实现位于 ``soft_hertz_tool`` 包。"""

from __future__ import annotations

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from PySide6.QtWidgets import QApplication

from soft_hertz_tool.app.application import configure_application
from soft_hertz_tool.app.main_window import MainWindow
from soft_hertz_tool.devices.afd01_qs import QSPanel, QSSerialWorker
from soft_hertz_tool.devices.afdtr1024 import AFDTR1024Driver, AFDTR1024Panel, RXPanel, TXPanel
from soft_hertz_tool.devices.kaudc004a import KaUDCDriver, KaUDCPanel

SerialWorker = AFDTR1024Driver
DevicePanel = AFDTR1024Panel
KaUDCWorker = KaUDCDriver


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    configure_application(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
