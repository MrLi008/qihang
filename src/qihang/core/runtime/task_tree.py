"""实例树：唯一持有实例、父子关系与状态迁移守卫。

不变量（阶段一相关）：
- task_path 唯一
- 状态迁移只允许白名单内的边，非法迁移抛 `StatusTransitionError`
"""

from __future__ import annotations

from qihang.core.model.enums import NodeKind, Status
from qihang.core.model.runtime import TaskInstance

ALLOWED: dict[Status, frozenset[Status]] = {
    Status.PENDING: frozenset({Status.READY, Status.BLOCKED, Status.CANCELLED}),
    Status.READY: frozenset({Status.RUNNING, Status.BLOCKED, Status.CANCELLED}),
    Status.RUNNING: frozenset({Status.CHECK, Status.DONE, Status.FAILED, Status.CANCELLED}),
    Status.CHECK: frozenset({Status.DONE, Status.FAILED}),
    Status.DONE: frozenset({Status.STALE}),
    Status.FAILED: frozenset({Status.STALE}),
    Status.BLOCKED: frozenset({Status.STALE}),
    Status.STALE: frozenset({Status.PENDING}),
    Status.CANCELLED: frozenset(),
}


class StatusTransitionError(ValueError):
    code = "ILLEGAL_TRANSITION"


class TaskTree:
    def __init__(self) -> None:
        self._instances: dict[str, TaskInstance] = {}
        self._children: dict[str, list[str]] = {}

    def create(
        self,
        task_path: str,
        *,
        parent_path: str,
        spec_ref: str,
        node_kind: NodeKind,
        created_by: str = "static",
        deps: tuple[str, ...] = (),
        level: int = 0,
    ) -> TaskInstance:
        if task_path in self._instances:
            raise ValueError(f"task_path 重复: {task_path}")
        inst = TaskInstance(
            task_path=task_path,
            parent_path=parent_path,
            spec_ref=spec_ref,
            node_kind=node_kind,
            created_by=created_by,
            deps=deps,
            level=level,
        )
        self._instances[task_path] = inst
        self._children.setdefault(parent_path, []).append(task_path)
        self._children.setdefault(task_path, [])
        return inst

    def lookup(self, task_path: str) -> TaskInstance | None:
        return self._instances.get(task_path)

    def require(self, task_path: str) -> TaskInstance:
        inst = self._instances.get(task_path)
        if inst is None:
            raise KeyError(f"实例不存在: {task_path}")
        return inst

    def children(self, task_path: str) -> list[TaskInstance]:
        return [self._instances[p] for p in self._children.get(task_path, ())]

    def all_instances(self) -> list[TaskInstance]:
        return list(self._instances.values())

    def transition(self, task_path: str, to: Status) -> TaskInstance:
        inst = self.require(task_path)
        allowed = ALLOWED[inst.status]
        if to not in allowed:
            raise StatusTransitionError(f"{task_path}: 非法迁移 {inst.status.value} -> {to.value}")
        inst.status = to
        return inst

    def can_transition(self, task_path: str, to: Status) -> bool:
        inst = self._instances.get(task_path)
        return inst is not None and to in ALLOWED[inst.status]
