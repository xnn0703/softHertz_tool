"""构建 SoftHertz Tool PyInstaller 单文件 GUI 产物。

脚本从仓库位置推导全部输入和输出路径，只清理仓库内可再生成的
``build/pyinstaller`` 与 ``dist``，并让 PyInstaller 异常直接向调用方传播。
"""

import os
import shutil
import sys
from pathlib import Path

from PyInstaller.__main__ import run


APP_NAME = "SoftHertz_Tool"


def _project_directory() -> Path:
    """定位包含 ``pyproject.toml`` 的仓库根目录。

    Returns:
        当前构建脚本上两级的绝对仓库路径。
    """

    return Path(__file__).resolve().parents[1]


def _clean_build_outputs(project_dir: Path) -> None:
    """仅清理仓库内可再生成的 PyInstaller 输出。

    Args:
        project_dir: SoftHertz Tool 仓库根目录。

    Returns:
        无返回值；目标不存在时保持成功。
    """

    build_root = project_dir / "build" / "pyinstaller"
    dist_dir = project_dir / "dist"
    shutil.rmtree(build_root, ignore_errors=True)
    shutil.rmtree(dist_dir, ignore_errors=True)


def _pyinstaller_arguments(project_dir: Path) -> list[str]:
    """生成可复现的 PyInstaller 命令参数。

    Args:
        project_dir: SoftHertz Tool 仓库根目录。

    Returns:
        传给 ``PyInstaller.__main__.run`` 的参数列表。Windows 额外嵌入 ICO，
        所有平台均收集包内数据和 PNG 运行时资源。
    """

    source_dir = project_dir / "src"
    entrypoint = project_dir / "packaging" / "entrypoint.py"
    resources = source_dir / "soft_hertz_tool" / "resources"
    build_root = project_dir / "build" / "pyinstaller"
    spec_dir = build_root / "spec"
    work_dir = build_root / "work"
    dist_dir = project_dir / "dist"
    spec_dir.mkdir(parents=True, exist_ok=True)
    data_sep = os.pathsep
    args = [
        str(entrypoint),
        "--noconfirm",
        "--clean",
        f"--name={APP_NAME}",
        "--windowed",
        "--onefile",
        f"--paths={source_dir}",
        f"--specpath={spec_dir}",
        f"--workpath={work_dir}",
        f"--distpath={dist_dir}",
        "--collect-data=soft_hertz_tool",
        f"--add-data={resources / 'soft_hertz_logo_deepspace_blue_512.png'}{data_sep}.",
    ]
    if sys.platform.startswith("win"):
        args.append(f"--icon={resources / 'soft_hertz_logo_deepspace_blue_512.ico'}")
    return args


def main() -> None:
    """清理旧输出并执行一次完整 PyInstaller 构建。

    Returns:
        无返回值；PyInstaller 构建失败时异常原样向上传播。
    """

    project_dir = _project_directory()
    _clean_build_outputs(project_dir)
    run(_pyinstaller_arguments(project_dir))


if __name__ == "__main__":
    main()
