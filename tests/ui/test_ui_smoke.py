"""UI 冒烟：主题 token、事件桥、DAG 增量着色、实例树 patch、窗口跑一次 mock run。

运行方式：
    pytest tests/ui -m ui
无 PyQt6 的环境会整体 skip（core-only CI job 不装 PyQt）。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from qihang.core.model.events import EventBus  # noqa: E402
from qihang.core.model.enums import EventKind  # noqa: E402
from qihang.paths import SPECS_DIR, default_runs_dir  # noqa: E402
from qihang.ui.bridge.core_event_bridge import CoreEventBridge  # noqa: E402
from qihang.ui.models.instance_tree_model import InstanceTreeModel  # noqa: E402
from qihang.ui.theme.manager import ThemeManager  # noqa: E402
from qihang.ui.views.dag_view import DagScene  # noqa: E402
from qihang.ui.windows.main_window import MainWindow  # noqa: E402

pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _events(bus: EventBus) -> list:
    return bus.drain(100)


def test_theme_manager_tokens_and_app_qss(app):
    for name in ("light", "dark"):
        theme = ThemeManager(name)
        qss = theme.render_qss()
        assert "{{" not in qss and "}}" not in qss
        assert theme.color("surface").startswith("#")
        assert theme.status_color("DONE") == theme.color("status.done")
    ThemeManager("light").apply(app)
    assert "{{" not in app.styleSheet()


def test_event_bridge_drains_queue(app):
    bus = EventBus("UI-BRIDGE")
    bus.emit(EventKind.RUN_STARTED, "/A4", agent="A4")
    bus.emit(EventKind.INSTANCE_CREATED, "/A4", node_kind="task", status="PENDING")
    bridge = CoreEventBridge(bus)
    received: list[list] = []
    bridge.batch_ready.connect(received.append)
    assert bridge.poll()
    assert len(received) == 1 and len(received[0]) == 2
    assert bridge.drained == 2


def test_dag_scene_incremental_status_color(app):
    theme = ThemeManager("light")
    bus = EventBus("UI-DAG")
    bus.emit(EventKind.INSTANCE_CREATED, "/A4", node_kind="task", status="PENDING")
    bus.emit(EventKind.INSTANCE_CREATED, "/A4/S1", node_kind="task", status="PENDING")
    bus.emit(EventKind.INSTANCE_STATE, "/A4/S1", **{"from": "PENDING", "to": "RUNNING"})
    scene = DagScene(theme)
    assert scene.apply_events(_events(bus)) == 3
    node = scene.node("/A4/S1")
    assert node is not None
    assert node.pen().color().name().lower() == QColor(theme.status_color("RUNNING")).name().lower()

    bus.emit(EventKind.INSTANCE_STATE, "/A4/S1", **{"from": "RUNNING", "to": "DONE"})
    assert scene.apply_events(_events(bus)) == 1
    assert node.pen().color().name().lower() == QColor(theme.status_color("DONE")).name().lower()
    assert set(scene.known_paths) == {"/A4", "/A4/S1"}


def test_instance_tree_model_patch(app):
    bus = EventBus("UI-TREE")
    bus.emit(EventKind.INSTANCE_CREATED, "/A4", node_kind="task", status="PENDING")
    bus.emit(EventKind.INSTANCE_CREATED, "/A4/S1", node_kind="task", status="PENDING")
    bus.emit(EventKind.INSTANCE_STATE, "/A4/S1", **{"from": "PENDING", "to": "DONE", "duration_ms": 1000})
    bus.emit(EventKind.ARTIFACT_WRITTEN, "/A4/S1", output="file_list", hash="abc", size=10)
    model = InstanceTreeModel()
    changed = model.apply_events(_events(bus))
    assert changed >= 3
    assert set(model.known_paths) == {"/A4", "/A4/S1"}
    root_item = model.invisibleRootItem().child(0)
    assert root_item.child(0, 1).text() == "DONE"
    assert root_item.child(0, 2).text() == "1000ms"
    assert root_item.child(0, 3).text() == "file_list"


def test_main_window_runs_mock_a4(app):
    theme = ThemeManager("light")
    theme.apply(app)
    window = MainWindow(theme, specs_dir=SPECS_DIR, runs_dir=default_runs_dir(), delay_s=0.05)
    window.set_scenario("A4")
    window.show()
    window.start_run()

    deadline_ms = 15_000
    elapsed = 0
    while elapsed < deadline_ms and not window._status.text().startswith("结束"):
        QTest.qWait(20)
        elapsed += 20
    assert window._status.text().startswith("结束"), f"超时：{window._status.text()}"

    assert set(window._tree_model.known_paths) >= {"/A4", "/A4/S1", "/A4/E1", "/A4/J1", "/A4/S3"}
    assert window._events_total > 30
    assert len(window._scene.known_paths) == 8
    assert window._scene.node("/A4/E1/S2.1").pen().color().name().lower() == QColor(
        theme.status_color("DONE")
    ).name().lower()
    window.close()
