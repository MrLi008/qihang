"""定义层加载：YAML → AgentSpec（阶段一子集）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

try:  # 优先 ruamel，保持注释与顺序；缺失时退化为 PyYAML
    from ruamel.yaml import YAML as _RuamelYAML
except ImportError:  # pragma: no cover
    _RuamelYAML = None

try:
    import yaml as _PyYAML
except ImportError:  # pragma: no cover
    _PyYAML = None

from qihang.core.errors import SpecError
from qihang.core.model.enums import NodeKind
from qihang.core.model.spec import (
    AgentSpec,
    DecompositionSpec,
    ExecutionLimits,
    InputBinding,
    OutputDecl,
    SubtaskNode,
)
from qihang.core.runtime.spec_validation import ensure_spec_valid


def load_spec_data(path: Path) -> dict[str, Any]:
    """读取并返回 spec 原始映射（供 CLI/GUI 校验与导入复用）。"""
    return _read_yaml(Path(path))


def _read_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if _RuamelYAML is not None:
        yaml = _RuamelYAML(typ="safe")
        data = yaml.load(text)
    elif _PyYAML is not None:
        data = _PyYAML.safe_load(text)
    else:  # pragma: no cover
        raise SpecError("未安装 ruamel.yaml 或 PyYAML，无法加载 spec")
    if not isinstance(data, dict):
        raise SpecError(f"{path.name}: 顶层必须是映射", code="SPEC_SHAPE")
    return data


def _outputs(raw: Any, default_name: str = "artifact") -> tuple[OutputDecl, ...]:
    if not raw:
        return (OutputDecl(default_name),)
    result = []
    for item in raw:
        if isinstance(item, str):
            result.append(OutputDecl(item))
        else:
            result.append(OutputDecl(str(item["name"]), str(item.get("block_type", "ARTIFACT"))))
    return tuple(result)


def _bindings(raw: Any) -> tuple[InputBinding, ...]:
    if not raw:
        return ()
    result: list[InputBinding] = []
    for item in raw:
        name = str(item.get("name") or item.get("as") or item.get("to") or "")
        if not name:
            raise SpecError("inputs 项缺少 name/as", code="SPEC_INPUT_NAME")
        source = item.get("source", item.get("from"))
        literal = item.get("literal")
        result.append(InputBinding(name=name, source=str(source) if source is not None else None,
                                   literal=str(literal) if literal is not None else None))
    return tuple(result)


def _node(raw: Mapping[str, Any]) -> SubtaskNode:
    kind_raw = str(raw.get("node_kind", NodeKind.TASK.value))
    try:
        kind = NodeKind(kind_raw)
    except ValueError as exc:
        raise SpecError(f"未知 node_kind: {kind_raw}", code="SPEC_NODE_KIND") from exc
    return SubtaskNode(
        id=str(raw.get("id", "")),
        node_kind=kind,
        execution_mode=str(raw.get("execution_mode", "single_generate")),
        deps=tuple(str(x) for x in raw.get("deps", ()) or ()),
        fanout_by=str(raw["fanout_by"]) if raw.get("fanout_by") else None,
        max_instances=int(raw.get("max_instances", 20)),
        instance_id_pattern=str(raw.get("instance_id_pattern", "S{index}")),
        inputs_template=_bindings(raw.get("inputs_template")),
        outputs=_outputs(raw.get("outputs")),
        validator_key=str(raw["validator_key"]) if raw.get("validator_key") else None,
        level=int(raw.get("level", 1)),
        join_from=tuple(str(x) for x in raw.get("join_from", ()) or ()),
    )


def parse_spec(data: Mapping[str, Any], *, source: str = "<inline>") -> AgentSpec:
    ensure_spec_valid(data, source=source)

    agent_id = str(data.get("agent") or "")

    subtasks_block = data.get("subtasks") or {}
    mode = str(subtasks_block.get("mode", "static")) if isinstance(subtasks_block, dict) else "static"
    items = tuple(_node(x) for x in (subtasks_block.get("items") or [])) if isinstance(subtasks_block, dict) else ()
    expandables = tuple(_node(x) for x in (data.get("expandables") or ()))

    ids = [n.id for n in items] + [n.id for n in expandables]
    seen: dict[str, str] = {}
    for index, node in enumerate(items):
        if node.id in seen:
            raise SpecError(
                f"{source}: subtasks.items[{index}].id 重复（首次出现于 {seen[node.id]}）: {node.id}",
                code="SPEC_NODE_DUP",
            )
        seen[node.id] = f"subtasks.items[{index}]"
    for index, node in enumerate(expandables):
        if node.id in seen:
            raise SpecError(
                f"{source}: expandables[{index}].id 重复（首次出现于 {seen[node.id]}）: {node.id}",
                code="SPEC_NODE_DUP",
            )
        seen[node.id] = f"expandables[{index}]"

    known = set(ids)
    if data.get("dynamic_expand"):
        # 根层 DECOMPOSE 由编排器合成；静态节点可显式依赖它（A9 的 J1）。
        known.add("DECOMPOSE")
    for index, node in enumerate(items):
        for dep_index, dep in enumerate(node.deps):
            if dep not in known:
                raise SpecError(
                    f"{source}: subtasks.items[{index}].deps[{dep_index}] 依赖未知节点 {dep}",
                    code="SPEC_DEP",
                )
        if node.node_kind is NodeKind.EXPAND:
            if not node.fanout_by:
                raise SpecError(
                    f"{source}: subtasks.items[{index}].fanout_by 缺失（expand 节点必须声明 fanout_by）",
                    code="SPEC_FANOUT",
                )
            _check_pattern(node, f"subtasks.items[{index}]", source)

    for index, node in enumerate(expandables):
        if node.node_kind in (NodeKind.EXPAND, NodeKind.DYNAMIC_EXPAND):
            _check_pattern(node, f"expandables[{index}]", source)
        if node.node_kind is NodeKind.DYNAMIC_EXPAND:
            if node.level in (0, None):
                raise SpecError(
                    f"{source}: expandables[{index}].level 必须 >= 1", code="SPEC_LEVEL"
                )
            if node.level > 8:
                raise SpecError(
                    f"{source}: expandables[{index}].level 超出范围 1–8（当前 {node.level}）",
                    code="SPEC_LEVEL",
                )

    for index, node in enumerate(items):
        if node.join_from and node.node_kind is not NodeKind.JOIN:
            raise SpecError(
                f"{source}: subtasks.items[{index}].join_from 只允许用于 join 节点",
                code="SPEC_JOIN_SOURCE",
            )

    dynamic_nodes = [n for n in expandables if n.node_kind is NodeKind.DYNAMIC_EXPAND]
    if dynamic_nodes:
        levels = [n.level for n in dynamic_nodes]
        if 1 not in levels:
            raise SpecError(
                f"{source}: 动态展开点必须声明 level=1（根层），当前 {levels}",
                code="SPEC_LEVEL",
            )
        if len(set(levels)) != len(levels):
            raise SpecError(f"{source}: 动态展开点 level 重复：{levels}", code="SPEC_LEVEL")

    dec_raw = data.get("decomposition")
    decomposition = None
    if isinstance(dec_raw, Mapping):
        decomposition = DecompositionSpec(
            output_schema=str(dec_raw.get("output_schema", "subtask_plan_v1")),
            allowed_agent_refs=tuple(str(x) for x in (dec_raw.get("allowed_agent_refs") or ())),
            max_depth=int(dec_raw.get("max_depth", 2)),
            max_fanout=int(dec_raw.get("max_fanout", 8)),
            require_acceptance_ref=bool(dec_raw.get("require_acceptance_ref", False)),
        )

    dynamic_expand = bool(data.get("dynamic_expand", False))
    if dynamic_expand and decomposition is None:
        raise SpecError(f"{source}: dynamic_expand=true 需要 decomposition 声明", code="SPEC_DYNAMIC")
    if dynamic_expand and not expandables:
        raise SpecError(f"{source}: dynamic_expand=true 需要至少一个 expandables 节点", code="SPEC_DYNAMIC")

    exec_raw = data.get("execution")
    execution = ExecutionLimits()
    if isinstance(exec_raw, Mapping):
        execution = ExecutionLimits(
            timeout_s=float(exec_raw["timeout_s"]) if exec_raw.get("timeout_s") is not None else None,
            max_attempts=int(exec_raw["max_attempts"]) if exec_raw.get("max_attempts") is not None else None,
            budget_tokens=int(exec_raw["budget_tokens"]) if exec_raw.get("budget_tokens") is not None else None,
        )

    return AgentSpec(
        agent_id=agent_id,
        schema_version=int(data.get("schema_version", 5)),
        display_name=str(data.get("display_name", "")),
        role_definition=str(data.get("role_definition", "")),
        acceptance_criteria=tuple(str(x) for x in (data.get("acceptance_criteria") or ())),
        generation_template=str(data.get("generation_template", "")),
        inputs=_bindings((data.get("message_contract") or {}).get("inputs")),
        outputs=_outputs((data.get("message_contract") or {}).get("outputs")),
        subtasks_mode=mode,
        subtasks=items,
        decomposition=decomposition,
        dynamic_expand=dynamic_expand,
        expandables=expandables,
        failure_policy=str(subtasks_block.get("failure_policy", "best_effort"))
        if isinstance(subtasks_block, Mapping)
        else "best_effort",
        execution=execution,
        parameters=dict(data.get("parameters") or {}),
    )


def _check_pattern(node: SubtaskNode, path: str, source: str) -> None:
    pattern = node.instance_id_pattern
    if "{index}" not in pattern and "{key}" not in pattern:
        raise SpecError(
            f"{source}: {path}.instance_id_pattern 必须包含 {{index}} 或 {{key}}，当前为 {pattern!r}",
            code="SPEC_FANOUT",
        )


class SpecLoader:
    def __init__(self, spec_dir: Path) -> None:
        self._dir = Path(spec_dir)

    def load(self, agent_id: str) -> AgentSpec:
        path = self._dir / f"{agent_id.lower()}.yaml"
        if not path.exists():
            raise SpecError(f"spec 不存在: {path}", code="SPEC_NOT_FOUND")
        return parse_spec(_read_yaml(path), source=path.name)

    def load_all(self) -> dict[str, AgentSpec]:
        specs: dict[str, AgentSpec] = {}
        for path in sorted(self._dir.glob("*.yaml")):
            spec = parse_spec(_read_yaml(path), source=path.name)
            specs[spec.agent_id] = spec
        return specs
