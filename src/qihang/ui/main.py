"""UI 入口：`python -m qihang.ui.main` / `python run.py --gui` / `gui.cmd`。

应用启动顺序固定：依赖自检 → QApplication → ThemeManager.apply(app)（应用级 QSS）→ MainWindow。
PyQt6 采用惰性导入，保证缺依赖时先给中文提示而不是裸 traceback。
"""

from __future__ import annotations

import argparse
import sys

from qihang.paths import default_runs_dir, default_specs_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qihang-ui", description="契衡 · 阶段一 PyQt 壳")
    parser.add_argument("--theme", choices=["light", "dark"], default="light")
    parser.add_argument("--scenario", choices=["A4", "A6"], default="A4")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--specs-dir", default=str(default_specs_dir()))
    parser.add_argument("--auto-start", action="store_true", help="启动后立即跑一次")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="构造窗口后立即退出（无显示环境请配 QT_QPA_PLATFORM=offscreen）",
    )
    args = parser.parse_args(argv)

    from qihang.preflight import require_gui

    require_gui()

    from PyQt6.QtWidgets import QApplication

    from qihang.ui.theme.manager import ThemeManager
    from qihang.ui.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    theme = ThemeManager(args.theme)
    theme.apply(app)

    window = MainWindow(
        theme, specs_dir=args.specs_dir, runs_dir=default_runs_dir(), delay_s=args.delay
    )
    window.set_scenario(args.scenario)
    window.show()

    if args.self_check:
        from PyQt6.QtTest import QTest

        if args.auto_start:
            window.start_run()
            for _ in range(500):
                QTest.qWait(20)
                if window._status.text().startswith("结束"):
                    break
            print(f"GUI 自检：{window._status.text()} · DAG 节点 {len(window._scene.known_paths)}")
        else:
            QTest.qWait(200)
            print(f"GUI 自检通过：主窗口构造成功（theme={theme.name}，scenario={args.scenario}）")
        window.close()
        return 0

    if args.auto_start:
        window.start_run()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
