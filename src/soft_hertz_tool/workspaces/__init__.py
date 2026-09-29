"""面向用户的设备工作区。"""

from soft_hertz_tool.workspaces.afd01_qs import Afd01QsWorkspace
from soft_hertz_tool.workspaces.afdtr import AfdtrWorkspace
from soft_hertz_tool.workspaces.ka_rf_unit import KaRfUnitWorkspace
from soft_hertz_tool.workspaces.kur512 import Kur512Workspace

__all__ = ["Afd01QsWorkspace", "AfdtrWorkspace", "KaRfUnitWorkspace", "Kur512Workspace"]