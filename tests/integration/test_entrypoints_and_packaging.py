"""模块入口和 PyInstaller 构建边界检查。"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _load_build_module():
    module_path = REPOSITORY_ROOT / "packaging" / "build_windows.py"
    spec = importlib.util.spec_from_file_location("soft_hertz_build_windows", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_module_smoke_entrypoint_exits_cleanly():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
    environment["QT_QPA_PLATFORM"] = "offscreen"
    completed = subprocess.run(
        [sys.executable, "-m", "soft_hertz_tool", "--smoke"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_pyinstaller_arguments_use_root_outputs_and_current_product_name(tmp_path: Path):
    build_windows = _load_build_module()
    # 默认无 SOFTHERTZ_VERSION 时回退 ``0.0.0+dev``，产物名为 ``SoftHertz_Tool-0.0.0+dev``。
    app_name = build_windows._app_name(build_windows._resolve_version())
    arguments = build_windows._pyinstaller_arguments(tmp_path, app_name)

    assert f"--name={app_name}" in arguments
    assert app_name.startswith("SoftHertz_Tool-")
    assert "--clean" in arguments
    assert f"--distpath={tmp_path / 'dist'}" in arguments
    assert f"--workpath={tmp_path / 'build' / 'pyinstaller' / 'work'}" in arguments
    assert all("SoftHertz_AFDTR_Tool" not in argument for argument in arguments)


def test_build_cleanup_is_limited_to_regenerable_output_directories(tmp_path: Path):
    build_windows = _load_build_module()
    pyinstaller_output = tmp_path / "build" / "pyinstaller"
    unrelated_build_output = tmp_path / "build" / "keep"
    distribution_output = tmp_path / "dist"
    pyinstaller_output.mkdir(parents=True)
    unrelated_build_output.mkdir(parents=True)
    distribution_output.mkdir()
    (pyinstaller_output / "work.txt").write_text("generated", encoding="utf-8")
    (unrelated_build_output / "keep.txt").write_text("keep", encoding="utf-8")
    (distribution_output / "app.exe").write_text("generated", encoding="utf-8")

    build_windows._clean_build_outputs(tmp_path)

    assert not pyinstaller_output.exists()
    assert not distribution_output.exists()
    assert (unrelated_build_output / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_build_version_sanitizes_plus_for_windows_filename(monkeypatch):
    """``+`` 在 Windows PyInstaller 产物与 spec 文件名下兼容性差，转为 ``.``。"""
    build_windows = _load_build_module()
    monkeypatch.setenv("SOFTHERTZ_VERSION", "v3.1.4+dev")
    assert build_windows._resolve_version() == "3.1.4.dev"
    assert "+" not in build_windows._app_name(build_windows._resolve_version())

    monkeypatch.setenv("SOFTHERTZ_VERSION", "v3.1.4")
    assert build_windows._resolve_version() == "3.1.4"
    assert build_windows._app_name(build_windows._resolve_version()) == "SoftHertz_Tool-3.1.4"


def test_build_summary_is_safe_for_windows_cp1252_console():
    """构建日志不得在 GitHub Windows runner 的 cp1252 stdout 上编码失败。"""
    build_windows = _load_build_module()
    summary = build_windows._build_summary("3.1.3", "SoftHertz_Tool-3.1.3")

    assert summary.encode("cp1252") == b"Build version: 3.1.3 -> artifact: SoftHertz_Tool-3.1.3"
