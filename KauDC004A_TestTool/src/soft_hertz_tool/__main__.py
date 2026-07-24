"""模块启动入口：python -m soft_hertz_tool。"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from soft_hertz_tool.app.application import configure_application
from soft_hertz_tool.app.main_window import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    configure_application(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
