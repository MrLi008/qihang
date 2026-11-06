"""测试装配助手：假时钟 + 同步执行器 + 内置 specs。"""

from __future__ import annotations

from typing import Iterable, Mapping

from qihang.core.executor.mock import MockExecutor
from qihang.core.model.events import EventBus
from qihang.core.runtime.fakes import ImmediateRunner, VirtualClock
from qihang.core.runtime.orchestrator import Orchestrator
from qihang.core.runtime.scheduler import run_to_completion
from qihang.core.runtime.spec_loader import SpecLoader
from qihang.core.store.blobstore import BlobStore
from qihang.paths import SPECS_DIR


def build(
    fail_inject: Mapping[str, str] | None = None,
    *,
    delay_s: float = 1.0,
    project: Mapping[str, str] | None = None,
) -> tuple[Orchestrator, EventBus, VirtualClock, BlobStore]:
    specs = SpecLoader(SPECS_DIR).load_all()
    clock = VirtualClock()
    artifacts = BlobStore()
    bus = EventBus("R-TEST")
    executor = MockExecutor(clock, base_delay_s=delay_s, jitter_s=0.0, fail_inject=fail_inject)
    orchestrator = Orchestrator(
        specs, executor, clock, ImmediateRunner(), artifacts, bus, run_id="R-TEST", project=project
    )
    return orchestrator, bus, clock, artifacts


def execute(
    agent_id: str,
    fail_inject: Mapping[str, str] | None = None,
    *,
    delay_s: float = 1.0,
) -> tuple[Orchestrator, list, int]:
    orchestrator, bus, clock, _ = build(fail_inject, delay_s=delay_s)
    orchestrator.start(agent_id)
    ticks = run_to_completion(orchestrator, clock)
    return orchestrator, bus.drain(10_000), ticks


def paths(orchestrator: Orchestrator) -> Iterable[str]:
    return [i.task_path for i in orchestrator.tree.all_instances()]
