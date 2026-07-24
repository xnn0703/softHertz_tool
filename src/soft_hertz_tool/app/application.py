"""Qt 应用级样式和字体配置。"""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from soft_hertz_tool.identity import (
    PRODUCT_DISPLAY_NAME,
    SETTINGS_APPLICATION,
    SETTINGS_ORGANIZATION,
)


QSS_STYLE = """
QLabel#panelTitle {
    font-size: 13pt;
    font-weight: bold;
    color: #1a2a44;
    padding: 4px 0;
    border-bottom: 2px solid #c0c8d4;
}
"""


def configure_application(app: QApplication) -> None:
    """应用统一外观；macOS 保持原生，Windows 使用 Fusion。"""
    app.setOrganizationName(SETTINGS_ORGANIZATION)
    app.setApplicationName(SETTINGS_APPLICATION)
    app.setApplicationDisplayName(PRODUCT_DISPLAY_NAME)

    if sys.platform.startswith("win"):
        app.setStyle("Fusion")
        font_families = ["Microsoft YaHei", "Noto Sans CJK SC", "sans-serif"]
    elif sys.platform == "darwin":
        font_families = ["PingFang SC", "Helvetica Neue", "sans-serif"]
    else:
        font_families = ["Noto Sans CJK SC", "DejaVu Sans", "sans-serif"]

    font = QFont()
    font.setFamilies(font_families)
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(QSS_STYLE)
