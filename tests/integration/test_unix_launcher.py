"""macOS/Linux ``run.sh`` 参数分发回归测试。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _prepare_launcher_sandbox(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """创建无需安装依赖或打开 GUI 的最小启动脚本测试仓库。

    Args:
        tmp_path: pytest 为当前用例提供的临时目录。

    Returns:
        启动脚本路径、Python 调用记录路径和子进程环境变量。
    """

    launcher = tmp_path / "run.sh"
    shutil.copy2(REPOSITORY_ROOT / "run.sh", launcher)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='launcher-test'\n")

    module_entrypoint = tmp_path / "src" / "soft_hertz_tool" / "__main__.py"
    module_entrypoint.parent.mkdir(parents=True)
    module_entrypoint.write_text('"""测试占位入口。"""\n', encoding="utf-8")

    virtualenv_bin = tmp_path / ".venv" / "bin"
    virtualenv_bin.mkdir(parents=True)
    invocation_log = tmp_path / "python-invocations.jsonl"
    python_stub = virtualenv_bin / "python"
    python_stub.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["SOFTHERTZ_TEST_INVOCATIONS"], "a", encoding="utf-8") as stream:
    json.dump(sys.argv[1:], stream)
    stream.write("\\n")
""",
        encoding="utf-8",
    )
    python_stub.chmod(0o755)
    (tmp_path / ".venv" / ".deps_installed").touch()

    environment = os.environ.copy()
    environment["SOFTHERTZ_TEST_INVOCATIONS"] = str(invocation_log)
    return launcher, invocation_log, environment


@pytest.mark.skipif(os.name == "nt", reason="run.sh 仅用于 macOS/Linux")
@pytest.mark.parametrize(
    ("arguments", "expected_invocation"),
    [
        ([], ["-m", "soft_hertz_tool"]),
        (["app"], ["-m", "soft_hertz_tool"]),
        (
            ["afdtr-sim"],
            ["-m", "soft_hertz_tool.devices.afdtr1024.simulator"],
        ),
        (
            ["qs-sim"],
            ["-m", "soft_hertz_tool.devices.afd01_qs.simulator"],
        ),
        (
            ["ka-rf-sim"],
            ["-m", "soft_hertz_tool.devices.ka_rf_unit.simulator"],
        ),
        (
            ["app", "--smoke", "--style", "Fusion"],
            ["-m", "soft_hertz_tool", "--smoke", "--style", "Fusion"],
        ),
    ],
)
def test_run_sh_forwards_empty_and_nonempty_arguments(
    tmp_path: Path,
    arguments: list[str],
    expected_invocation: list[str],
) -> None:
    """验证 Bash 3.2 下空参数不报错，非空参数保持原顺序和值。"""

    launcher, invocation_log, environment = _prepare_launcher_sandbox(tmp_path)

    completed = subprocess.run(
        ["/bin/bash", str(launcher), *arguments],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    invocations = [
        json.loads(line)
        for line in invocation_log.read_text(encoding="utf-8").splitlines()
    ]
    assert invocations[-1] == expected_invocation
