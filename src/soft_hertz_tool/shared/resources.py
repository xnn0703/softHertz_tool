"""开发环境和 PyInstaller onefile 环境的资源定位。"""

from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path


def resource_path(name: str) -> str:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / name
        if bundled.exists():
            return str(bundled)

    packaged = files("soft_hertz_tool.resources").joinpath(name)
    if packaged.is_file():
        return str(packaged)

    raise FileNotFoundError(f"未找到 SoftHertz Tool 资源: {name}")
