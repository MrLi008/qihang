"""主窗口：发起 Run、实例树、DAG、事件流面板。

线程边界：
- 内核在 RunLoop 线程里 tick；
- 事件由 CoreEventBridge 的 QTimer 在 GUI 线程 drain；
- 本窗口不调用 orchestrator.tick()、不 sleep、不碰执行器与存储。
"""

from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QPainter
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGraphicsView,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QSplitter,
    QToolBar,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from qihang.app.run_session import create_session
from qihang.ui.bridge.core_event_bridge import CoreEventBridge
from qihang.ui.models.instance_tree_model import InstanceTreeModel
from qihang.ui.views.dag_view import DagScene


def _event_line(event) -> str:
    path = event.task_path or "-"
    if event.kind == "INSTANCE_STATE":
        detail = f"{event.payload.get('from')} -> {event.payload.get('to')}"
    elif event.kind == "JOIN_DONE":
        detail = f"coverage={event.payload.get('coverage')}"
    elif event.kind == "EXPAND_PLANNED":
        detail = f"count={event.payload.get('count')}"
    elif event.kind == "RUN_FINISHED":
        detail = f"status={event.payload.get('status')} wall={event.payload.get('wall_time_ms')}ms"
    else:
        detail = ""
    return f"[{event.seq:03d}] {event.kind:<17} {path:<24} {detail}"


class MainWindow(QMainWindow):
    def __init__(
        self,
        theme,
        *,
        specs_dir: Path | str = "specs",
        runs_dir: Path | str = ".qihang/runs",
        delay_s: float = 1.0,
    ) -> None:
        super().__init__()
        self._theme = theme
        self._specs_dir = Path(specs_dir)
        self._runs_dir = Path(runs_dir)
        self._delay_s = delay_s
        self._session = None
        self._bridge: CoreEventBridge | None = None
        self._events_total = 0

        self.setWindowTitle("契衡 · 阶段一 Mock Run")
        self.resize(1180, 760)

        self._tree_model = InstanceTreeModel(self)
        self._tree_view = QTreeView()
        self._tree_view.setModel(self._tree_model)
        self._tree_view.setAlternatingRowColors(False)
        self._tree_view.header().setStretchLastSection(True)

        self._scene = DagScene(theme, self)
        self._dag_view = QGraphicsView(self._scene)
        self._dag_view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._dag_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(4000)

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self._tree_view)
        top.addWidget(self._dag_view)
        top.setSizes([420, 740])

        root = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(top)
        root.addWidget(self._log)
        root.setSizes([540, 180])

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(root)
        self.setCentralWidget(container)

        self._status = QLabel("就绪")
        self.statusBar().addWidget(self._status)
        self._build_toolbar()

    # ------------------------------------------------------------------ 工具栏
    def set_scenario(self, agent: str) -> None:
        if agent in [self._agent.itemText(i) for i in range(self._agent.count())]:
            self._agent.setCurrentText(agent)

    def _build_toolbar(self) -> None:
        bar = QToolBar("运行")
        bar.setMovable(False)
        self.addToolBar(bar)

        bar.addWidget(QLabel("Agent "))
        self._agent = QComboBox()
        self._agent.addItems(["A4", "A6"])
        bar.addWidget(self._agent)

        bar.addWidget(QLabel("  每任务耗时(s) "))
        self._delay = QDoubleSpinBox()
        self._delay.setRange(0.05, 5.0)
        self._delay.setSingleStep(0.1)
        self._delay.setDecimals(2)
        self._delay.setValue(self._delay_s)
        bar.addWidget(self._delay)

        self._start_action = QAction("发起 Run", self)
        self._start_action.triggered.connect(self.start_run)
        bar.addAction(self._start_action)

    # ------------------------------------------------------------------ 运行
    def start_run(self) -> None:
        if self._session is not None and self._session.running:
            return
        agent = self._agent.currentText()
        run_id = time.strftime("GUI-%H%M%S")
        self._tree_model.reset()
        self._scene.reset()
        self._log.clear()
        self._events_total = 0
        self._start_action.setEnabled(False)
        self._status.setText(f"运行中 · {agent}")

        self._session = create_session(
            self._specs_dir,
            self._runs_dir / run_id,
            run_id=run_id,
            delay_s=self._delay.value(),
        )
        self._bridge = CoreEventBridge(self._session.bus, parent=self)
        self._bridge.batch_ready.connect(self._on_events)
        self._bridge.start()

        self._session.start(agent)

    def _on_events(self, batch) -> None:
        self._tree_model.apply_events(batch)
        self._scene.apply_events(batch)
        self._tree_view.expandAll()
        for event in batch:
            self._log.appendPlainText(_event_line(event))
            self._events_total += 1
            if event.kind == "RUN_FINISHED":
                self._finish_run(event)

    def _finish_run(self, event) -> None:
        if self._bridge is not None:
            self._bridge.stop()
        if self._session is not None:
            self._session.stop_kernel()
        status = event.payload.get("status")
        total = event.payload.get("total")
        wall = event.payload.get("wall_time_ms")
        self._status.setText(f"结束 · status={status} · 实例 {total} · {wall}ms")
        self._start_action.setEnabled(True)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._bridge is not None:
            self._bridge.stop()
        if self._session is not None:
            self._session.close()
        super().closeEvent(event)
