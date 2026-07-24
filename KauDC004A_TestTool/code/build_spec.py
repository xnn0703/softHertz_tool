import os
import sys
from pathlib import Path

from PyInstaller.__main__ import run

if __name__ == "__main__":
    project_dir = Path(__file__).resolve().parents[1]
    code_dir = Path(__file__).resolve().parent
    source_dir = project_dir / "src"
    entrypoint = project_dir / "packaging" / "entrypoint.py"
    resources = source_dir / "soft_hertz_tool" / "resources"
    build_root = project_dir / "build" / "pyinstaller"
    spec_dir = build_root / "spec"
    work_dir = build_root / "work"
    dist_dir = code_dir / "dist"
    spec_dir.mkdir(parents=True, exist_ok=True)
    data_sep = os.pathsep
    args = [
        str(entrypoint),
        "--noconfirm",
        "--name=SoftHertz_AFDTR_Tool",
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
    run(args)
