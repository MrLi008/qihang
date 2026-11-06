"""UI 入口：`python -m qihang.ui.main` / `python run.py --gui` / `gui.cmd`。

应用启动顺序固定：依赖自检 → QApplication → ThemeManager.apply(app)（应用级 QSS）→ MainWindow。
PyQt6 采用惰性导入，保证缺依赖时先给中文提示而不是裸 traceback。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from qihang.paths import default_bench_dir, default_runs_dir, default_specs_dir


def _print_summary(report: dict, out_file: Path) -> None:
    heartbeat = report.get("heartbeat_ms") or {}
    dag = report.get("dag_render_ms") or {}
    tree = report.get("tree_batch_ms") or {}
    events = report.get("events") or {}
    print(
        f"GUI 规模压测：{report.get('scenario')} · 实例 {report.get('instances')} · "
        f"wall {report.get('wall_ms')}ms · delay {report.get('delay_s')}s"
    )
    print(
        "心跳漂移(ms)："
        f"p50={heartbeat.get('p50')} p99={heartbeat.get('p99')} max={heartbeat.get('max')} "
        f"（{heartbeat.get('samples')} 次采样）"
    )
    print(
        "DAG 每批渲染(ms)："
        f"p50={dag.get('p50')} p99={dag.get('p99')} max={dag.get('max')} "
        f"批次数={dag.get('samples')} · 估算帧率={report.get('fps_estimate')} fps"
    )
    print(
        "实例树批量更新(ms)："
        f"total={tree.get('total')} p50={tree.get('p50')} p99={tree.get('p99')} "
        f"最大单批={tree.get('max')}"
    )
    print(
        "事件："
        f"总数={events.get('total')} drain批次={events.get('drain_batches')} "
        f"单批最大={events.get('max_batch')} 平均={events.get('avg_batch')}"
    )
    print(f"内存峰值：{report.get('memory_peak_mb')} MB（tracemalloc）")
    judgement = report.get("judgement") or {}
    print(
        f"判定：心跳 p99 {judgement.get('heartbeat')}（阈值 100ms）；"
        f"帧率 {judgement.get('fps')}（阈值 30fps）"
    )
    print(f"瓶颈提示：{report.get('bottleneck_hint')}")
    print(f"指标已落盘：{out_file}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qihang-ui", description="契衡 · 阶段一 PyQt 壳")
    parser.add_argument("--theme", choices=["light", "dark"], default="light")
    parser.add_argument("--scenario", default="A4", help="specs 目录中的 agent 标识，如 A4 / A7")
    parser.add_argument("--delay", type=float, default=1.0, help="每个任务的基础耗时（秒）")
    parser.add_argument("--specs-dir", default=str(default_specs_dir()))
    parser.add_argument("--auto-start", action="store_true", help="启动后立即跑一次")
    parser.add_argument("--bench", action="store_true", help="跑完输出规模指标 JSON 并自动退出")
    parser.add_argument("--bench-out", default=str(default_bench_dir()))
    parser.add_argument("--bench-timeout", type=float, default=180.0, help="压测最长等待秒数")
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
    scenario = args.scenario.upper()
    if scenario not in window.scenario_names:
        print(
            f"场景不存在：{args.scenario}；可用：{', '.join(window.scenario_names) or '（specs 目录为空）'}",
            file=sys.stderr,
        )
        window.close()
        return 2
    window.set_scenario(scenario)
    window.show()

    if args.bench:
        from PyQt6.QtTest import QTest

        window.start_run()
        deadline = time.monotonic() + args.bench_timeout
        while time.monotonic() < deadline and not window.run_finished:
            QTest.qWait(10)
        report = window.bench_report()
        if report is None:
            report = {
                "scenario": scenario,
                "status": "TIMEOUT",
                "instances": len(window._tree_model.known_paths),
                "events": {"total": window._events_total},
            }
        out_dir = Path(args.bench_out)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"gui_{scenario}_{report.get('instances') or 0}nodes.json"
        out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_summary(report, out_file)
        window.close()
        return 0 if report.get("status") != "TIMEOUT" else 3

    if args.self_check:
        from PyQt6.QtTest import QTest

        if args.auto_start:
            window.start_run()
            for _ in range(500):
                QTest.qWait(20)
                if window.run_finished:
                    break
            print(f"GUI 自检：{window._status.text()} · DAG 节点 {len(window._scene.known_paths)}")
        else:
            QTest.qWait(200)
            print(f"GUI 自检通过：主窗口构造成功（theme={theme.name}，scenario={scenario}）")
        window.close()
        return 0

    if args.auto_start:
        window.start_run()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
