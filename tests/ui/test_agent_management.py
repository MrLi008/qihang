"""GUI 动态 agent 列表、新建/导入落盘、A7 500 实例与压测指标。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog  # noqa: E402

from qihang.app import spec_service  # noqa: E402
from qihang.core.errors import SpecError  # noqa: E402
from qihang.paths import SPECS_DIR, default_runs_dir  # noqa: E402
from qihang.ui.theme.manager import ThemeManager  # noqa: E402
from qihang.ui.windows import main_window as main_window_module  # noqa: E402
from qihang.ui.windows.main_window import MainWindow  # noqa: E402

pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _wait(window: MainWindow, timeout_ms: int = 30_000) -> None:
    elapsed = 0
    while elapsed < timeout_ms and not window.run_finished:
        QTest.qWait(20)
        elapsed += 20
    assert window.run_finished, f"超时：{window._status.text()}"


def test_agent_list_is_loaded_from_specs_dir(app) -> None:
    window = MainWindow(ThemeManager("light"), specs_dir=SPECS_DIR, runs_dir=default_runs_dir())
    names = window.scenario_names
    assert "A7" in names
    assert "A9" in names
    assert "A4" in names
    window.close()


def test_add_and_import_agent_persist_after_reopen(app, tmp_path: Path) -> None:
    for spec in SPECS_DIR.glob("*.yaml"):
        (tmp_path / spec.name).write_text(spec.read_text(encoding="utf-8"), encoding="utf-8")

    data = spec_service.build_new_agent_spec(
        agent_id="X2",
        display_name="自定义规模",
        role_definition="负责验证配置驱动。",
        subtask_mode="static",
        expand_mode="fanout",
        nodes=12,
    )
    target = spec_service.save_agent_spec(tmp_path, data, source="X2")
    assert target.exists()

    source = tmp_path / "imported.yaml"
    text = (SPECS_DIR / "a7.yaml").read_text(encoding="utf-8").replace("agent: A7", "agent: R7", 1)
    source.write_text(text, encoding="utf-8")
    imported = spec_service.import_agent_spec(source, tmp_path)
    assert imported.exists()

    window = MainWindow(ThemeManager("light"), specs_dir=tmp_path, runs_dir=default_runs_dir())
    assert set(window.scenario_names) >= {"X2", "R7", "A7"}
    window.close()


def test_invalid_spec_is_not_written(app, tmp_path: Path) -> None:
    bad = {"agent": "BAD", "unknown_field": 1}
    with pytest.raises(SpecError) as exc:
        spec_service.save_agent_spec(tmp_path, bad, source="BAD")
    assert "unknown_field" in exc.value.message and "未知字段" in exc.value.message
    assert not list(tmp_path.glob("bad.yaml"))


def _working_specs(tmp_path: Path) -> Path:
    for spec in SPECS_DIR.glob("*.yaml"):
        (tmp_path / spec.name).write_text(spec.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_add_agent_via_toolbar_persists(app, tmp_path: Path, monkeypatch) -> None:
    specs = _working_specs(tmp_path)
    data = spec_service.build_new_agent_spec(agent_id="X3", display_name="界面新建", nodes=6)

    class FakeDialog:
        DialogCode = QDialog.DialogCode

        def __init__(self, parent=None) -> None:
            self._data = data

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        @property
        def saved_data(self) -> dict:
            return self._data

    monkeypatch.setattr(main_window_module, "AddAgentDialog", FakeDialog)
    window = MainWindow(ThemeManager("light"), specs_dir=specs, runs_dir=default_runs_dir())
    window._add_agent()
    assert "X3" in window.scenario_names
    assert (specs / "x3.yaml").exists()
    window.close()

    reopened = MainWindow(ThemeManager("light"), specs_dir=specs, runs_dir=default_runs_dir())
    assert "X3" in reopened.scenario_names
    reopened.close()


def test_import_agent_via_toolbar_persists(app, tmp_path: Path, monkeypatch) -> None:
    specs = _working_specs(tmp_path)
    source = tmp_path / "imported_r8.yaml"
    text = (SPECS_DIR / "a7.yaml").read_text(encoding="utf-8").replace("agent: A7", "agent: R8", 1)
    source.write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(source), "YAML (*.yaml)")
    )

    window = MainWindow(ThemeManager("light"), specs_dir=specs, runs_dir=default_runs_dir())
    window._import_agent()
    assert "R8" in window.scenario_names
    assert (specs / "r8.yaml").exists()
    window.close()

    reopened = MainWindow(ThemeManager("light"), specs_dir=specs, runs_dir=default_runs_dir())
    assert "R8" in reopened.scenario_names
    reopened.close()


def test_a7_500_nodes_and_bench_metrics(app) -> None:
    theme = ThemeManager("light")
    theme.apply(app)
    window = MainWindow(theme, specs_dir=SPECS_DIR, runs_dir=default_runs_dir(), delay_s=0.01)
    window.set_scenario("A7")
    assert window._agent.currentText() == "A7"
    window.show()
    window.start_run()
    _wait(window, timeout_ms=60_000)

    assert len(window._tree_model.known_paths) == 505
    assert len(window._scene.known_paths) == 505
    report = window.bench_report()
    assert report is not None
    assert report["instances"] == 505
    assert report["events"]["total"] > 4000
    assert report["heartbeat_ms"]["samples"] > 0
    assert report["dag_render_ms"]["samples"] > 0
    assert report["tree_batch_ms"]["max"] is not None
    window.close()


def test_a9_multilevel_runs_in_gui(app) -> None:
    theme = ThemeManager("light")
    theme.apply(app)
    window = MainWindow(theme, specs_dir=SPECS_DIR, runs_dir=default_runs_dir(), delay_s=0.01)
    window.set_scenario("A9")
    assert window._agent.currentText() == "A9"
    window.show()
    window.start_run()
    _wait(window, timeout_ms=30_000)

    assert len(window._tree_model.known_paths) == 30
    assert "/A9/E1/T1/E2/T1.1/E3/T1.1.1" in window._tree_model.known_paths
    assert "/A9/E1/T1/E2/T1.1/E3/T1.1.1" in window._scene.known_paths
    window.close()
