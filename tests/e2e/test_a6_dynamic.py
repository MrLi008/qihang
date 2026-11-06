from qihang.core.model.enums import EventKind, Status
from qihang.core.runtime.scheduler import run_to_completion
from tests.helpers import build


def test_a6_dynamic_decompose_and_expand() -> None:
    orchestrator, bus, clock, artifacts = build()
    orchestrator.start("A6")
    run_to_completion(orchestrator, clock)
    events = bus.drain(10_000)

    tree = orchestrator.tree
    assert tree.require("/A6").status is Status.DONE
    assert tree.require("/A6/DECOMPOSE").status is Status.DONE
    assert tree.require("/A6/E2").status is Status.DONE
    for sid in ("T1", "T2", "T3"):
        assert tree.require(f"/A6/E2/{sid}").status is Status.DONE

    decompose = tree.require("/A6/DECOMPOSE")
    assert decompose.plan_doc is not None
    assert len(decompose.plan_doc["subtasks"]) == 3

    e2 = tree.require("/A6/E2")
    aggregate = artifacts.get(e2.outputs["aggregate"].artifact_id)
    assert '"coverage": "3/3"' in aggregate

    root = tree.require("/A6")
    assert "refactor_report" in root.input_snapshot
    assert '"coverage": "3/3"' in root.input_snapshot["refactor_report"].text

    kinds = [e.kind for e in events]
    assert kinds.count(EventKind.EXPAND_PLANNED.value) == 1
    planned = next(e for e in events if e.kind == EventKind.EXPAND_PLANNED.value)
    assert planned.payload["stage"] == "dynamic"
    assert planned.payload["slots"] == ["T1", "T2", "T3"]
    assert planned.payload["plan_id"] == "A6/DECOMPOSE-P1"


def test_dynamic_decompose_plan_is_whitelisted() -> None:
    """Mock plan 必须落在 allowed_agent_refs 内，否则 DECOMPOSE 会失败。"""
    orchestrator, _, clock, _ = build()
    orchestrator.start("A6")
    run_to_completion(orchestrator, clock)
    decompose = orchestrator.tree.require("/A6/DECOMPOSE")
    assert decompose.error is None
    assert {x["agent_ref"] for x in decompose.plan_doc["subtasks"]} == {"A6.refactor"}
