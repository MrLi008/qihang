"""GUI 规模压测探针：只在主线程读信号、记时间段，不碰内核、不做阻塞等待。

采集项：
- 心跳漂移：100ms QTimer 的实际间隔 − 100ms 的 p50/p99/max；
- DAG 渲染：每批 apply_events 耗时 p50/p99/max，相邻渲染批间隔估算 fps；
- 实例树：每批更新耗时与最大单批；
- 事件吞吐：drain 批次数、单批最大事件数、总数；
- 内存：tracemalloc 峰值（进程内 Python 堆）。
"""

from __future__ import annotations

import time
import tracemalloc
from typing import Any

from PyQt6.QtCore import QObject, QTimer


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[index]


def _stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"p50": None, "p99": None, "max": None, "samples": 0}
    return {
        "p50": round(percentile(values, 50) or 0.0, 2),
        "p99": round(percentile(values, 99) or 0.0, 2),
        "max": round(max(values), 2),
        "samples": len(values),
    }


class GuiProbe(QObject):
    def __init__(self, parent=None, *, heartbeat_ms: int = 100) -> None:
        super().__init__(parent)
        self._heartbeat_ms = heartbeat_ms
        self._timer = QTimer(self)
        self._timer.setInterval(heartbeat_ms)
        self._timer.timeout.connect(self._heartbeat)
        self._last_beat = 0.0
        self._running = False
        self._peak_bytes = 0
        self.heartbeat_drift: list[float] = []
        self.dag_ms: list[float] = []
        self.tree_ms: list[float] = []
        self.batch_sizes: list[int] = []
        self._dag_ts: list[float] = []

    def start(self) -> None:
        self.heartbeat_drift.clear()
        self.dag_ms.clear()
        self.tree_ms.clear()
        self.batch_sizes.clear()
        self._dag_ts.clear()
        tracemalloc.start()
        self._last_beat = time.perf_counter()
        self._running = True
        self._timer.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._timer.stop()
        current, peak = tracemalloc.get_traced_memory()
        self._peak_bytes = peak
        tracemalloc.stop()

    def _heartbeat(self) -> None:
        now = time.perf_counter()
        drift = (now - self._last_beat) * 1000.0 - self._heartbeat_ms
        self._last_beat = now
        self.heartbeat_drift.append(drift)

    def record_batch(self, *, size: int, tree_ms: float, dag_ms: float, dag_changed: int) -> None:
        self.batch_sizes.append(size)
        self.tree_ms.append(tree_ms)
        self.dag_ms.append(dag_ms)
        if dag_changed:
            self._dag_ts.append(time.perf_counter())

    def _fps(self) -> float | None:
        if len(self._dag_ts) < 2:
            return None
        intervals = [(b - a) * 1000.0 for a, b in zip(self._dag_ts, self._dag_ts[1:])]
        mean = sum(intervals) / len(intervals)
        if mean <= 0:
            return None
        return round(min(1000.0 / mean, 1000.0), 1)

    def report(
        self,
        *,
        scenario: str,
        instances: int,
        events_total: int,
        wall_ms: int,
        status: str,
        delay_s: float,
    ) -> dict[str, Any]:
        heartbeat = _stats(self.heartbeat_drift)
        dag = _stats(self.dag_ms)
        tree = _stats(self.tree_ms)
        fps = self._fps()
        events_batches = len(self.batch_sizes)
        peak_mb = round(self._peak_bytes / (1024.0 * 1024.0), 1)
        max_batch = max(self.batch_sizes) if self.batch_sizes else 0
        heartbeat_p99 = heartbeat["p99"] or 0.0
        tree_max = tree["max"] or 0.0
        dag_p99 = dag["p99"] or 0.0

        hints: list[str] = []
        if fps is not None and fps < 30:
            if dag_p99 < 8.0:
                hints.append("事件批节奏受限：事件桥 100ms 轮询 + 单批上限 400，不是图元渲染能力不足")
            else:
                hints.append("DAG 布局重排：每批新增节点触发 _relayout 全量重排与边重算")
        if heartbeat_p99 > 100:
            if tree_max >= 50:
                hints.append("实例树：每批 expandAll + 整批 layoutChanged 占用主线程")
            elif dag_p99 >= 50:
                hints.append("DAG 单批渲染超过 50ms，主线程被场景重排占住")
            else:
                hints.append("事件批过大，主线程单批处理时间超过心跳周期")

        return {
            "scenario": scenario,
            "status": status,
            "instances": instances,
            "delay_s": delay_s,
            "wall_ms": wall_ms,
            "heartbeat_ms": heartbeat,
            "dag_render_ms": dag,
            "fps_estimate": fps,
            "tree_batch_ms": {**tree, "total": round(sum(self.tree_ms), 2)},
            "events": {
                "total": events_total,
                "drain_batches": events_batches,
                "max_batch": max_batch,
                "avg_batch": round(sum(self.batch_sizes) / events_batches, 1) if events_batches else 0,
            },
            "memory_peak_mb": peak_mb,
            "thresholds": {"heartbeat_p99_ms": 100, "fps": 30},
            "judgement": {
                "heartbeat": "达标" if heartbeat_p99 <= 100 else "不达标",
                "fps": "达标" if (fps is not None and fps >= 30) else ("未采集" if fps is None else "不达标"),
            },
            "bottleneck_hint": "；".join(hints) or "未发现明显瓶颈",
        }
