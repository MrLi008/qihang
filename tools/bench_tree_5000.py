#!/usr/bin/env python3
"""S-1 压测骨架：5000 节点实例树。

对应 02 §5 的 S-1（可视化容量）中"纯数据侧"的那一半：
- 构建：5000 节点 TaskTree 需要多久；
- 查询：随机 lookup 的 p50 / p99；
- 增量刷新：200 个节点做 READY→RUNNING→CHECK→DONE 迁移并生成发给视图的 patch 负载，
  这一项对应 02 的判据"200 节点增量刷新 ≤ 30ms"；
- 快照：全量 asdict 导出耗时（离线导出与 journal 重放都会用到）。

不测的部分（明确留给 GUI 压测）：主线程心跳 p99、800 可见节点帧率——需要真实
QGraphicsScene 渲染，本轮只交付 DAG 空壳，见 docs/05-实现偏差记录.md。

用法：
    python tools/bench_tree_5000.py
    python tools/bench_tree_5000.py --nodes 5000 --repeat 3 --out bench-out/tree_5000.json
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import statistics
import sys
import time
import tracemalloc
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qihang.core.model.enums import NodeKind, Status  # noqa: E402
from qihang.core.runtime.task_tree import TaskTree  # noqa: E402

INCREMENTAL_BUDGET_MS = 30.0
INCREMENTAL_NODES = 200


def build_tree(node_count: int) -> tuple[TaskTree, str, list[str]]:
    """构造 root → 若干 EXPAND → 每个 EXPAND 约 99 个 TASK 的实例树。"""
    tree = TaskTree()
    root = "BENCH"
    tree.create(root, parent_path="", spec_ref="A4", node_kind=NodeKind.TASK, created_by="root")
    expands: list[str] = []
    seq = 0
    created = 1
    while created < node_count:
        if created % 100 == 1:
            seq += 1
            path = f"BENCH/E{seq}"
            tree.create(path, parent_path=root, spec_ref="E1", node_kind=NodeKind.EXPAND)
            expands.append(path)
        else:
            parent = expands[-1]
            tree.create(
                f"{parent}/T{created}",
                parent_path=parent,
                spec_ref="S2",
                node_kind=NodeKind.TASK,
            )
        created += 1
    return tree, root, expands


def _ms(fn: Callable[[], Any]) -> float:
    started = time.perf_counter()
    fn()
    return (time.perf_counter() - started) * 1000.0


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((len(ordered) - 1) * q)))
    return round(ordered[idx], 3)


def _patch_payload(inst) -> dict[str, Any]:
    """模拟发给 InstanceTreeModel 的增量 patch（只带变化字段）。"""
    return {
        "task_path": inst.task_path,
        "status": inst.status.value,
        "duration_ms": inst.duration_ms,
        "error": inst.error,
    }


def run(nodes: int, repeat: int) -> dict[str, Any]:
    build_ms = []
    peak_bytes = 0
    tree: TaskTree | None = None
    root = ""
    expands: list[str] = []
    for _ in range(repeat):
        tracemalloc.start()
        started = time.perf_counter()
        tree, root, expands = build_tree(nodes)
        build_ms.append((time.perf_counter() - started) * 1000.0)
        peak_bytes = max(peak_bytes, tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()

    assert tree is not None
    actual_nodes = len(tree.all_instances())
    paths = [inst.task_path for inst in tree.all_instances()]

    rng = random.Random(20261105)
    lookup_samples = [rng.choice(paths) for _ in range(min(actual_nodes, 5000))]
    lookup_us = []
    for path in lookup_samples:
        started = time.perf_counter()
        tree.lookup(path)
        lookup_us.append((time.perf_counter() - started) * 1_000_000.0)

    # 取前 200 个叶子任务做迁移（不含 EXPAND 节点）
    leaves = [p for p in paths if "/T" in p][:INCREMENTAL_NODES]

    def incremental() -> None:
        patches = []
        for path in leaves:
            tree.require(path).status = Status.PENDING  # 复位，保证 repeat 可重入
            for to in (Status.READY, Status.RUNNING, Status.CHECK, Status.DONE):
                inst = tree.transition(path, to)
                if to is Status.DONE:
                    inst.finished_at = inst.started_at
                patches.append(_patch_payload(inst))
        assert len(patches) == len(leaves) * 4

    incremental_ms = [_ms(incremental) for _ in range(repeat)]

    snapshot_ms = [_ms(lambda: [asdict(i) for i in tree.all_instances()]) for _ in range(repeat)]
    children_of_root = len(tree.children(root))

    return {
        "spike": "S-1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "python": f"{platform.python_version()} ({platform.python_implementation()})",
        "parameters": {
            "nodes": nodes,
            "repeat": repeat,
            "incremental_nodes": INCREMENTAL_NODES,
            "expands": len(expands),
        },
        "results": {
            "actual_nodes": actual_nodes,
            "root_children": children_of_root,
            "build_ms": [round(v, 3) for v in build_ms],
            "build_ms_p50": _percentile(build_ms, 0.5),
            "build_nodes_per_s": round(actual_nodes / (statistics.mean(build_ms) / 1000.0), 1),
            "lookup_us_p50": _percentile(lookup_us, 0.5),
            "lookup_us_p99": _percentile(lookup_us, 0.99),
            "incremental_ms": [round(v, 3) for v in incremental_ms],
            "incremental_ms_p50": _percentile(incremental_ms, 0.5),
            "incremental_ms_p99": _percentile(incremental_ms, 0.99),
            "snapshot_ms_p50": _percentile(snapshot_ms, 0.5),
            "tree_peak_mib": round(peak_bytes / (1024 * 1024), 2),
        },
        "budgets": {
            "incremental_ms_p99_max": INCREMENTAL_BUDGET_MS,
            "gui_heartbeat_p99_max": 100.0,
            "gui_800_fps_min": 30,
        },
        "verdict": {
            "incremental_data_side": "PASS"
            if _percentile(incremental_ms, 0.99) <= INCREMENTAL_BUDGET_MS
            else "FAIL",
            "gui_side": "NOT_MEASURED（需要 QGraphicsScene 渲染，本轮只交付空壳）",
        },
    }


def _print_report(report: dict[str, Any]) -> None:
    r = report["results"]
    print(f"\nS-1 · 实例树压测（{report['parameters']['nodes']} 节点，repeat={report['parameters']['repeat']}）")
    print(f"  实际节点数            {r['actual_nodes']}（root 子节点 {r['root_children']}，expand {report['parameters']['expands']}）")
    print(f"  构建 p50              {r['build_ms_p50']:.2f} ms  （{r['build_nodes_per_s']:.0f} nodes/s）")
    print(f"  lookup p50 / p99      {r['lookup_us_p50']:.3f} / {r['lookup_us_p99']:.3f} µs")
    print(f"  200 节点增量迁移 p50  {r['incremental_ms_p50']:.2f} ms")
    print(f"  200 节点增量迁移 p99  {r['incremental_ms_p99']:.2f} ms  （预算 ≤ {INCREMENTAL_BUDGET_MS:.0f} ms）")
    print(f"  全量快照 p50          {r['snapshot_ms_p50']:.2f} ms")
    print(f"  树峰值内存            {r['tree_peak_mib']:.2f} MiB")
    print(f"  判定                  data-side={report['verdict']['incremental_data_side']}；gui-side={report['verdict']['gui_side']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S-1 5000 节点实例树压测")
    parser.add_argument("--nodes", type=int, default=5000)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--out", default="bench-out/tree_5000.json")
    args = parser.parse_args(argv)

    report = run(args.nodes, args.repeat)
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_report(report)
    print(f"\n原件已落盘：{out}")
    return 0 if report["verdict"]["incremental_data_side"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
