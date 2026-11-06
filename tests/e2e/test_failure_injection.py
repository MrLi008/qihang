from qihang.core.model.enums import EventKind, Status
from qihang.core.runtime.scheduler import run_to_completion
from tests.helpers import build


def test_failed_fanout_child_degrades_coverage_but_run_finishes() -> None:
    orchestrator, bus, clock, artifacts = build({"S2.3": "closed_missing"})
    orchestrator.start("A4")
    run_to_completion(orchestrator, clock)
    events = bus.drain(10_000)
    tree = orchestrator.tree

    failed = tree.require("/A4/E1/S2.3")
    assert failed.status is Status.FAILED
    assert "UNCLOSED_BLOCK" in (failed.error or "")

    assert tree.require("/A4/E1").status is Status.DONE
    j1 = tree.require("/A4/J1")
    report = artifacts.get(j1.outputs["aggregate"].artifact_id)
    assert '"coverage": "2/3"' in report
    assert "/A4/E1/S2.3" in report  # failure_list 显式披露

    root = tree.require("/A4")
    assert root.status is Status.DONE
    assert "/A4/E1/S2.3" in root.input_snapshot["patches"].text

    errors = [e for e in events if e.kind == EventKind.ERROR.value]
    assert len(errors) == 1
    assert errors[0].payload["code"] == "UNCLOSED_BLOCK"
    assert errors[0].task_path == "/A4/E1/S2.3"
