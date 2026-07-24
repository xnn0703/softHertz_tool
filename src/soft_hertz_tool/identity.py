"""产品显示名、持久化命名空间和兼容迁移规则。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings


PRODUCT_DISPLAY_NAME = "SoftHertz Tool"
SETTINGS_ORGANIZATION = "SoftHertz"
SETTINGS_APPLICATION = "SoftHertz_Tool"
LEGACY_SETTINGS_APPLICATION = "AFDTR_Tool"
DEVICE_MODEL_KEY = "device_model"
DEFAULT_WORKSPACE_KEY = "AFDTR"
LOG_DIRECTORY_NAME = "logs"


def create_application_settings() -> QSettings:
    """创建当前产品使用的设置存储。"""

    return QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)


def create_legacy_settings() -> QSettings:
    """打开旧 AFDTR 产品设置；迁移过程只读，不删除旧值。"""

    return QSettings(SETTINGS_ORGANIZATION, LEGACY_SETTINGS_APPLICATION)


def load_device_model(
    settings: QSettings,
    legacy_settings: Optional[QSettings] = None,
    default: str = DEFAULT_WORKSPACE_KEY,
) -> str:
    """读取设备工作区；当前设置缺失时从旧命名空间迁移一次。

    当前命名空间具有最高优先级。旧值仅复制到当前命名空间，原设置保持不变。
    """

    if settings.contains(DEVICE_MODEL_KEY):
        value = settings.value(DEVICE_MODEL_KEY)
        return default if value is None else str(value)

    legacy = legacy_settings if legacy_settings is not None else create_legacy_settings()
    if not legacy.contains(DEVICE_MODEL_KEY):
        return default

    value = legacy.value(DEVICE_MODEL_KEY)
    selected = default if value is None else str(value)
    settings.setValue(DEVICE_MODEL_KEY, selected)
    settings.sync()
    return selected


def default_log_directory(documents_directory: Path) -> Path:
    """返回当前产品位于系统文档目录下的默认日志目录。"""

    return (
        Path(documents_directory)
        / SETTINGS_ORGANIZATION
        / SETTINGS_APPLICATION
        / LOG_DIRECTORY_NAME
    )
