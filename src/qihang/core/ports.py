"""内核端口（Protocol）：时钟、调度器、执行器、事件汇。

四条替换点都在这里，阶段二接真实 LLM 时只换实现，不改内核。
"""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence, TypeVar

T = TypeVar("T")


class Clock(Protocol):
    def now(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class TaskRunner(Protocol):
    """把一个可调用对象放到工作线程执行；返回 Future。

    真实实现 = ThreadPoolExecutor；测试实现 = 立即执行 + 假时钟。
    """

    def submit(self, fn: Callable[[], T]) -> Future[T]: ...

    def shutdown(self, wait: bool = False) -> None: ...


class EventSink(Protocol):
    def emit(self, kind: Any, task_path: str | None = None, *, ts: float = 0.0, **payload: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class OutputDeclView:
    name: str
    block_type: str


@dataclass(frozen=True, slots=True)
class GenerateRequest:
    run_id: str
    task_path: str
    attempt: int
    spec_ref: str
    rendered_prompt: str
    input_snapshot_hash: str
    outputs: tuple[OutputDeclView, ...] = ()
    agent_id: str = ""
    role_definition: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecomposeRequest:
    run_id: str
    task_path: str
    agent_id: str
    goal: str = ""
    output_schema: str = "subtask_plan_v1"
    allowed_agent_refs: Sequence[str] = ()
    max_fanout: int = 8
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    run_id: str
    task_path: str
    artifact_text: str
    rules: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    text: str
    latency_ms: int = 0
    executor: str = "mock"
    usage: TokenUsage = field(default_factory=TokenUsage)
    ok: bool = True
    error: str | None = None


class Executor(Protocol):
    kind: str

    def generate(self, req: GenerateRequest) -> ExecutionResult: ...

    def decompose(self, req: DecomposeRequest) -> ExecutionResult: ...

    def review(self, req: ReviewRequest) -> ExecutionResult: ...
