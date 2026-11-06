"""新建 Agent 对话框：只收集关键字段并做中文校验，落盘由主窗口负责。

约束：颜色全部来自应用级 QSS（本文件不出现 setStyleSheet / 颜色字面量）。
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from qihang.app import spec_service
from qihang.core.errors import SpecError


class AddAgentDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加 Agent")
        self._data: dict[str, Any] | None = None

        self._agent_id = QLineEdit()
        self._agent_id.setPlaceholderText("例如 A8（字母开头，仅字母/数字/下划线）")
        self._display = QLineEdit()
        self._display.setPlaceholderText("例如 自定义场景")
        self._role = QPlainTextEdit()
        self._role.setPlaceholderText("角色定义与判断标准")
        self._role.setFixedHeight(90)

        self._mode = QComboBox()
        self._mode.addItem("静态子任务", "static")
        self._mode.addItem("动态拆解（DECOMPOSE）", "dynamic")

        self._expand = QComboBox()
        self._expand.addItem("无展开", "none")
        self._expand.addItem("静态 fan-out（S1→E1→J1→S3）", "fanout")

        self._nodes = QSpinBox()
        self._nodes.setRange(1, 20000)
        self._nodes.setValue(500)

        self._dynamic = QCheckBox("允许运行期动态扩展")
        self._dynamic.setToolTip("勾选后固定使用动态拆解结构（DECOMPOSE + expandables）")

        form = QFormLayout()
        form.addRow("Agent 标识", self._agent_id)
        form.addRow("展示名", self._display)
        form.addRow("角色定义", self._role)
        form.addRow("子任务模式", self._mode)
        form.addRow("展开方式", self._expand)
        form.addRow("子任务实例数", self._nodes)
        form.addRow("", self._dynamic)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._mode.currentIndexChanged.connect(self._sync_enabled)
        self._dynamic.toggled.connect(self._sync_enabled)
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        dynamic = self._dynamic.isChecked() or self._mode.currentData() == "dynamic"
        self._expand.setEnabled(not dynamic)
        self._nodes.setEnabled(not dynamic)

    def spec_data(self) -> dict[str, Any]:
        return spec_service.build_new_agent_spec(
            agent_id=self._agent_id.text(),
            display_name=self._display.text(),
            role_definition=self._role.toPlainText(),
            subtask_mode=str(self._mode.currentData()),
            expand_mode=str(self._expand.currentData()),
            nodes=self._nodes.value(),
            dynamic_expand=self._dynamic.isChecked(),
        )

    def accept(self) -> None:  # noqa: N802 (Qt 命名)
        try:
            spec_service.validate_agent_spec(self.spec_data(), source="新建 Agent")
        except SpecError as exc:
            QMessageBox.warning(self, "配置不合法", exc.message)
            return
        self._data = self.spec_data()
        super().accept()

    @property
    def saved_data(self) -> dict[str, Any] | None:
        return self._data
