"""真实时钟：只有 I/O 工作线程可以调用 sleep，内核线程与 GUI 线程禁止等待。"""

from __future__ import annotations

import time


class SystemClock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)
