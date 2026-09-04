"""SoftHertz 多设备串口调试上位机。"""

from __future__ import annotations

import os as _os

__all__ = ["__version__"]

# CI 在构建时通过 ``SOFTHERTZ_VERSION`` 环境变量注入 tag 名称（如 ``v3.1.3``），
# 本地开发或 workflow_dispatch 缺省时回退到 ``0.0.0+dev``，便于与正式版区分。
__version__ = _os.environ.get("SOFTHERTZ_VERSION") or "0.0.0+dev"
