"""任务执行的工作线程池：内核只提交、只轮询 Future，从不阻塞等结果。"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")


class ThreadPoolRunner:
    def __init__(self, max_workers: int = 8, thread_name_prefix: str = "qihang-io") -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=thread_name_prefix)

    def submit(self, fn: Callable[[], T]) -> Future[T]:
        return self._pool.submit(fn)

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait)
