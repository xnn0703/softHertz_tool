"""主窗口与静态工作区注册回归。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from soft_hertz_tool.identity import (
    DEVICE_MODEL_KEY,
    PRODUCT_DISPLAY_NAME,
    SETTINGS_APPLICATION,
    SETTINGS_ORGANIZATION,
    create_application_settings,
    load_device_model,
)
from soft_hertz_tool.app.main_window import MainWindow
from soft_hertz_tool.app.registry import WORKSPACE_SPECS, workspace_keys


def test_registry_has_unique_expected_keys():
    assert workspace_keys() == ("AFDTR", "AFD01_QS")
    assert len(set(workspace_keys())) == len(WORKSPACE_SPECS)


def test_current_settings_use_unified_product_identity():
    settings = create_application_settings()
    assert settings.organizationName() == SETTINGS_ORGANIZATION
    assert settings.applicationName() == SETTINGS_APPLICATION


def _ini_settings(path) -> QSettings:
    return QSettings(str(path), QSettings.IniFormat)


def test_device_model_migrates_once_without_deleting_legacy_setting(tmp_path):
    settings = _ini_settings(tmp_path / "SoftHertz_Tool.ini")
    legacy_settings = _ini_settings(tmp_path / "AFDTR_Tool.ini")
    legacy_settings.setValue(DEVICE_MODEL_KEY, "AFD01_QS")
    legacy_settings.sync()

    assert load_device_model(settings, legacy_settings) == "AFD01_QS"
    assert settings.value(DEVICE_MODEL_KEY) == "AFD01_QS"
    assert legacy_settings.value(DEVICE_MODEL_KEY) == "AFD01_QS"

    legacy_settings.setValue(DEVICE_MODEL_KEY, "AFDTR")
    legacy_settings.sync()
    assert load_device_model(settings, legacy_settings) == "AFD01_QS"
    assert legacy_settings.value(DEVICE_MODEL_KEY) == "AFDTR"


def test_current_device_model_takes_priority_over_legacy_setting(tmp_path):
    settings = _ini_settings(tmp_path / "SoftHertz_Tool.ini")
    legacy_settings = _ini_settings(tmp_path / "AFDTR_Tool.ini")
    settings.setValue(DEVICE_MODEL_KEY, "AFDTR")
    legacy_settings.setValue(DEVICE_MODEL_KEY, "AFD01_QS")

    assert load_device_model(settings, legacy_settings) == "AFDTR"


def test_main_window_switches_and_shuts_down_workspaces(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = _ini_settings(tmp_path / f"{SETTINGS_ORGANIZATION}_{SETTINGS_APPLICATION}.ini")
    legacy_settings = _ini_settings(tmp_path / "legacy.ini")
    window = MainWindow(settings=settings, legacy_settings=legacy_settings)
    assert window.windowTitle() == PRODUCT_DISPLAY_NAME
    assert window.pages.count() == 2
    assert not window.workspaces[1].panel._telemetry_timer.isActive()
    window.model_combo.setCurrentIndex(1)
    assert window.pages.currentIndex() == 1
    assert window.workspaces[1].panel._telemetry_timer.isActive()

    active_workspace = window.workspaces[1]
    original_deactivate = active_workspace.deactivate
    original_activate = active_workspace.activate
    rollback_calls = []
    active_workspace.deactivate = lambda: False
    active_workspace.activate = lambda: rollback_calls.append(True)
    window.model_combo.setCurrentIndex(0)
    assert window.model_combo.currentIndex() == 1
    assert window.pages.currentIndex() == 1
    assert rollback_calls == [True]
    active_workspace.deactivate = original_deactivate
    active_workspace.activate = original_activate

    window.model_combo.setCurrentIndex(0)
    assert window.pages.currentIndex() == 0
    assert not window.workspaces[1].panel._telemetry_timer.isActive()
    window.model_combo.setCurrentIndex(1)
    assert window.workspaces[1].panel._telemetry_timer.isActive()

    prepare_blocker = window.workspaces[0]
    original_prepare = prepare_blocker.deactivate
    prepare_blocker.deactivate = lambda: False
    assert not window.shutdown()
    assert not any(panel._shutdown for panel in window.workspaces[0].panels)
    assert not window.workspaces[1].panel._shutdown
    assert window.workspaces[1].panel._telemetry_timer.isActive()
    prepare_blocker.deactivate = original_prepare
    assert window.shutdown()
    window.deleteLater()
    app.processEvents()
