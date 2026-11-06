"""内核驱动：真实运行时用一个 stdlib 线程跑 tick；测试直接手动 tick。"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from qihang.core.ports import Clock

if TYPE_CHECKING:  # pragma: no cover
    from qihang.core.runtime.orchestrator import Orchestrator


class RunLoop(threading.Thread):
    """内核线程：只跑状态机，不做网络等待（等待发生在 I/O 线程池里）。"""

    def __init__(self, orchestrator: "Orchestrator", *, poll_s: float = 0.02) -> None:
        super().__init__(name="qihang-kernel", daemon=True)
        self._orch = orchestrator
        self._poll_s = poll_s
        self._stop_event = threading.Event()
        self._wake = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set() and not self._orch.is_finished():
            progress = self._orch.tick()
            self._wake.wait(0.0 if progress else self._poll_s)
            self._wake.clear()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake.set()


def run_to_completion(
    orchestrator: "Orchestrator",
    clock: Clock,
    *,
    max_ticks: int = 20_000,
    idle_limit: int = 500,
) -> int:
    """同步驱动到终态，供 CLI 与测试使用；返回 tick 次数。"""
    idle = 0
    ticks = 0
    while not orchestrator.is_finished():
        progress = orchestrator.tick()
        ticks += 1
        if progress:
            idle = 0
        else:
            idle += 1
            clock.sleep(0.005)
            if idle > idle_limit:
                raise RuntimeError(f"内核停滞：连续 {idle} 次 tick 无进展（ticks={ticks}）")
        if ticks > max_ticks:
            raise RuntimeError(f"超过最大 tick 次数 {max_ticks}")
    return ticks
