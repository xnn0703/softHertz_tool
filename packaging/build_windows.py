import os
import shutil
import sys
from pathlib import Path

from PyInstaller.__main__ import run


APP_NAME = "SoftHertz_Tool"


def _project_directory() -> Path:
    return Path(__file__).resolve().parents[1]


def _clean_build_outputs(project_dir: Path) -> None:
    """仅清理仓库内可再生成的 PyInstaller 输出。"""

    build_root = project_dir / "build" / "pyinstaller"
    dist_dir = project_dir / "dist"
    shutil.rmtree(build_root, ignore_errors=True)
    shutil.rmtree(dist_dir, ignore_errors=True)


def _pyinstaller_arguments(project_dir: Path) -> list[str]:
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
    project_dir = _project_directory()
    _clean_build_outputs(project_dir)
    run(_pyinstaller_arguments(project_dir))


if __name__ == "__main__":
    main()
