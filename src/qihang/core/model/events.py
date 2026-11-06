"""事件模型与事件总线。

约定：所有事件由内核线程产生（I/O 工作线程只返回结果，不直接发事件），
因此 `seq` 单调且无并发写。总线只暴露 `SimpleQueue`，不触碰任何 UI 类型。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from queue import SimpleQueue
from typing import Any

from qihang.core.model.enums import EventKind


@dataclass(frozen=True, slots=True)
class RunEvent:
    seq: int
    run_id: str
    kind: str
    task_path: str | None
    ts: float
    payload: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.queue: SimpleQueue[RunEvent] = SimpleQueue()
        self._seq = itertools.count(1)

    def emit(
        self,
        kind: EventKind | str,
        task_path: str | None = None,
        *,
        ts: float = 0.0,
        **payload: Any,
    ) -> RunEvent:
        event = RunEvent(
            seq=next(self._seq),
            run_id=self.run_id,
            kind=kind.value if isinstance(kind, EventKind) else str(kind),
            task_path=task_path,
            ts=ts,
            payload=dict(payload),
        )
        self.queue.put(event)
        return event

    def drain(self, limit: int = 400) -> list[RunEvent]:
        """最多取 limit 条；GUI 以 100ms 节奏调用，单批有上限防事件风暴。"""
        items: list[RunEvent] = []
        for _ in range(limit):
            try:
                items.append(self.queue.get_nowait())
            except Exception:
                break
        return items
