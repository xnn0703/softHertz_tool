"""工作区注册契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from soft_hertz_tool.shared.lifecycle import Workspace


@dataclass(frozen=True)
class WorkspaceSpec:
    key: str
    title: str
    factory: Callable[[], Workspace]
