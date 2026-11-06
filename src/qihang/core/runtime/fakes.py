"""测试替身：虚拟时钟与同步执行器。

生产代码不放测试替身会让"可注入时钟"无法复用，因此这两个类由 core 提供，
但只用于测试与基准脚本，不参与正常 GUI/CLI 运行。
"""

from __future__ import annotations

from concurrent.futures import Future
from typing import Callable, TypeVar

T = TypeVar("T")


class VirtualClock:
    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self._t += seconds

    def advance(self, seconds: float) -> float:
        self._t += seconds
        return self._t


class ImmediateRunner:
    """在当前线程立即执行，供单测使用（生产用 ThreadPoolRunner）。"""

    def submit(self, fn: Callable[[], T]) -> Future[T]:
        future: Future[T] = Future()
        try:
            future.set_result(fn())
        except Exception as exc:  # noqa: BLE001 - 由调用方通过 Future 处理
            future.set_exception(exc)
        return future

    def shutdown(self, wait: bool = False) -> None:
        return None
