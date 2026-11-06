#!/usr/bin/env python3
"""线程与分层守卫（静态、无需 PyQt，可在 core-only CI job 运行）。

对应 03 §1 原则 1/2/3：
- GUI 源码（`qihang/ui/**`）不得出现 `time.sleep`、阻塞式 `Future.result()`、网络库、
  sqlite3 直连，也不得直接 import `qihang.core.store` / `qihang.core.executor`；
- 应用服务层（`qihang/app/**`）不得出现 `time.sleep` 与网络库（用例编排允许小文件 IO）；
- 内核（`qihang/core/**`）不得 import Qt，也不得反向 import `qihang.ui` / `qihang.app`。

这只是静态粗筛，真正的守卫是 `tests/test_layering.py`（AST 精确扫描 import）+ 人工评审。

用法：python tools/check_ui_thread.py [--root src/qihang]
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NETWORK_MODULES = {"requests", "urllib", "urllib3", "http", "socket", "aiohttp", "httpx"}
QT_PREFIXES = ("PyQt5", "PyQt6", "PySide2", "PySide6", "shiboken", "sip")

UI_FORBIDDEN_IMPORTS = NETWORK_MODULES | {"sqlite3"}
UI_FORBIDDEN_QIHANG = {
    "qihang.core.store",
    "qihang.core.executor",
    "qihang.core.runtime",
    "qihang.core.protocol",
}
APP_FORBIDDEN_IMPORTS = NETWORK_MODULES


def _imports(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = "." * node.level + module
            out.append((node.lineno, module))
            for alias in node.names:
                out.append((node.lineno, f"{module}.{alias.name}") if module else (node.lineno, alias.name))
    return out


def _matches(module: str, forbidden: set[str]) -> bool:
    return any(module == item or module.startswith(item + ".") for item in forbidden)


def scan(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: SYNTAX_ERROR: {exc.msg}"]

    issues: list[str] = []
    part = path.as_posix()
    is_ui = "/ui/" in part
    is_app = "/app/" in part
    is_core = "/core/" in part

    for lineno, module in _imports(tree):
        if is_ui and _matches(module, UI_FORBIDDEN_IMPORTS):
            issues.append(f"{path}:{lineno}: UI_FORBIDDEN_IMPORT: {module}")
        if is_ui and _matches(module, UI_FORBIDDEN_QIHANG):
            issues.append(f"{path}:{lineno}: UI_REACHES_INTO_CORE: {module}")
        if is_app and _matches(module, APP_FORBIDDEN_IMPORTS):
            issues.append(f"{path}:{lineno}: APP_FORBIDDEN_IMPORT: {module}")
        if is_core and (module.startswith(QT_PREFIXES) or module.startswith("qihang.ui") or module.startswith("qihang.app")):
            issues.append(f"{path}:{lineno}: CORE_LAYER_VIOLATION: {module}")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        target = ast.unparse(node.func.value)
        if attr == "sleep" and (is_ui or is_app) and not target.startswith("QThread"):
            issues.append(f"{path}:{node.lineno}: GUI_THREAD_SLEEP: {target}.sleep(...)")
        if attr == "result" and is_ui and not node.args and not node.keywords:
            issues.append(f"{path}:{node.lineno}: BLOCKING_FUTURE_RESULT: {target}.result()")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GUI 线程与分层静态守卫")
    parser.add_argument("--root", default="src/qihang")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if not root.is_absolute():
        root = ROOT / root

    files = sorted(root.rglob("*.py"))
    issues: list[str] = []
    for path in files:
        issues.extend(scan(path))

    print(f"[check_ui_thread] 扫描 {len(files)} 个源文件（core/app/ui）")
    if issues:
        for issue in issues:
            print(f"  FAIL {issue}")
        print(f"[check_ui_thread] 失败：{len(issues)} 处违规")
        return 1
    print("[check_ui_thread] 通过：GUI 线程无 sleep/阻塞调用，core 未反向依赖 UI/APP。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
