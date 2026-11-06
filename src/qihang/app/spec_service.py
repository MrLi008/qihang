"""Spec 目录服务：给 UI / CLI 复用「列出、校验、新建、导入、落盘」。

UI 只依赖本模块，不直接 import `qihang.core.runtime`（遵守分层守卫）。
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Mapping

from qihang.core.errors import SpecError
from qihang.core.model.spec import AgentSpec
from qihang.core.runtime.spec_loader import load_spec_data, parse_spec


def list_agents(specs_dir: Path | str) -> tuple[list[str], list[str]]:
    """返回 (可用 agent 标识列表, 不可用 spec 的中文错误列表)。"""
    agents: set[str] = set()
    errors: list[str] = []
    for path in sorted(Path(specs_dir).glob("*.yaml")):
        try:
            spec = parse_spec(load_spec_data(path), source=path.name)
        except SpecError as exc:
            errors.append(f"{path.name}：{exc.message}")
        except OSError as exc:
            errors.append(f"{path.name}：读取失败（{exc}）")
        else:
            agents.add(spec.agent_id)
    return sorted(agents), errors


def load_agent_spec(path: Path | str) -> AgentSpec:
    path = Path(path)
    return parse_spec(load_spec_data(path), source=path.name)


def validate_agent_spec(data: Mapping[str, Any], *, source: str = "<新建>") -> AgentSpec:
    """只校验不落盘；失败抛 SpecError（中文、含字段路径）。"""
    return parse_spec(data, source=source)


def save_agent_spec(
    specs_dir: Path | str,
    data: Mapping[str, Any],
    *,
    overwrite: bool = False,
    source: str = "<新建>",
) -> Path:
    """先校验再落盘；校验失败抛 SpecError（中文、含字段路径），不会写出坏文件。"""
    spec = parse_spec(data, source=source)
    target = Path(specs_dir) / f"{spec.agent_id.lower()}.yaml"
    if target.exists() and not overwrite:
        raise SpecError(f"同名 spec 已存在：{target.name}（勾选覆盖或换一个 agent 标识）", code="SPEC_EXISTS")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_dump_yaml(data), encoding="utf-8")
    except OSError as exc:
        raise SpecError(f"写入 {target.name} 失败：{exc}", code="SPEC_IO") from exc
    return target


def import_agent_spec(source: Path | str, specs_dir: Path | str, *, overwrite: bool = False) -> Path:
    source = Path(source)
    try:
        data = load_spec_data(source)
    except SpecError:
        raise
    except OSError as exc:
        raise SpecError(f"读取 {source.name} 失败：{exc}", code="SPEC_IO") from exc
    except Exception as exc:  # YAML 语法错误
        raise SpecError(f"解析 {source.name} 失败：{exc}", code="SPEC_YAML") from exc
    return save_agent_spec(specs_dir, data, overwrite=overwrite, source=source.name)


def build_new_agent_spec(
    *,
    agent_id: str,
    display_name: str = "",
    role_definition: str = "",
    subtask_mode: str = "static",
    expand_mode: str = "none",
    nodes: int = 500,
    dynamic_expand: bool = False,
) -> dict[str, Any]:
    """按界面关键字段生成一份合法 spec（返回可校验的映射）。"""
    nodes = max(1, int(nodes))
    agent_id = agent_id.strip()
    role = role_definition.strip() or f"你是 {agent_id} Agent。"
    data: dict[str, Any] = {
        "agent": agent_id,
        "schema_version": 5,
        "display_name": display_name.strip() or agent_id,
        "role_definition": role,
        "generation_template": "## 执行\n{{context}}\nDELIVERY_STATUS: COMPLETE\n",
        "message_contract": {
            "inputs": [{"name": "context", "literal": "（待填写）"}],
            "outputs": [{"name": "artifact", "block_type": "ARTIFACT"}],
        },
        "subtasks": {"mode": "static", "failure_policy": "best_effort", "items": []},
        "execution": {"timeout_s": 60, "max_attempts": 1, "budget_tokens": None},
    }

    if subtask_mode == "dynamic" or dynamic_expand:
        data["subtasks"] = {"mode": "dynamic", "failure_policy": "best_effort", "items": []}
        data["dynamic_expand"] = True
        data["decomposition"] = {
            "output_schema": "subtask_plan_v1",
            "allowed_agent_refs": [f"{agent_id}.refactor"],
            "max_depth": 2,
            "max_fanout": 8,
            "require_acceptance_ref": False,
        }
        data["expandables"] = [
            {
                "id": "E2",
                "node_kind": "dynamic_expand",
                "max_instances": 8,
                "instance_id_pattern": "T{index}",
                "inputs_template": [
                    {"name": "target", "source": "plan.item.target"},
                    {"name": "rule", "source": "plan.item.rule"},
                ],
                "outputs": [{"name": "patch", "block_type": "DATA"}],
            }
        ]
        data["message_contract"] = {
            "inputs": [{"name": "refactor_report", "source": "children.by_id.E2.outputs.aggregate"}],
            "outputs": [{"name": "artifact", "block_type": "ARTIFACT"}],
        }
        data["generation_template"] = "## 汇总\n{{refactor_report}}\nDELIVERY_STATUS: COMPLETE\n"
        return data

    if expand_mode == "fanout":
        data["parameters"] = {"list_size": nodes}
        data["message_contract"] = {
            "inputs": [
                {"name": "file_list", "source": "children.by_id.S1.outputs.file_list"},
                {"name": "aggregate", "source": "children.by_id.J1.outputs.aggregate"},
            ],
            "outputs": [{"name": "artifact", "block_type": "ARTIFACT"}],
        }
        data["generation_template"] = "## 汇总\n{{file_list}}\n{{aggregate}}\nDELIVERY_STATUS: COMPLETE\n"
        data["subtasks"] = {
            "mode": "static",
            "failure_policy": "best_effort",
            "items": [
                {"id": "S1", "outputs": [{"name": "file_list", "block_type": "DATA"}]},
                {
                    "id": "E1",
                    "node_kind": "expand",
                    "deps": ["S1"],
                    "fanout_by": "children.by_id.S1.outputs.file_list",
                    "max_instances": nodes,
                    "instance_id_pattern": "S2.{index}",
                    "inputs_template": [{"name": "target_file", "source": "fanout.item"}],
                    "outputs": [{"name": "patch", "block_type": "DATA"}],
                },
                {
                    "id": "J1",
                    "node_kind": "join",
                    "deps": ["E1"],
                    "outputs": [{"name": "aggregate", "block_type": "DATA"}],
                },
                {"id": "S3", "deps": ["J1"], "outputs": [{"name": "artifact", "block_type": "ARTIFACT"}]},
            ],
        }
    return data


def _dump_yaml(data: Mapping[str, Any]) -> str:
    try:
        from ruamel.yaml import YAML

        yaml = YAML()
        yaml.default_flow_style = False
        yaml.allow_unicode = True
        buffer = io.StringIO()
        yaml.dump(dict(data), buffer)
        return buffer.getvalue()
    except ImportError:  # pragma: no cover - 无 ruamel 时退化为 PyYAML
        import yaml as pyyaml

        return pyyaml.safe_dump(dict(data), allow_unicode=True, sort_keys=False)
