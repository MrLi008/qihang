"""运行期数据模型：实例、产物引用、解析结果、Run 摘要。"""

from __future__ import annotations

from dataclasses import dataclass, field

from qihang.core.model.enums import TERMINAL_STATUSES, NodeKind, Status


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    content_hash: str
    output: str
    schema: str = "text"
    size: int = 0


@dataclass(frozen=True, slots=True)
class Resolved:
    """一条 DataRef 的解析结果。

    `text` 是阶段一扩展字段：解析时顺带取出产物正文，供模板渲染直接使用；
    03 §4.2 的 Resolved 只有前五个字段，差异见 docs/05-实现偏差记录.md。
    """

    ref: str
    task_path: str
    output: str
    artifact_ref: str
    value_hash: str
    text: str = ""


@dataclass
class TaskInstance:
    task_path: str
    parent_path: str
    spec_ref: str
    node_kind: NodeKind
    status: Status = Status.PENDING
    created_by: str = "static"
    deps: tuple[str, ...] = ()
    attempt: int = 1
    outputs: dict[str, ArtifactRef] = field(default_factory=dict)
    input_snapshot: dict[str, Resolved] = field(default_factory=dict)
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    plan_doc: dict | None = None
    fanout_value: str | None = None
    fanout_index: int | None = None
    plan_item: dict | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def duration_ms(self) -> int | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return int(round((self.finished_at - self.started_at) * 1000))


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    root_path: str
    status: Status
    total_instances: int
    done: int
    failed: int
    blocked: int
    wall_time_ms: int
    coverage: str | None = None
