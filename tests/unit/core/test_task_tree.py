import pytest

from qihang.core.model.enums import NodeKind, Status
from qihang.core.runtime.task_tree import StatusTransitionError, TaskTree


def test_create_and_children() -> None:
    tree = TaskTree()
    tree.create("/A4", parent_path="/", spec_ref="A4", node_kind=NodeKind.TASK)
    tree.create("/A4/S1", parent_path="/A4", spec_ref="A4", node_kind=NodeKind.TASK)
    tree.create("/A4/E1", parent_path="/A4", spec_ref="A4", node_kind=NodeKind.EXPAND)
    assert [i.task_path for i in tree.children("/A4")] == ["/A4/S1", "/A4/E1"]
    assert tree.require("/A4").status is Status.PENDING


def test_duplicate_path_rejected() -> None:
    tree = TaskTree()
    tree.create("/A4", parent_path="/", spec_ref="A4", node_kind=NodeKind.TASK)
    with pytest.raises(ValueError):
        tree.create("/A4", parent_path="/", spec_ref="A4", node_kind=NodeKind.TASK)


def test_legal_and_illegal_transitions() -> None:
    tree = TaskTree()
    tree.create("/A4", parent_path="/", spec_ref="A4", node_kind=NodeKind.TASK)
    for status in (Status.READY, Status.RUNNING, Status.CHECK, Status.DONE):
        tree.transition("/A4", status)
    assert tree.require("/A4").status is Status.DONE
    with pytest.raises(StatusTransitionError):
        tree.transition("/A4", Status.RUNNING)
