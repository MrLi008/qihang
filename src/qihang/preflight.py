"""启动自检：缺依赖时输出中文提示，而不是裸 traceback。

CLI 入口（`run.py` / `run.cmd` / `python -m qihang`）启动时调用 `require_core()`；
GUI 入口（`gui.cmd` / `python run.py --gui`）启动时调用 `require_gui()`。
本模块只依赖标准库，避免自检本身因缺包而失败。
"""

from __future__ import annotations

import importlib.util
import sys

_PYQT_HINT = """\
GUI 需要 PyQt6，但当前环境不可用。
  安装：python -m pip install PyQt6==6.6.1 PyQt6-Qt6==6.6.2
  若已安装 PyQt6 6.11/6.12 却报 DLL 加载失败或 0xC0000139（入口点找不到），请降级到上面的 6.6.1 / Qt 6.6.2。
  只跑 CLI 则不需要 PyQt6。"""


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def require_core() -> None:
    """CLI 前置：YAML 解析是硬依赖（ruamel.yaml 或 PyYAML 任一即可）。"""
    if _has("ruamel.yaml") or _has("yaml"):
        if not _has("jsonschema"):
            sys.stderr.write(
                "提示：未检测到 jsonschema，将使用内置轻量校验器；需要严格 JSON Schema 校验时执行 "
                "python -m pip install \"jsonschema>=4.20\"（或安装 [validation] extras）。\n"
            )
        return
    sys.stderr.write(
        "启动失败：缺少 YAML 解析依赖（ruamel.yaml 或 PyYAML 任一即可）。\n"
        "  推荐：python -m pip install \"ruamel.yaml>=0.18\"\n"
        "  或：  python -m pip install PyYAML\n"
    )
    raise SystemExit(4)


def require_gui() -> None:
    """GUI 前置：PyQt6 必须可导入（含 DLL 可加载）。"""
    try:
        from PyQt6.QtWidgets import QApplication  # noqa: F401
    except (ImportError, OSError) as exc:
        sys.stderr.write(f"启动失败：PyQt6 加载失败（{exc.__class__.__name__}: {exc}）。\n{_PYQT_HINT}\n")
        raise SystemExit(4)
