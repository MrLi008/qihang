"""定义层数据模型（阶段一子集）。

与 03 §4.1 对应，但只保留阶段一跑得动的最小字段：
- 不做 9 项静态校验（阶段二 S2-03）
- 不做预算与失败策略三态（阶段二 S2-12/S2-11）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qihang.core.model.enums import NodeKind


@dataclass(frozen=True, slots=True)
class OutputDecl:
    name: str
    block_type: str = "ARTIFACT"


@dataclass(frozen=True, slots=True)
class InputBinding:
    """message_contract.inputs 的一项。

    name: 模板里使用的变量名（不写 {{}}）
    source: 源 DSL 表达式（如 self.children.S1.outputs.file_list）
    literal: 直接量（与 source 互斥）
    """

    name: str
    source: str | None = None
    literal: str | None = None


@dataclass(frozen=True, slots=True)
class SubtaskNode:
    id: str
    node_kind: NodeKind = NodeKind.TASK
    execution_mode: str = "single_generate"
    deps: tuple[str, ...] = ()
    fanout_by: str | None = None
    max_instances: int = 20
    instance_id_pattern: str = "S{index}"
    inputs_template: tuple[InputBinding, ...] = ()
    outputs: tuple[OutputDecl, ...] = ()
    validator_key: str | None = None
    level: int = 1
    join_from: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    """执行参数占位：阶段一只解析并保留，不强制超时/重试/预算。"""

    timeout_s: float | None = None
    max_attempts: int | None = None
    budget_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class DecompositionSpec:
    output_schema: str = "subtask_plan_v1"
    allowed_agent_refs: tuple[str, ...] = ()
    max_depth: int = 2
    max_fanout: int = 8
    require_acceptance_ref: bool = False


@dataclass(frozen=True, slots=True)
class AgentSpec:
    agent_id: str
    schema_version: int = 5
    display_name: str = ""
    role_definition: str = ""
    acceptance_criteria: tuple[str, ...] = ()
    generation_template: str = ""
    inputs: tuple[InputBinding, ...] = ()
    outputs: tuple[OutputDecl, ...] = field(default_factory=lambda: (OutputDecl("artifact"),))
    subtasks_mode: str = "static"
    subtasks: tuple[SubtaskNode, ...] = ()
    decomposition: DecompositionSpec | None = None
    dynamic_expand: bool = False
    expandables: tuple[SubtaskNode, ...] = ()
    failure_policy: str = "best_effort"
    execution: ExecutionLimits = field(default_factory=ExecutionLimits)
    parameters: dict[str, Any] = field(default_factory=dict)

    def subtask_by_id(self, sid: str) -> SubtaskNode | None:
        for item in (*self.subtasks, *self.expandables):
            if item.id == sid:
                return item
        return None
