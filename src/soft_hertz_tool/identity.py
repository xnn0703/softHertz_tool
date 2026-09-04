"""产品显示名、持久化命名空间和兼容迁移规则。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings

from soft_hertz_tool import __version__


PRODUCT_DISPLAY_NAME = "SoftHertz Tool"
SETTINGS_ORGANIZATION = "SoftHertz"
SETTINGS_APPLICATION = "SoftHertz_Tool"
LEGACY_SETTINGS_APPLICATION = "AFDTR_Tool"
DEVICE_MODEL_KEY = "device_model"
DEFAULT_WORKSPACE_KEY = "AFDTR"
LOG_DIRECTORY_NAME = "logs"


def display_name_with_version() -> str:
    """返回带版本号的客户可见产品名。

    Returns:
        例如 ``"SoftHertz Tool v3.1.3"``；本地开发时为
        ``"SoftHertz Tool v0.0.0+dev"``。
    """
    return f"{PRODUCT_DISPLAY_NAME} v{__version__}"


def create_application_settings() -> QSettings:
    """创建当前产品使用的设置存储。

    Returns:
        绑定 ``SoftHertz/SoftHertz_Tool`` 命名空间的 QSettings 对象。
    """

    return QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)


def create_legacy_settings() -> QSettings:
    """打开旧 AFDTR 产品设置。

    Returns:
        绑定旧 ``SoftHertz/AFDTR_Tool`` 命名空间的 QSettings 对象。

    Notes:
        调用方只读取迁移所需值，不删除或覆盖旧设置。
    """

    return QSettings(SETTINGS_ORGANIZATION, LEGACY_SETTINGS_APPLICATION)


def load_device_model(
    settings: QSettings,
    legacy_settings: Optional[QSettings] = None,
    default: str = DEFAULT_WORKSPACE_KEY,
) -> str:
    """读取设备工作区；当前设置缺失时从旧命名空间迁移一次。

    Args:
        settings: 当前产品设置。
        legacy_settings: 可选旧设置；未提供时按旧命名空间创建。
        default: 当前和旧设置均无有效值时使用的 Workspace key。

    Returns:
        应当激活的稳定 Workspace key。

    Notes:
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
    """构造当前产品位于系统文档目录下的默认日志路径。

    Args:
        documents_directory: 操作系统或调用方提供的文档根目录。

    Returns:
        ``<文档>/SoftHertz/SoftHertz_Tool/logs`` 路径；函数不创建目录。
    """

    return (
        Path(documents_directory)
        / SETTINGS_ORGANIZATION
        / SETTINGS_APPLICATION
        / LOG_DIRECTORY_NAME
    )
