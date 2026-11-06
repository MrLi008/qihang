"""分层防火墙：core 不得依赖 Qt，也不得反向依赖 app / ui。

这条测试在 CI 的 core-only job 里先跑，后续所有改动都被它保护。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "qihang" / "core"

FORBIDDEN_PREFIXES = (
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "shiboken",
    "qihang.ui",
    "qihang.app",
)


def _module_name(node: ast.AST) -> str:
    if isinstance(node, ast.Import):
        return ",".join(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        return node.module or ""
    return ""


def test_core_has_no_qt_or_ui_imports() -> None:
    violations: list[str] = []
    for path in sorted(CORE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for module in modules:
                if any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno} imports {module}")

    assert not violations, "core 层出现被禁止的依赖:\n" + "\n".join(violations)


def test_core_has_no_qt_widget_terms() -> None:
    """粗筛：core 源码里不应出现 QWidget/QApplication 这类运行时符号。"""
    hits: list[str] = []
    for path in sorted(CORE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for needle in ("QApplication(", "QWidget(", "QTimer("):
            if needle in text:
                hits.append(f"{path.relative_to(ROOT)}: {needle}")
    assert not hits, "core 层出现 Qt 运行时符号:\n" + "\n".join(hits)
