"""强制依赖规则：core 不得依赖任何界面层。"""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_ROOTS = {"textual", "rich", "tui", "web", "desktop", "mobile"}
CORE_ROOT = Path(__file__).resolve().parents[1] / "core"


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_has_no_ui_imports():
    violations = {}
    for path in CORE_ROOT.rglob("*.py"):
        forbidden = imported_roots(path) & FORBIDDEN_ROOTS
        if forbidden:
            violations[str(path)] = sorted(forbidden)
    assert not violations, f"core 出现界面层依赖: {violations}"


def test_core_has_no_direct_io():
    """core 不允许直接 print / input，输出必须通过事件交给前端。"""
    offenders = []
    for path in CORE_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"print", "input"}:
                    offenders.append(f"{path}:{node.lineno}:{node.func.id}")
    assert not offenders, f"core 出现直接 IO: {offenders}"
