"""SoftHertz 多设备串口调试上位机。"""

from __future__ import annotations

__all__ = ["__version__"]

# 版本号硬编码于本模块，发版时人工同步到当前 tag。
# 注意：与 ``pyproject.toml`` 的 ``[project] version`` 字段（始终为开发占位
# ``0.0.0``）和 CI 通过 ``SOFTHERTZ_VERSION`` 注入到 ``packaging/build_windows.py``
# 的构建期版本号相互独立——前者驱动运行期窗口标题，后两者分别用于包元数据
# 与 Windows EXE 产物命名。
__version__ = "3.2.0"