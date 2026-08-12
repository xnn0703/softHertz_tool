"""产品源码文档字符串覆盖率契约测试。"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCUMENTED_SOURCE_ROOTS = (
    PROJECT_ROOT / "src" / "soft_hertz_tool",
    PROJECT_ROOT / "packaging",
)


def _has_nonempty_docstring(node: ast.AST) -> bool:
    """判断 AST 节点是否拥有去除空白后仍非空的 docstring。"""

    docstring = ast.get_docstring(node, clean=False)
    return bool(docstring and docstring.strip())


def _missing_docstrings(source_root: Path) -> list[str]:
    """收集一个源码根目录中缺少 docstring 的模块、类和函数节点。"""

    missing: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative_path = path.relative_to(PROJECT_ROOT)
        if not _has_nonempty_docstring(tree):
            missing.append(f"{relative_path}:1:Module:<module>")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _has_nonempty_docstring(node):
                missing.append(
                    f"{relative_path}:{node.lineno}:{type(node).__name__}:{node.name}"
                )
    return missing


def test_product_python_nodes_have_nonempty_docstrings() -> None:
    """要求产品源码与打包脚本的模块、类及任意层级函数均有 docstring。

    该契约覆盖私有函数、dunder 方法和嵌套辅助函数，但不规定 Args、Returns
    等 docstring 的具体排版格式。
    """

    missing = [
        item
        for source_root in DOCUMENTED_SOURCE_ROOTS
        for item in _missing_docstrings(source_root)
    ]
    assert not missing, "缺少非空 docstring：\n" + "\n".join(missing)
