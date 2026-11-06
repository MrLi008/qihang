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
    InputBinding,
    OutputDecl,
    SubtaskNode,
)


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
    )


def parse_spec(data: Mapping[str, Any], *, source: str = "<inline>") -> AgentSpec:
    agent_id = str(data.get("agent") or "")
    if not agent_id:
        raise SpecError(f"{source}: 缺少 agent 字段", code="SPEC_AGENT")

    subtasks_block = data.get("subtasks") or {}
    mode = str(subtasks_block.get("mode", "static")) if isinstance(subtasks_block, dict) else "static"
    items = tuple(_node(x) for x in (subtasks_block.get("items") or [])) if isinstance(subtasks_block, dict) else ()
    expandables = tuple(_node(x) for x in (data.get("expandables") or ()))

    ids = [n.id for n in items] + [n.id for n in expandables]
    if any(not i for i in ids):
        raise SpecError(f"{source}: 子任务缺少 id", code="SPEC_NODE_ID")
    if len(set(ids)) != len(ids):
        raise SpecError(f"{source}: 子任务 id 重复: {ids}", code="SPEC_NODE_DUP")
    known = set(ids)
    for node in items:
        for dep in node.deps:
            if dep not in known:
                raise SpecError(f"{source}: 子任务 {node.id} 依赖未知节点 {dep}", code="SPEC_DEP")
        if node.node_kind is NodeKind.EXPAND and not node.fanout_by:
            raise SpecError(f"{source}: expand 节点 {node.id} 缺少 fanout_by", code="SPEC_FANOUT")

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
    if dynamic_expand and (decomposition is None or not expandables):
        raise SpecError(f"{source}: dynamic_expand 需要 decomposition 与 expandables", code="SPEC_DYNAMIC")

    return AgentSpec(
        agent_id=agent_id,
        schema_version=int(data.get("schema_version", 5)),
        display_name=str(data.get("display_name", "")),
        role_definition=str(data.get("role_definition", "")),
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
