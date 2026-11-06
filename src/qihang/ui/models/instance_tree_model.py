"""实例树视图模型：只对脏节点做插入/更新，整批用 blockSignals 包裹。

批次结束后发一次 `layoutChanged`，避免逐条 itemChanged 触发重复重绘。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QStandardItem, QStandardItemModel

HEADERS = ("实例", "状态", "耗时", "产物")


def _parent_path(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path.lstrip("/") else "/"


class InstanceTreeModel(QStandardItemModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHorizontalHeaderLabels(list(HEADERS))
        self._items: dict[str, QStandardItem] = {}
        self._batches = 0
        self._dirty: set[str] = set()

    @property
    def known_paths(self) -> tuple[str, ...]:
        return tuple(self._items)

    def reset(self) -> None:
        self.clear()
        self._items.clear()
        self._batches = 0
        self._dirty.clear()
        self.setHorizontalHeaderLabels(list(HEADERS))

    def _make_item(self, path: str, node_kind: str, status: str) -> QStandardItem:
        item = QStandardItem(f"{path.rsplit('/', 1)[-1]}")
        item.setData(path, Qt.ItemDataRole.UserRole)
        item.setData(node_kind, Qt.ItemDataRole.UserRole + 1)
        item.setToolTip(f"{path} · {node_kind}")
        status_item = QStandardItem(status)
        duration_item = QStandardItem("-")
        output_item = QStandardItem("-")
        return item, status_item, duration_item, output_item  # type: ignore[return-value]

    def _row_items(self, path: str) -> list[QStandardItem]:
        item = self._items[path]
        row = item.row()
        parent = item.parent() or self.invisibleRootItem()
        return [parent.child(row, col) for col in range(len(HEADERS))]

    def apply_events(self, events) -> int:
        """返回被修改（新建或状态变化）的节点数。"""
        changed: list[str] = []
        self.blockSignals(True)
        try:
            for event in events:
                path = event.task_path
                if not path:
                    continue
                if event.kind == "INSTANCE_CREATED":
                    if path in self._items:
                        continue
                    kind = str(event.payload.get("node_kind", "task"))
                    status = str(event.payload.get("status", "PENDING"))
                    item, status_item, duration_item, output_item = self._make_item(path, kind, status)
                    parent = self._items.get(_parent_path(path))
                    if parent is not None:
                        parent.appendRow([item, status_item, duration_item, output_item])
                    else:
                        self.appendRow([item, status_item, duration_item, output_item])
                    self._items[path] = item
                    changed.append(path)
                elif event.kind == "INSTANCE_STATE" and path in self._items:
                    cells = self._row_items(path)
                    cells[1].setText(str(event.payload.get("to", "")))
                    duration = event.payload.get("duration_ms")
                    cells[2].setText(f"{duration}ms" if duration is not None else "-")
                    changed.append(path)
                elif event.kind == "ARTIFACT_WRITTEN" and path in self._items:
                    cells = self._row_items(path)
                    output = str(event.payload.get("output", ""))
                    existing = cells[3].text()
                    cells[3].setText(output if existing == "-" else f"{existing},{output}")
                    changed.append(path)
        finally:
            self.blockSignals(False)
        if changed:
            self._batches += 1
            self._dirty = set(changed)
            self.layoutChanged.emit()
        return len(changed)
