"""仓库根结构和生成物隔离检查。"""

from __future__ import annotations

import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATED_SUFFIXES = {".exe", ".zip", ".pyc", ".log", ".spec"}
GENERATED_PARTS = {"build", "dist", "__pycache__", ".pytest_cache"}


def test_repository_root_is_the_only_project_root():
    for required in ("pyproject.toml", "src", "tests", "packaging", "docs"):
        assert (REPOSITORY_ROOT / required).exists(), f"仓库根缺少 {required}"

    for retired in ("KauDC004A_TestTool", "softHertz_upper", "DOC"):
        assert not (REPOSITORY_ROOT / retired).exists(), f"旧目录仍存在：{retired}"


def test_git_does_not_track_generated_artifacts():
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    tracked = [
        Path(raw.decode("utf-8"))
        for raw in completed.stdout.split(b"\0")
        if raw
    ]
    generated = [
        str(path)
        for path in tracked
        if path.suffix.lower() in GENERATED_SUFFIXES
        or GENERATED_PARTS.intersection(path.parts)
    ]
    assert not generated, "Git 仍在跟踪生成物：\n" + "\n".join(generated)
