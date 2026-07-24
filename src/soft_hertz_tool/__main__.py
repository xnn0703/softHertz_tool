"""模块启动入口：``python -m soft_hertz_tool``。"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from soft_hertz_tool.app.application import configure_application
from soft_hertz_tool.app.main_window import MainWindow


SMOKE_CLOSE_DELAY_MS = 250


def _parse_arguments(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="SoftHertz 多设备串口调试工具")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="创建主窗口后自动关闭，用于安装包和 CI 启动冒烟",
    )
    return parser.parse_known_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    options, qt_arguments = _parse_arguments(raw_arguments)
    application_arguments = [sys.argv[0], *qt_arguments]
    app = QApplication.instance() or QApplication(application_arguments)
    configure_application(app)
    window = MainWindow()
    window.show()

    previous_quit_on_close = app.quitOnLastWindowClosed()
    smoke_timer = None
    if options.smoke:
        app.setQuitOnLastWindowClosed(True)
        smoke_timer = QTimer(window)
        smoke_timer.setSingleShot(True)
        smoke_timer.timeout.connect(window.close)
        smoke_timer.start(SMOKE_CLOSE_DELAY_MS)

    try:
        return app.exec()
    finally:
        if smoke_timer is not None:
            smoke_timer.stop()
        app.setQuitOnLastWindowClosed(previous_quit_on_close)


if __name__ == "__main__":
    raise SystemExit(main())
