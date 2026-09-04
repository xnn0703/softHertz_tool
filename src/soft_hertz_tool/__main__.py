"""模块启动入口：``python -m soft_hertz_tool``。"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from soft_hertz_tool.app.application import configure_application
from soft_hertz_tool.app.main_window import MainWindow
from soft_hertz_tool.identity import display_name_with_version


SMOKE_CLOSE_DELAY_MS = 250


def _parse_arguments(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str]]:
    """解析应用自有参数，并保留 Qt 可识别的未知参数。

    Args:
        argv: 不包含可执行文件名的命令行参数。

    Returns:
        二元组：SoftHertz Tool 参数命名空间，以及需要继续传给
        :class:`QApplication` 的参数列表。
    """

    parser = argparse.ArgumentParser(description="SoftHertz 多设备串口调试工具")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="创建主窗口后自动关闭，用于安装包和 CI 启动冒烟",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="打印版本号并退出",
    )
    return parser.parse_known_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """创建并运行 SoftHertz Tool Qt 应用。

    Args:
        argv: 可选的应用参数；为 ``None`` 时读取 ``sys.argv[1:]``。

    Returns:
        Qt 事件循环的退出码。

    Notes:
        ``--smoke`` 会创建真实主窗口并在短延时后关闭，只验证应用、资源与
        生命周期能够启动，不验证串口或真实硬件。
    """

    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    options, qt_arguments = _parse_arguments(raw_arguments)
    if options.version:
        print(display_name_with_version())
        return 0
    application_arguments = [sys.argv[0], *qt_arguments]
    # 测试或嵌入场景可能已经创建 QApplication；复用实例可避免 Qt 的单例冲突。
    app = QApplication.instance() or QApplication(application_arguments)
    configure_application(app)
    if options.smoke:
        print(display_name_with_version(), flush=True)
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
        # 复用外部 QApplication 时必须恢复原值，避免 smoke 模式污染调用方生命周期。
        app.setQuitOnLastWindowClosed(previous_quit_on_close)


if __name__ == "__main__":
    raise SystemExit(main())
