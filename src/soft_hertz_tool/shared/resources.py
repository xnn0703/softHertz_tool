"""开发环境和 PyInstaller onefile 环境的资源定位。"""

from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path


def resource_path(name: str) -> str:
    """定位源码安装或 PyInstaller onefile 中的包资源。

    Args:
        name: ``soft_hertz_tool.resources`` 下的资源文件名。

    Returns:
        现存资源的本地文件系统路径字符串。

    Raises:
        FileNotFoundError: onefile 解包目录和安装包资源中均不存在该文件。
    """

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        # PyInstaller 把额外运行时资源放在临时 _MEIPASS 根目录，优先使用该副本。
        bundled = Path(meipass) / name
        if bundled.exists():
            return str(bundled)

    packaged = files("soft_hertz_tool.resources").joinpath(name)
    if packaged.is_file():
        return str(packaged)

    raise FileNotFoundError(f"未找到 SoftHertz Tool 资源: {name}")
