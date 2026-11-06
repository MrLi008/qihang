"""元数据规范测试：a3–a7 通过、典型错误定位准确、轻量/严格两条路径一致。"""

from __future__ import annotations

import pytest

from qihang.core.errors import SpecError
from qihang.core.runtime.spec_loader import load_spec_data, parse_spec
from qihang.core.runtime.spec_validation import (
    SCHEMA_PATH,
    ensure_spec_valid,
    jsonschema_available,
    validate_spec_data,
)
from qihang.paths import SPECS_DIR

ENGINES = ["light"] + (["strict"] if jsonschema_available() else [])


def _base_agent() -> dict:
    return {
        "agent": "X",
        "schema_version": 5,
        "subtasks": {"mode": "static", "items": []},
    }


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("name", ["a3", "a4", "a5", "a6", "a7", "a9"])
def test_builtin_specs_pass_both_engines(name: str, engine: str) -> None:
    data = load_spec_data(SPECS_DIR / f"{name}.yaml")
    assert validate_spec_data(data, engine=engine) == []
    spec = parse_spec(data, source=f"{name}.yaml")
    assert spec.agent_id == name.upper()


@pytest.mark.parametrize("engine", ENGINES)
def test_unknown_field_reports_path(engine: str) -> None:
    data = _base_agent()
    data["foo"] = 1
    with pytest.raises(SpecError) as exc:
        ensure_spec_valid(data, source="bad.yaml", engine=engine)
    message = exc.value.message
    assert "foo" in message and "未知字段" in message

    data = _base_agent()
    data["subtasks"]["items"] = [{"id": "S1", "bogus": 1}]
    with pytest.raises(SpecError) as exc:
        ensure_spec_valid(data, source="bad.yaml", engine=engine)
    assert "subtasks.items[0].bogus" in exc.value.message


@pytest.mark.parametrize("engine", ENGINES)
def test_type_error_reports_path(engine: str) -> None:
    data = _base_agent()
    data["subtasks"]["items"] = [{"id": "S1", "max_instances": "20"}]
    with pytest.raises(SpecError) as exc:
        ensure_spec_valid(data, source="bad.yaml", engine=engine)
    message = exc.value.message
    assert "subtasks.items[0].max_instances" in message
    assert "类型错误" in message and "整数" in message


@pytest.mark.parametrize("engine", ENGINES)
def test_missing_required_reports_path(engine: str) -> None:
    data = {"schema_version": 5}
    with pytest.raises(SpecError) as exc:
        ensure_spec_valid(data, source="bad.yaml", engine=engine)
    assert "agent" in exc.value.message and "缺少必填字段" in exc.value.message


@pytest.mark.parametrize("engine", ENGINES)
def test_unsupported_schema_version(engine: str) -> None:
    data = _base_agent()
    data["schema_version"] = 7
    with pytest.raises(SpecError) as exc:
        ensure_spec_valid(data, source="bad.yaml", engine=engine)
    assert "schema_version" in exc.value.message


@pytest.mark.parametrize("engine", ENGINES)
def test_schema_version_6_is_current(engine: str) -> None:
    data = _base_agent()
    data["schema_version"] = 6
    ensure_spec_valid(data, source="v6.yaml", engine=engine)
    assert parse_spec(data, source="v6.yaml").schema_version == 6


def test_expand_without_fanout_reports_path() -> None:
    data = _base_agent()
    data["subtasks"]["items"] = [{"id": "E1", "node_kind": "expand"}]
    with pytest.raises(SpecError) as exc:
        parse_spec(data, source="bad.yaml")
    assert "subtasks.items[0].fanout_by" in exc.value.message


def test_illegal_instance_pattern_reports_path() -> None:
    data = _base_agent()
    data["subtasks"]["items"] = [
        {"id": "E1", "node_kind": "expand", "fanout_by": "children.by_id.S1.outputs.file_list",
         "instance_id_pattern": "S2.fixed"}
    ]
    with pytest.raises(SpecError) as exc:
        parse_spec(data, source="bad.yaml")
    assert "instance_id_pattern" in exc.value.message and "{index}" in exc.value.message


def test_dynamic_expand_without_declaration_reports_path() -> None:
    data = _base_agent()
    data["dynamic_expand"] = True
    with pytest.raises(SpecError) as exc:
        parse_spec(data, source="bad.yaml")
    assert "decomposition" in exc.value.message


def test_schema_resource_is_present() -> None:
    assert SCHEMA_PATH.exists()


def test_missing_version_defaults_to_5() -> None:
    spec = parse_spec({"agent": "V5", "subtasks": {"mode": "static", "items": []}}, source="v5.yaml")
    assert spec.schema_version == 5


@pytest.mark.parametrize("engine", ENGINES)
def test_v4_aliases_still_load(engine: str) -> None:
    data = {
        "agent": "V4",
        "schema_version": 4,
        "message_contract": {"inputs": [{"as": "x", "from": "project.key"}]},
        "subtasks": {"mode": "static", "items": []},
    }
    ensure_spec_valid(data, source="v4.yaml", engine=engine)
    spec = parse_spec(data, source="v4.yaml")
    assert spec.inputs[0].name == "x"
    assert spec.inputs[0].source == "project.key"


def test_a9_declares_levels_and_explicit_join_source() -> None:
    spec = parse_spec(load_spec_data(SPECS_DIR / "a9.yaml"), source="a9.yaml")
    assert [n.level for n in spec.expandables] == [1, 2, 3]
    join = spec.subtask_by_id("J1")
    assert join is not None and join.join_from == ("E1",)


def test_dynamic_expand_level_must_be_positive_and_unique() -> None:
    data = _base_agent()
    data["dynamic_expand"] = True
    data["decomposition"] = {"output_schema": "subtask_plan_v1", "allowed_agent_refs": ["X"]}
    data["expandables"] = [
        {"id": "E1", "node_kind": "dynamic_expand", "level": 0, "max_instances": 2},
    ]
    with pytest.raises(SpecError) as exc:
        parse_spec(data, source="bad.yaml")
    assert "expandables[0].level" in exc.value.message

    data["expandables"] = [
        {"id": "E1", "node_kind": "dynamic_expand", "level": 1, "max_instances": 2},
        {"id": "E2", "node_kind": "dynamic_expand", "level": 1, "max_instances": 2},
    ]
    with pytest.raises(SpecError) as exc:
        parse_spec(data, source="bad.yaml")
    assert "level 重复" in exc.value.message
