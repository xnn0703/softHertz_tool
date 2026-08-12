"""架构依赖方向的自动化约束。"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, Tuple


PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "soft_hertz_tool"


def _python_files(root: Path) -> Iterator[Path]:
    yield from sorted(root.rglob("*.py"))


def _imports(path: Path) -> Iterator[Tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module


def _assert_no_imports(root: Path, forbidden_prefixes: tuple[str, ...]) -> None:
    violations = []
    for path in _python_files(root):
        for line, module in _imports(path):
            if module.startswith(forbidden_prefixes):
                violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{line} -> {module}")
    assert not violations, "发现违反架构依赖方向的导入：\n" + "\n".join(violations)


def test_shared_does_not_depend_on_devices_workspaces_or_app():
    _assert_no_imports(
        PACKAGE_ROOT / "shared",
        (
            "soft_hertz_tool.devices",
            "soft_hertz_tool.workspaces",
            "soft_hertz_tool.app",
        ),
    )


def test_devices_do_not_depend_on_workspaces_or_app():
    _assert_no_imports(
        PACKAGE_ROOT / "devices",
        (
            "soft_hertz_tool.workspaces",
            "soft_hertz_tool.app",
        ),
    )


def test_protocol_and_stream_modules_do_not_depend_on_qt_or_serial():
    violations = []
    for path in _python_files(PACKAGE_ROOT / "devices"):
        if path.name not in {"protocol.py", "stream.py", "models.py"}:
            continue
        for line, module in _imports(path):
            if module.startswith(("PySide6", "serial")):
                violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{line} -> {module}")
    assert not violations, "协议/流解析层出现 Qt 或串口依赖：\n" + "\n".join(violations)
