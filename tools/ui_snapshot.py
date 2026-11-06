#!/usr/bin/env python3
"""GUI 证据脚本：离屏跑一次 A4，抓到"运行中"和"结束"两张窗口截图。

用法（需要 PyQt6）：
    python tools/ui_snapshot.py --delay 0.8 --out-dir bench-out
产物：
    bench-out/ui-a4-midrun.png   可见 RUNNING / DONE 混合状态
    bench-out/ui-a4-final.png    全部终态
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from qihang.paths import SPECS_DIR  # noqa: E402
from qihang.ui.theme.manager import ThemeManager  # noqa: E402
from qihang.ui.windows.main_window import MainWindow  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GUI 截图证据")
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--out-dir", default="bench-out")
    args = parser.parse_args(argv)

    out = Path(args.out_dir)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv[:1])
    theme = ThemeManager("light")
    theme.apply(app)
    window = MainWindow(theme, specs_dir=SPECS_DIR, runs_dir=ROOT / ".qihang" / "ui-runs", delay_s=args.delay)
    window.set_scenario("A4")
    window.resize(1180, 760)
    window.show()
    window.start_run()

    # 等到展开子实例出现，抓一张"运行中"
    mid_shot = out / "ui-a4-midrun.png"
    elapsed = 0
    while elapsed < 8000 and "/A4/E1/S2.1" not in window._tree_model.known_paths:
        QTest.qWait(20)
        elapsed += 20
    QTest.qWait(300)
    window.grab().save(str(mid_shot))

    # 跑到结束
    while elapsed < 20_000 and not window._status.text().startswith("结束"):
        QTest.qWait(20)
        elapsed += 20
    final_shot = out / "ui-a4-final.png"
    window.grab().save(str(final_shot))

    print(f"status: {window._status.text()}")
    print(f"tree instances: {len(window._tree_model.known_paths)}")
    print(f"dag nodes: {len(window._scene.known_paths)}")
    print(f"events: {window._events_total}")
    print(f"midrun: {mid_shot}")
    print(f"final:  {final_shot}")
    window.close()
    return 0 if window._status.text().startswith("结束") else 2


if __name__ == "__main__":
    raise SystemExit(main())
