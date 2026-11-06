#!/usr/bin/env python3
"""S-3 压测骨架：800 条实例状态批量写回。

对应 02 §5 的 S-3（写库卡顿）。本脚本直接压 `core/store/projection.ProjectionWriter`：
- 场景 A：800 条事件作为一批提交，重复 N 批，看单批 p99 是否 ≤ 8ms；
- 场景 B：800 实例 × 3 次写 = 2400 条一次性积压，按 200 条/批排空，看批耗时与积压时延；
- 附送一项单写者检查：从别的线程调用 enqueue 必须抛 `WriterThreadError`。

判定阈值来自 02 §5：单批 p99 ≤ 8ms、索引落后 ≤ 1s、无队列积压增长。

用法：
    python tools/bench_writeback_800.py
    python tools/bench_writeback_800.py --instances 800 --writes 3 --repeat 10 --out bench-out/writeback_800.json
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qihang.core.model.events import RunEvent  # noqa: E402
from qihang.core.model.enums import EventKind  # noqa: E402
from qihang.core.store.projection import ProjectionWriter, WriterThreadError  # noqa: E402

BATCH_BUDGET_MS = 8.0
LAG_BUDGET_MS = 1000.0


def make_events(count: int, *, seq_start: int = 1) -> list[RunEvent]:
    events = []
    for i in range(count):
        events.append(
            RunEvent(
                seq=seq_start + i,
                run_id="BENCH-S3",
                kind=EventKind.INSTANCE_STATE.value,
                task_path=f"BENCH/E1/T{i % 800}",
                ts=time.time(),
                payload={
                    "from": "RUNNING" if i % 2 else "READY",
                    "to": "DONE",
                    "duration_ms": 1000 + i % 7,
                    "attempt": 1,
                },
            )
        )
    return events


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((len(ordered) - 1) * q)))
    return round(ordered[idx], 3)


def _writer_thread_guard(db: Path) -> bool:
    """从子线程调用 enqueue，必须被拒绝。返回 True 表示守卫生效。"""
    writer = ProjectionWriter(db)
    result: dict[str, Any] = {}

    def worker() -> None:
        try:
            writer.enqueue(make_events(1)[0])
            result["raised"] = False
        except WriterThreadError as exc:
            result["raised"] = True
            result["code"] = exc.code

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    writer.close()
    return bool(result.get("raised"))


def run(instances: int, writes: int, repeat: int, db_path: Path) -> dict[str, Any]:
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-wal", "-shm"):
        extra = db_path.with_name(db_path.name + suffix)
        if extra.exists():
            extra.unlink()

    owner_thread_id = threading.get_ident()

    # ---------- 场景 A：单批 800 条 ----------
    batch_ms: list[float] = []
    writer = ProjectionWriter(db_path, batch_size=instances, clock=time.perf_counter)
    seq = 1
    for _ in range(repeat):
        writer.enqueue_many(make_events(instances, seq_start=seq))
        stat = writer.drain(limit=instances)
        batch_ms.append(stat.batch_ms)
        seq += instances
    rows_a = writer.count()
    writer.close()

    # ---------- 场景 B：800×writes 条积压，200 条/批排空 ----------
    db_b = db_path.with_name(db_path.stem + "-backlog" + db_path.suffix)
    if db_b.exists():
        db_b.unlink()
    backlog = make_events(instances * writes)
    writer = ProjectionWriter(db_b, batch_size=200, clock=time.perf_counter)
    enqueued_at = time.perf_counter()
    writer.enqueue_many(backlog)
    queue_full_ms = (time.perf_counter() - enqueued_at) * 1000.0
    per_batch: list[float] = []
    lags: list[float] = []
    backlog_sizes: list[int] = []
    total_started = time.perf_counter()
    while True:
        stat = writer.drain()
        if stat.rows == 0:
            break
        per_batch.append(stat.batch_ms)
        lags.append(stat.lag_ms)
        backlog_sizes.append(stat.backlog)
    total_ms = (time.perf_counter() - total_started) * 1000.0
    rows_b = writer.count()
    writer.close()

    guard = _writer_thread_guard(db_path.with_name(db_path.stem + "-guard" + db_path.suffix))

    return {
        "spike": "S-3",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "python": f"{platform.python_version()} ({platform.python_implementation()})",
        "parameters": {
            "instances": instances,
            "writes_per_instance": writes,
            "repeat": repeat,
            "sqlite": "WAL + synchronous=NORMAL，单写者（属主线程 %d）" % owner_thread_id,
        },
        "scenario_a_single_batch": {
            "batch_rows": instances,
            "batches": repeat,
            "rows_written": rows_a,
            "batch_ms": [round(v, 3) for v in batch_ms],
            "p50_ms": percentile(batch_ms, 0.5),
            "p99_ms": percentile(batch_ms, 0.99),
            "max_ms": round(max(batch_ms), 3),
        },
        "scenario_b_backlog": {
            "total_rows": len(backlog),
            "rows_written": rows_b,
            "batch_size": 200,
            "batches": len(per_batch),
            "enqueue_ms": round(queue_full_ms, 3),
            "total_drain_ms": round(total_ms, 3),
            "batch_p50_ms": percentile(per_batch, 0.5),
            "batch_p99_ms": percentile(per_batch, 0.99),
            "max_lag_ms": round(max(lags or [0.0]), 3),
            "max_backlog": max(backlog_sizes or [0]),
            "final_backlog": backlog_sizes[-1] if backlog_sizes else 0,
        },
        "owner_thread_guard": {"raised": guard, "verdict": "PASS" if guard else "FAIL"},
        "budgets": {"batch_p99_ms_max": BATCH_BUDGET_MS, "index_lag_ms_max": LAG_BUDGET_MS},
        "verdict": {
            "scenario_a": "PASS" if percentile(batch_ms, 0.99) <= BATCH_BUDGET_MS else "FAIL",
            "scenario_b": "PASS"
            if percentile(per_batch, 0.99) <= BATCH_BUDGET_MS and max(lags or [0.0]) <= LAG_BUDGET_MS
            else "FAIL",
        },
    }


def _print_report(report: dict[str, Any]) -> None:
    a = report["scenario_a_single_batch"]
    b = report["scenario_b_backlog"]
    print(f"\nS-3 · 批量写回压测（{report['parameters']['instances']} 实例 / {report['parameters']['writes_per_instance']} 次写）")
    print(f"  A. 单批 {a['batch_rows']} 条 × {a['batches']} 批：p50 {a['p50_ms']:.2f}ms，p99 {a['p99_ms']:.2f}ms，max {a['max_ms']:.2f}ms（预算 {BATCH_BUDGET_MS:.0f}ms）")
    print(f"     rows_written={a['rows_written']}")
    print(f"  B. 积压 {b['total_rows']} 条按 {b['batch_size']}/批排空：{b['batches']} 批，批 p99 {b['batch_p99_ms']:.2f}ms，总 {b['total_drain_ms']:.2f}ms")
    print(f"     max_lag={b['max_lag_ms']:.2f}ms（预算 {LAG_BUDGET_MS:.0f}ms），max_backlog={b['max_backlog']}，final_backlog={b['final_backlog']}")
    print(f"  C. 单写者线程守卫：{report['owner_thread_guard']['verdict']}")
    print(f"  判定：A={report['verdict']['scenario_a']}，B={report['verdict']['scenario_b']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S-3 800 条批量写回压测")
    parser.add_argument("--instances", type=int, default=800)
    parser.add_argument("--writes", type=int, default=3)
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--out", default="bench-out/writeback_800.json")
    parser.add_argument("--db", default="bench-out/writeback.sqlite")
    parser.add_argument("--keep-db", action="store_true", help="保留 sqlite 文件")
    args = parser.parse_args(argv)

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    db = Path(args.db)
    if not db.is_absolute():
        db = ROOT / db
    out.parent.mkdir(parents=True, exist_ok=True)

    report = run(args.instances, args.writes, args.repeat, db)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_report(report)
    print(f"\n原件已落盘：{out}")

    if not args.keep_db:
        for path in db.parent.glob(db.stem + "*.sqlite*"):
            path.unlink(missing_ok=True)
        shutil.rmtree(db.parent / "__pycache__", ignore_errors=True)
    ok = report["verdict"]["scenario_a"] == "PASS" and report["verdict"]["scenario_b"] == "PASS"
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
