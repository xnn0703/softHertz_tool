"""PyInstaller 友好的静态工作区注册表。"""

from __future__ import annotations

from soft_hertz_tool.app.spec import WorkspaceSpec
from soft_hertz_tool.workspaces import Afd01QsWorkspace, AfdtrWorkspace


WORKSPACE_SPECS = (
    WorkspaceSpec("AFDTR", "AFDTR（三设备）", AfdtrWorkspace),
    WorkspaceSpec("AFD01_QS", "AFD01_QS", Afd01QsWorkspace),
)


def workspace_keys() -> tuple[str, ...]:
    """返回按 UI 展示顺序排列的稳定 Workspace key。

    Returns:
        registry 中所有工作区 key 组成的不可变元组。
    """

    return tuple(spec.key for spec in WORKSPACE_SPECS)
