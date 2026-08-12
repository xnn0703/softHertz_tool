"""Qt 进程级产品身份检查。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from soft_hertz_tool.app.application import configure_application
from soft_hertz_tool.identity import (
    PRODUCT_DISPLAY_NAME,
    SETTINGS_APPLICATION,
    SETTINGS_ORGANIZATION,
)


def test_configure_application_sets_process_identity():
    app = QApplication.instance() or QApplication([])
    configure_application(app)

    assert app.organizationName() == SETTINGS_ORGANIZATION
    assert app.applicationName() == SETTINGS_APPLICATION
    assert app.applicationDisplayName() == PRODUCT_DISPLAY_NAME
