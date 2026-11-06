import pytest

from qihang.core.errors import PlanError
from qihang.core.model.enums import NodeKind
from qihang.core.model.spec import SubtaskNode
from qihang.core.runtime.planner import parse_plan_doc, plan_static, values_from_text


def test_values_from_json_or_lines() -> None:
    assert values_from_text('["a.py", "b.py"]') == ["a.py", "b.py"]
    assert values_from_text("a.py\nb.py\n") == ["a.py", "b.py"]
    assert values_from_text("") == []


def test_plan_static_uses_pattern() -> None:
    node = SubtaskNode(id="E1", node_kind=NodeKind.EXPAND, instance_id_pattern="S2.{index}")
    plan = plan_static("/A4/E1", node, ["a.py", "b.py"])
    assert plan.instance_paths == ("/A4/E1/S2.1", "/A4/E1/S2.2")
    assert plan.items[0].index == 1


def test_max_instances_guard() -> None:
    node = SubtaskNode(id="E1", node_kind=NodeKind.EXPAND, max_instances=2)
    with pytest.raises(PlanError):
        plan_static("/A4/E1", node, ["a.py", "b.py", "c.py"])


def test_plan_doc_whitelist_and_dup() -> None:
    doc = {"plan_id": "P1", "subtasks": [{"id": "T1", "agent_ref": "A6.refactor"}]}
    assert parse_plan_doc(doc, allowed_agent_refs=["A6.refactor"]) == doc["subtasks"]
    with pytest.raises(PlanError):
        parse_plan_doc({"subtasks": [{"id": "T9", "agent_ref": "A9.other"}]}, allowed_agent_refs=["A6.refactor"])
    with pytest.raises(PlanError):
        parse_plan_doc(
            {"subtasks": [{"id": "T1", "agent_ref": "A6.refactor"}, {"id": "T1", "agent_ref": "A6.refactor"}]}
        )
