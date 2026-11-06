"""JOIN 聚合：coverage + failure_list + 汇总产物。

阶段一不实现 `failure_disclosed` 程序校验（阶段二 S2-15），
但会把失败项显式写进聚合产物，父任务渲染时自然带上。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from qihang.core.model.enums import Status
from qihang.core.model.runtime import TaskInstance


@dataclass(frozen=True, slots=True)
class JoinItem:
    task_path: str
    status: str
    output: str
    artifact_ref: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class JoinReport:
    total: int
    done: int
    failed: int
    coverage: str
    failures: tuple[str, ...] = ()
    items: tuple[JoinItem, ...] = field(default_factory=tuple)

    def to_text(self) -> str:
        return json.dumps(
            {
                "coverage": self.coverage,
                "total": self.total,
                "done": self.done,
                "failed": self.failed,
                "failures": list(self.failures),
                "items": [asdict(i) for i in self.items],
            },
            ensure_ascii=False,
            indent=2,
        )


def evaluate(children: list[TaskInstance], output: str = "patch") -> JoinReport:
    items: list[JoinItem] = []
    failures: list[str] = []
    done = 0
    for child in children:
        art = child.outputs.get(output)
        items.append(
            JoinItem(
                task_path=child.task_path,
                status=child.status.value,
                output=output,
                artifact_ref=art.artifact_id if art else "",
                content_hash=art.content_hash if art else "",
            )
        )
        if child.status is Status.DONE and art is not None:
            done += 1
        else:
            failures.append(child.task_path)
    total = len(children)
    return JoinReport(
        total=total,
        done=done,
        failed=total - done,
        coverage=f"{done}/{total}",
        failures=tuple(failures),
        items=tuple(items),
    )
