#!/usr/bin/env python3
"""契衡 · 免安装启动器（不要求 pip install，不改全局环境变量）。

用法（任意当前目录均可，路径自动解析到本文件所在的 code/src）：

    python run.py run --scenario a4        # CLI，参数原样透传给 qihang.cli
    python run.py --gui                    # 启动 GUI（需要 PyQt6）
    python run.py --gui --self-check       # 只构造窗口并退出（可配 QT_QPA_PLATFORM=offscreen）

Windows 双击入口：run.cmd（CLI）、gui.cmd（GUI）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

_USAGE = """\
契衡 · 免安装启动器

  python run.py run --scenario a4          跑 CLI（a3/a4/a5/a6/all）
  python run.py run --scenario a4 --delay 1.0
  python run.py --gui                      启动主窗口（需要 PyQt6）
  python run.py --gui --self-check         自检窗口构造（无显示环境配 QT_QPA_PLATFORM=offscreen）

Windows 下也可双击：run.cmd（CLI，参数透传）、gui.cmd（GUI）。
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    sys.path.insert(0, str(SRC))

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_USAGE)
        return 0 if argv else 2

    if argv[0] == "--gui":
        from qihang.ui.main import main as gui_main

        return gui_main(argv[1:])

    from qihang.cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ModuleNotFoundError as exc:
        sys.stderr.write(
            f"启动失败：{exc}。\n"
            "请确认 code/src 目录完整（本启动器会把该目录加入 sys.path）；"
            "若仍失败，请检查 Python 版本是否为 3.11。\n"
        )
        raise SystemExit(5)
