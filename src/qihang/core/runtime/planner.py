"""展开点规划：静态 fan-out 与动态 plan 的实例命名。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from qihang.core.errors import PlanError
from qihang.core.model.spec import SubtaskNode


@dataclass(frozen=True, slots=True)
class FanoutItem:
    index: int
    key: str
    value: str


@dataclass(frozen=True, slots=True)
class FanoutPlan:
    expand_path: str
    pattern: str
    items: tuple[FanoutItem, ...]
    instance_paths: tuple[str, ...]


def values_from_text(text: str) -> list[str]:
    """fanout_by 的结果：优先按 JSON 数组解析，退化为按行切分。"""
    stripped = text.strip()
    if not stripped:
        return []
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        return [str(x) for x in data]
    return [line.strip() for line in stripped.splitlines() if line.strip()]


def plan_static(expand_path: str, node: SubtaskNode, values: Sequence[str]) -> FanoutPlan:
    if len(values) > node.max_instances:
        raise PlanError(
            f"展开项 {len(values)} 超过 max_instances={node.max_instances}",
            code="FANOUT_EXCEEDED",
        )
    items = [FanoutItem(index=i, key=str(v), value=str(v)) for i, v in enumerate(values, 1)]
    paths = tuple(f"{expand_path}/{node.instance_id_pattern.format(index=i.index, key=i.value)}" for i in items)
    return FanoutPlan(expand_path=expand_path, pattern=node.instance_id_pattern, items=tuple(items), instance_paths=paths)


def parse_plan_doc(
    doc: dict[str, Any],
    *,
    max_fanout: int = 8,
    allowed_agent_refs: Iterable[str] = (),
) -> list[dict[str, Any]]:
    if not isinstance(doc, dict):
        raise PlanError("plan 必须是 JSON 对象", code="PLAN_SHAPE")
    subtasks = doc.get("subtasks")
    if not isinstance(subtasks, list) or not subtasks:
        raise PlanError("plan.subtasks 必须是非空数组", code="PLAN_SHAPE")
    if len(subtasks) > max_fanout:
        raise PlanError(f"plan 子任务 {len(subtasks)} 超过 max_fanout={max_fanout}", code="PLAN_FANOUT")
    allowed = set(allowed_agent_refs)
    seen: set[str] = set()
    for item in subtasks:
        if not isinstance(item, dict):
            raise PlanError("plan.subtasks 每项必须是对象", code="PLAN_SHAPE")
        sid = str(item.get("id", ""))
        if not sid:
            raise PlanError("plan 子任务缺少 id", code="PLAN_SHAPE")
        if sid in seen:
            raise PlanError(f"plan 子任务 id 重复: {sid}", code="PLAN_DUP_ID")
        seen.add(sid)
        ref = str(item.get("agent_ref", ""))
        if allowed and ref not in allowed:
            raise PlanError(f"plan 子任务 {sid} 的 agent_ref 越权: {ref}", code="PLAN_AGENT")
    return subtasks
