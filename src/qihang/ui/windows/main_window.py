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
    QFileDialog,
    QGraphicsView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QToolBar,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from qihang.app import spec_service
from qihang.app.run_session import create_session
from qihang.core.errors import SpecError
from qihang.ui.bench import GuiProbe
from qihang.ui.bridge.core_event_bridge import CoreEventBridge
from qihang.ui.models.instance_tree_model import InstanceTreeModel
from qihang.ui.views.dag_view import DagScene
from qihang.ui.windows.add_agent_dialog import AddAgentDialog


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
        self._probe = GuiProbe(self)
        self._bench_report: dict | None = None

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

    def _reload_agents(self, select: str | None = None) -> None:
        """从 specs 目录动态加载 agent 列表；坏 spec 不阻断，收集中文错误。"""
        current = select or self._agent.currentText()
        agents, errors = spec_service.list_agents(self._specs_dir)
        self._agent.blockSignals(True)
        self._agent.clear()
        self._agent.addItems(agents)
        if current in agents:
            self._agent.setCurrentText(current)
        self._agent.blockSignals(False)
        if errors:
            self._log.appendPlainText("spec 读取失败（已跳过）：" + "；".join(errors))

    def _add_agent(self) -> None:
        dialog = AddAgentDialog(self)
        if dialog.exec() != AddAgentDialog.DialogCode.Accepted or dialog.saved_data is None:
            return
        try:
            spec = spec_service.validate_agent_spec(dialog.saved_data, source="新建 Agent")
            spec_service.save_agent_spec(self._specs_dir, dialog.saved_data, source="新建 Agent")
        except SpecError as exc:
            QMessageBox.warning(self, "保存失败", exc.message)
            return
        self._reload_agents(select=spec.agent_id)
        self._status.setText(f"已添加 {spec.agent_id}")
        self._log.appendPlainText(f"已保存 spec：{self._specs_dir / (spec.agent_id.lower() + '.yaml')}")

    def _import_agent(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 Spec", str(self._specs_dir), "YAML (*.yaml *.yml);;所有文件 (*)"
        )
        if not path:
            return
        try:
            target = spec_service.import_agent_spec(path, self._specs_dir)
            spec = spec_service.load_agent_spec(target)
        except SpecError as exc:
            QMessageBox.warning(self, "导入失败", exc.message)
            return
        self._reload_agents(select=spec.agent_id)
        self._status.setText(f"已导入 {spec.agent_id}")
        self._log.appendPlainText(f"已保存 spec：{target}")

    def _build_toolbar(self) -> None:
        bar = QToolBar("运行")
        bar.setMovable(False)
        self.addToolBar(bar)

        bar.addWidget(QLabel("Agent "))
        self._agent = QComboBox()
        bar.addWidget(self._agent)
        self._reload_agents()

        add_action = QAction("添加 Agent", self)
        add_action.triggered.connect(self._add_agent)
        bar.addAction(add_action)
        import_action = QAction("导入 Spec", self)
        import_action.triggered.connect(self._import_agent)
        bar.addAction(import_action)

        bar.addWidget(QLabel("  每任务耗时(s) "))
        self._delay = QDoubleSpinBox()
        self._delay.setRange(0.01, 5.0)
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
        self._bench_report = None
        self._start_action.setEnabled(False)
        self._status.setText(f"运行中 · {agent}")
        self._probe.start()

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
        tree_started = time.perf_counter()
        self._tree_model.apply_events(batch)
        tree_ms = (time.perf_counter() - tree_started) * 1000.0
        dag_started = time.perf_counter()
        scene_changed = self._scene.apply_events(batch)
        dag_ms = (time.perf_counter() - dag_started) * 1000.0
        self._probe.record_batch(
            size=len(batch), tree_ms=tree_ms, dag_ms=dag_ms, dag_changed=scene_changed
        )
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
        self._probe.stop()
        self._bench_report = self._probe.report(
            scenario=self._agent.currentText(),
            instances=len(self._tree_model.known_paths),
            events_total=self._events_total,
            wall_ms=int(wall or 0),
            status=str(status),
            delay_s=round(self._delay.value(), 3),
        )
        self._status.setText(f"结束 · status={status} · 实例 {total} · {wall}ms")
        self._start_action.setEnabled(True)

    @property
    def scenario_names(self) -> tuple[str, ...]:
        return tuple(self._agent.itemText(i) for i in range(self._agent.count()))

    @property
    def run_finished(self) -> bool:
        return self._status.text().startswith("结束")

    def bench_report(self) -> dict | None:
        return self._bench_report

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._probe.stop()
        if self._bridge is not None:
            self._bridge.stop()
        if self._session is not None:
            self._session.close()
        super().closeEvent(event)
