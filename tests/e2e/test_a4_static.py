import time

from qihang.core.model.enums import EventKind, Status
from qihang.core.runtime.scheduler import run_to_completion
from tests.helpers import build


def _run(agent: str, **kwargs):
    orchestrator, bus, clock, artifacts = build(**kwargs)
    orchestrator.start(agent)
    ticks = run_to_completion(orchestrator, clock)
    return orchestrator, bus.drain(10_000), clock, artifacts, ticks


def test_a4_static_fanout_join_and_data_passing() -> None:
    started = time.perf_counter()
    orchestrator, events, clock, artifacts, ticks = _run("A4")
    elapsed = time.perf_counter() - started

    tree = orchestrator.tree
    root = tree.require("/A4")
    assert root.status is Status.DONE
    assert elapsed < 2.0, "测试不得真的等 1 秒 × N（走假时钟）"
    assert clock.now() >= 6.0, "假时钟应当累加 6 个 1 秒任务"

    paths = [i.task_path for i in tree.all_instances()]
    assert "/A4/E1/S2.1" in paths and "/A4/E1/S2.2" in paths and "/A4/E1/S2.3" in paths
    assert tree.require("/A4/E1/S2.3").status is Status.DONE
    assert tree.require("/A4/S3").status is Status.DONE

    e1 = tree.require("/A4/E1")
    assert e1.outputs["aggregate"].content_hash
    e1_text = artifacts.get(e1.outputs["aggregate"].artifact_id)
    assert '"coverage": "3/3"' in e1_text

    j1 = tree.require("/A4/J1")
    j1_text = artifacts.get(j1.outputs["aggregate"].artifact_id)
    assert '"coverage": "3/3"' in j1_text
    assert "/A4/E1/S2.1" in j1_text

    # 层间传数：根任务在渲染时真的取到了 S1 的清单与 J1 的聚合
    assert set(root.input_snapshot) == {"file_list", "patches"}
    assert "auth.py" in root.input_snapshot["file_list"].text
    assert '"coverage": "3/3"' in root.input_snapshot["patches"].text

    kinds = [e.kind for e in events]
    assert EventKind.EXPAND_PLANNED.value in kinds
    assert kinds.count(EventKind.EXPAND_PLANNED.value) == 1
    assert kinds.count(EventKind.JOIN_DONE.value) == 2  # E1 收口 + J1
    assert kinds.count(EventKind.LLM_REQUEST.value) == 6  # S1 + 3×S2 + S3 + A4
    assert kinds[-1] == EventKind.RUN_FINISHED.value

    seqs = [e.seq for e in events]
    assert seqs == list(range(1, len(seqs) + 1)), "事件 seq 必须单调连续"
    assert ticks > 0
