#!/usr/bin/env python3
"""主题守卫：UI 源码不得硬编码颜色，不得用 setStyleSheet 覆盖应用级 QSS。

规则（对应 03 §1 原则 5「主题统一」）：
1. 字符串里出现 `#rgb` / `#rrggbb` / `#rrggbbaa` 一律报错（颜色必须来自 ThemeManager token）；
2. 出现 `rgb(...)` / `rgba(...)` / `hsl(...)` 字面量报错；
3. `.setStyleSheet(...)` 只允许作用在 QApplication（`app.setStyleSheet`），
   组件级覆盖一律报错——组件样式应通过 objectName / property 由应用级 QSS 命中。

不 import PyQt，可在 core-only CI job 中运行。

用法：python tools/check_theme.py [--root src/qihang]
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FUNC_COLOR = re.compile(r"\b(?:rgba?|hsla?)\s*\(", re.IGNORECASE)
ALLOWED_SETSTYLE = re.compile(r"^(?:self\.)?_?app$|^QApplication\.instance\(\)$")

ROOT = Path(__file__).resolve().parents[1]


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def scan_file(path: Path) -> list[str]:
    issues: list[str] = []
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: SYNTAX_ERROR: {exc.msg}"]
    docstrings = _docstring_node_ids(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            text = node.value
            if HEX_COLOR.search(text):
                issues.append(f"{path}:{node.lineno}: HARDCODED_HEX_COLOR: {text.strip()[:60]}")
            if FUNC_COLOR.search(text):
                issues.append(f"{path}:{node.lineno}: HARDCODED_COLOR_FUNC: {text.strip()[:60]}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setStyleSheet":
            target = ast.unparse(node.func.value)
            if not ALLOWED_SETSTYLE.match(target):
                issues.append(f"{path}:{node.lineno}: WIDGET_SETSTYLESHEET: {target}.setStyleSheet(...)")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UI 主题守卫")
    parser.add_argument("--root", default="src/qihang")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if not root.is_absolute():
        root = ROOT / root

    files = sorted(p for p in (root / "ui").rglob("*.py")) if (root / "ui").exists() else []
    if not files:
        print(f"[check_theme] 未找到 UI 源码（{root / 'ui'}），跳过。")
        return 0

    issues: list[str] = []
    for path in files:
        issues.extend(scan_file(path))

    print(f"[check_theme] 扫描 {len(files)} 个 UI 源文件")
    if issues:
        for issue in issues:
            print(f"  FAIL {issue}")
        print(f"[check_theme] 失败：{len(issues)} 处硬编码颜色或组件级 setStyleSheet")
        return 1
    print("[check_theme] 通过：无硬编码颜色，setStyleSheet 仅限应用级。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
