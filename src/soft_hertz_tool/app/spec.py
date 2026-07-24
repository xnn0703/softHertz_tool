"""工作区注册契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from soft_hertz_tool.shared.lifecycle import Workspace


@dataclass(frozen=True)
class WorkspaceSpec:
    """静态 Workspace 注册项。

    Attributes:
        key: 用于 QSettings 持久化的稳定标识。
        title: 在工作区选择框中显示的文本。
        factory: 无参数创建 Workspace 实例的工厂。
    """

    key: str
    title: str
    factory: Callable[[], Workspace]
