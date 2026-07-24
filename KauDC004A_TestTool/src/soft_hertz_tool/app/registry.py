"""PyInstaller 友好的静态工作区注册表。"""

from __future__ import annotations

from soft_hertz_tool.app.spec import WorkspaceSpec
from soft_hertz_tool.workspaces import Afd01QsWorkspace, AfdtrWorkspace


WORKSPACE_SPECS = (
    WorkspaceSpec("AFDTR", "AFDTR（三设备）", AfdtrWorkspace),
    WorkspaceSpec("AFD01_QS", "AFD01_QS", Afd01QsWorkspace),
)


def workspace_keys() -> tuple[str, ...]:
    return tuple(spec.key for spec in WORKSPACE_SPECS)
