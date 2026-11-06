"""扩展性测试：只写配置、不改代码即可新增 agent 并跑完。"""

from __future__ import annotations

from pathlib import Path

from qihang.core.executor.mock import MockExecutor
from qihang.core.model.events import EventBus
from qihang.core.runtime.fakes import ImmediateRunner, VirtualClock
from qihang.core.runtime.orchestrator import Orchestrator
from qihang.core.runtime.scheduler import run_to_completion
from qihang.core.runtime.spec_loader import SpecLoader
from qihang.core.store.blobstore import BlobStore
from qihang.paths import SPECS_DIR


def test_new_agent_from_config_only(tmp_path: Path) -> None:
    text = (SPECS_DIR / "a4.yaml").read_text(encoding="utf-8")
    text = text.replace("agent: A4", "agent: X1", 1)
    (tmp_path / "x1.yaml").write_text(text, encoding="utf-8")

    specs = SpecLoader(tmp_path).load_all()
    assert set(specs) == {"X1"}

    clock = VirtualClock()
    orchestrator = Orchestrator(
        specs,
        MockExecutor(clock, base_delay_s=1.0, jitter_s=0.0),
        clock,
        ImmediateRunner(),
        BlobStore(),
        EventBus("R-EXT"),
        run_id="R-EXT",
    )
    orchestrator.start("X1")
    run_to_completion(orchestrator, clock)

    instances = list(orchestrator.tree.all_instances())
    assert len(instances) == 8
    assert all(item.status.value == "DONE" for item in instances)
