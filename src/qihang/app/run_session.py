"""应用服务：把 spec / 执行器 / 存储 / 事件总线装配成一次 Run 会话。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from qihang.core.executor.mock import MockExecutor
from qihang.core.model.events import EventBus
from qihang.core.ports import Clock
from qihang.core.runtime.clock import SystemClock
from qihang.core.runtime.orchestrator import Orchestrator
from qihang.core.runtime.runner import ThreadPoolRunner
from qihang.core.runtime.scheduler import RunLoop
from qihang.core.runtime.spec_loader import SpecLoader
from qihang.core.store.blobstore import BlobStore
from qihang.core.store.journal import JsonlJournal


@dataclass
class RunSession:
    run_id: str
    bus: EventBus
    orchestrator: Orchestrator
    artifacts: BlobStore
    runner: ThreadPoolRunner
    journal: JsonlJournal
    kernel: RunLoop | None = None

    # ---- 用例入口：UI 只调这两个方法，不直接碰 Orchestrator / RunLoop ----
    def start(self, agent_id: str, *, background: bool = True) -> str:
        """发起 Run；background=True 时由应用层负责起内核线程。返回根实例路径。"""
        root = self.orchestrator.start(agent_id)
        if background:
            self.kernel = RunLoop(self.orchestrator)
            self.kernel.start()
        return root

    @property
    def running(self) -> bool:
        return self.kernel is not None and self.kernel.is_alive()

    def stop_kernel(self, timeout: float = 2.0) -> None:
        if self.kernel is not None:
            self.kernel.stop()
            self.kernel.join(timeout=timeout)
            self.kernel = None

    def close(self) -> None:
        self.stop_kernel()
        self.runner.shutdown(wait=False)
        self.journal.close()


def create_session(
    specs_dir: Path,
    run_dir: Path,
    *,
    run_id: str = "R-001",
    delay_s: float = 1.0,
    fail_inject: Mapping[str, str] | None = None,
    max_workers: int = 8,
    clock: Clock | None = None,
) -> RunSession:
    clock = clock or SystemClock()
    specs = SpecLoader(specs_dir).load_all()
    artifacts = BlobStore(run_dir / "blobs")
    bus = EventBus(run_id)
    runner = ThreadPoolRunner(max_workers=max_workers)
    executor = MockExecutor(clock, base_delay_s=delay_s, fail_inject=fail_inject)
    orchestrator = Orchestrator(specs, executor, clock, runner, artifacts, bus, run_id=run_id)
    journal = JsonlJournal(run_dir / "journal.jsonl")
    return RunSession(run_id, bus, orchestrator, artifacts, runner, journal)
