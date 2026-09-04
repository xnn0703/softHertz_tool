"""构建 SoftHertz Tool PyInstaller 单文件 GUI 产物。

脚本从仓库位置推导全部输入和输出路径，只清理仓库内可再生成的
``build/pyinstaller`` 与 ``dist``，并让 PyInstaller 异常直接向调用方传播。

版本号来源：CI 通过 ``SOFTHERTZ_VERSION`` 环境变量（通常是
``GITHUB_REF_NAME``，如 ``v3.1.3``）注入，脚本内剥掉 ``v`` 前缀并把
PyInstaller 产物命名为 ``SoftHertz_Tool-<version>.exe``；本地构建缺省
为 ``0.0.0+dev``。
"""

import os
import re
import shutil
import sys
from pathlib import Path

from PyInstaller.__main__ import run


DEFAULT_DEV_VERSION = "0.0.0+dev"  # 解析时 ``+`` 转 ``.``，最终为 ``0.0.0.dev``。
# 接受 ``[0-9A-Za-z._-]`` 字符；``+`` 视为合法的 PEP 440 后缀分隔符。
# 文件名里用 ``.`` 替代 ``+``，避免 PyInstaller Windows bootloader / 某些
# 通配工具在 ``+`` 上的兼容性差异。
_FILENAME_SAFE_RE = re.compile(r"[^0-9A-Za-z._+-]")


def _resolve_version() -> str:
    """从 ``SOFTHERTZ_VERSION`` 环境变量解析构建版本。

    Returns:
        已剥 ``v`` 前缀、含 ``[0-9A-Za-z._-]`` 的版本字符串。
    """

    raw = os.environ.get("SOFTHERTZ_VERSION") or DEFAULT_DEV_VERSION
    if raw.startswith("v") and len(raw) > 1:
        raw = raw[1:]
    safe = _FILENAME_SAFE_RE.sub(".", raw)
    safe = safe.replace("+", ".")
    return safe or DEFAULT_DEV_VERSION.replace("+", ".")


def _app_name(version: str) -> str:
    """根据版本返回 PyInstaller ``--name`` 与产物文件名（不含扩展名）。"""

    return f"SoftHertz_Tool-{version}"


def _build_summary(version: str, app_name: str) -> str:
    """返回可在 Windows 非 UTF-8 控制台安全输出的构建摘要。"""

    return f"Build version: {version} -> artifact: {app_name}"


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


def _pyinstaller_arguments(project_dir: Path, app_name: str) -> list[str]:
    """生成可复现的 PyInstaller 命令参数。

    Args:
        project_dir: SoftHertz Tool 仓库根目录。
        app_name: PyInstaller ``--name``，通常为 ``SoftHertz_Tool-<version>``。

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
        f"--name={app_name}",
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

    Notes:
        产物名为 ``SoftHertz_Tool-<version>.<ext>``；版本来自
        ``SOFTHERTZ_VERSION`` 环境变量，缺省 ``0.0.0+dev``。
    """

    project_dir = _project_directory()
    version = _resolve_version()
    app_name = _app_name(version)
    _clean_build_outputs(project_dir)
    print(_build_summary(version, app_name))
    run(_pyinstaller_arguments(project_dir, app_name))


if __name__ == "__main__":
    main()
