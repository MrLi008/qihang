"""事件桥：内核 SimpleQueue → QTimer(100ms) → Qt 信号。

GUI 主线程只做 drain + 发信号；不 tick 内核、不碰执行器、不写 journal。
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class CoreEventBridge(QObject):
    batch_ready = pyqtSignal(list)  # list[RunEvent]

    def __init__(self, bus, *, interval_ms: int = 100, limit: int = 400, parent=None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._limit = limit
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll)
        self._drained = 0

    @property
    def drained(self) -> int:
        return self._drained

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def is_active(self) -> bool:
        return self._timer.isActive()

    def poll(self) -> list:
        batch = self._bus.drain(self._limit)
        if batch:
            self._drained += len(batch)
            self.batch_ready.emit(batch)
        return batch
