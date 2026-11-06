import json

from qihang.core.model.enums import Status
from qihang.core.runtime.scheduler import run_to_completion

from tests.helpers import build


def _run(fail_inject=None):
    orchestrator, bus, clock, artifacts = build(fail_inject, delay_s=0.01)
    orchestrator.start("A9")
    run_to_completion(orchestrator, clock)
    return orchestrator, bus.drain(20_000), artifacts


def _level_paths(orchestrator, level: int) -> list[str]:
    return sorted(
        i.task_path for i in orchestrator.tree.all_instances() if i.node_kind.value == "task" and i.level == level
    )


def _aggregate(orchestrator, artifacts, path: str) -> dict:
    inst = orchestrator.tree.require(path)
    return json.loads(artifacts.get(inst.outputs["aggregate"].artifact_id))


def test_a9_runs_three_dynamic_levels_and_root_aggregates_all_of_them() -> None:
    orchestrator, _, artifacts = _run()
    summary = orchestrator.summary()

    assert summary.status is Status.DONE
    assert summary.total_instances == 30
    assert summary.done == 30 and summary.failed == 0 and summary.blocked == 0

    level1 = _level_paths(orchestrator, 1)
    level2 = _level_paths(orchestrator, 2)
    level3 = _level_paths(orchestrator, 3)
    assert level1 == ["/A9/E1/T1", "/A9/E1/T2"]
    assert len(level2) == 4 and len(level3) == 8
    assert "/A9/E1/T1/E2/T1.1" in level2
    assert "/A9/E1/T1/E2/T1.1/E3/T1.1.1" in level3
    # 父子关系逐层成立
    for path in level3:
        assert orchestrator.tree.require(path).parent_path.count("/E3") == 1
    assert orchestrator.tree.require("/A9/E1/T1/E2/T1.1/E3/T1.1.1").parent_path == "/A9/E1/T1/E2/T1.1/E3"

    # 每层聚合 coverage 都是本层实例数
    assert _aggregate(orchestrator, artifacts, "/A9/E1")["coverage"] == "2/2"
    assert _aggregate(orchestrator, artifacts, "/A9/E1/T1/E2")["coverage"] == "2/2"
    assert _aggregate(orchestrator, artifacts, "/A9/E1/T1/E2/T1.1/E3")["coverage"] == "2/2"

    root = orchestrator.tree.require("/A9")
    level1_text = json.loads(root.input_snapshot["level1"].text)
    all_levels = json.loads(root.input_snapshot["all_levels"].text)
    all_patches = json.loads(root.input_snapshot["all_patches"].text)
    joined = json.loads(root.input_snapshot["joined"].text)

    assert level1_text["coverage"] == "2/2"
    assert joined["coverage"] == "2/2"
    assert len(joined["items"]) == 2
    assert len(all_levels) == 7  # E1(1) + E2(2) + E3(4)
    assert json.loads(all_levels["/A9/E1/T1/E2/T1.1/E3"])["coverage"] == "2/2"
    assert len(all_patches) == 14  # 2 + 4 + 8
    assert "/A9/E1/T1/E2/T1.1/E3/T1.1.1" in all_patches

    # 根产物真的带出三层文本，而不是只“跑通”
    artifact = artifacts.get(root.outputs["artifact"].artifact_id)
    assert '"/A9/E1/T1/E2/T1.1/E3/T1.1.1"' in artifact
    assert '"coverage": "2/2"' in artifact
    assert '"total": 2' in artifact


def test_a9_deep_failure_reduces_layer_coverage_but_root_still_closes() -> None:
    orchestrator, _, artifacts = _run({"T1.1.2": "closed_missing"})
    summary = orchestrator.summary()

    assert summary.status is Status.DONE
    assert (summary.total_instances, summary.done, summary.failed, summary.blocked) == (30, 29, 1, 0)

    failed_path = "/A9/E1/T1/E2/T1.1/E3/T1.1.2"
    assert orchestrator.tree.require(failed_path).status is Status.FAILED

    leaf_layer = _aggregate(orchestrator, artifacts, "/A9/E1/T1/E2/T1.1/E3")
    assert leaf_layer["coverage"] == "1/2"
    assert leaf_layer["failed"] == 1
    assert failed_path in leaf_layer["failures"]

    # 上层任务本身仍完成；失败通过所在层聚合向上带出，而不是整棵树崩掉
    assert _aggregate(orchestrator, artifacts, "/A9/E1/T1/E2")["coverage"] == "2/2"
    assert _aggregate(orchestrator, artifacts, "/A9/E1")["coverage"] == "2/2"

    root = orchestrator.tree.require("/A9")
    all_levels = json.loads(root.input_snapshot["all_levels"].text)
    leaf_text = json.loads(all_levels["/A9/E1/T1/E2/T1.1/E3"])
    assert leaf_text["coverage"] == "1/2"
    assert failed_path in leaf_text["failures"]
    assert len(json.loads(root.input_snapshot["all_patches"].text)) == 13

    artifact = artifacts.get(root.outputs["artifact"].artifact_id)
    assert failed_path in artifact
    assert "1/2" in artifact
