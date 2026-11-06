"""最小 DAG 视图：QGraphicsScene + 节点对象池。

- 节点只在 INSTANCE_CREATED 时创建，INSTANCE_STATE 只更新自身（脏节点重绘）；
- 颜色全部来自 ThemeManager 的 status token（`setBrush/setPen` 不写死颜色）；
- 布局是简化分层：depth 决定列，创建顺序决定行；边随布局重算。
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QBrush, QColor, QPen
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
)

NODE_W = 180.0
NODE_H = 56.0
GAP_X = 90.0
GAP_Y = 26.0
MARGIN = 20.0


def _brush(color_hex: str) -> QBrush:
    return QBrush(QColor(color_hex))


def _pen(color_hex: str, width: float = 1.0) -> QPen:
    return QPen(QColor(color_hex), width)


class DagNodeItem(QGraphicsRectItem):
    def __init__(self, path: str, kind: str, status: str, theme) -> None:
        super().__init__(QRectF(0, 0, NODE_W, NODE_H))
        self.path = path
        self.kind = kind
        self.status = status
        self._theme = theme
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setToolTip(f"{path} · {kind}")
        label = path.rsplit("/", 1)[-1]
        self._title = QGraphicsSimpleTextItem(label, self)
        self._title.setPos(10, 7)
        self._kind = QGraphicsSimpleTextItem(kind, self)
        self._kind.setPos(10, 25)
        self._meta = QGraphicsSimpleTextItem("", self)
        self._meta.setPos(10, 37)
        self._outputs: list[str] = []
        self._repaint()

    def _repaint(self) -> None:
        self.setBrush(_brush(self._theme.color("surface")))
        self.setPen(_pen(self._theme.status_color(self.status), 3.0))
        self._title.setBrush(_brush(self._theme.color("text")))
        self._kind.setBrush(_brush(self._theme.color("muted")))
        self._meta.setBrush(_brush(self._theme.color("muted")))

    def update_status(self, status: str) -> None:
        if status == self.status:
            return
        self.status = status
        self._repaint()

    def add_output(self, output: str) -> None:
        if output and output not in self._outputs:
            self._outputs.append(output)
            self._meta.setText("·".join(self._outputs))

    def apply_theme(self, theme) -> None:
        self._theme = theme
        self._repaint()


class DagScene(QGraphicsScene):
    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._nodes: dict[str, DagNodeItem] = {}
        self._edges: dict[str, QGraphicsLineItem] = {}
        self.setSceneRect(0, 0, 900, 600)

    @property
    def known_paths(self) -> tuple[str, ...]:
        return tuple(self._nodes)

    def node(self, path: str) -> DagNodeItem | None:
        return self._nodes.get(path)

    def reset(self) -> None:
        self.clear()
        self._nodes.clear()
        self._edges.clear()
        self.setSceneRect(0, 0, 900, 600)

    def apply_events(self, events) -> int:
        changed = 0
        created = False
        for event in events:
            path = event.task_path
            if not path:
                continue
            if event.kind == "INSTANCE_CREATED":
                if path in self._nodes:
                    continue
                kind = str(event.payload.get("node_kind", "task"))
                status = str(event.payload.get("status", "PENDING"))
                node = DagNodeItem(path, kind, status, self._theme)
                node.setPos(*self._free_slot(path))
                self.addItem(node)
                self._nodes[path] = node
                created = True
                changed += 1
            elif event.kind == "INSTANCE_STATE":
                node = self._nodes.get(path)
                if node is not None:
                    node.update_status(str(event.payload.get("to", node.status)))
                    changed += 1
            elif event.kind == "ARTIFACT_WRITTEN":
                node = self._nodes.get(path)
                if node is not None:
                    node.add_output(str(event.payload.get("output", "")))
                    changed += 1
        if created:
            self._relayout()
        return changed

    def apply_theme(self, theme) -> None:
        self._theme = theme
        for node in self._nodes.values():
            node.apply_theme(theme)

    # ---- 简化分层布局 ----
    @staticmethod
    def _depth(path: str) -> int:
        return max(0, path.count("/") - 1)

    def _free_slot(self, path: str) -> tuple[float, float]:
        depth = self._depth(path)
        row = sum(1 for p in self._nodes if self._depth(p) == depth)
        return MARGIN + depth * (NODE_W + GAP_X), MARGIN + row * (NODE_H + GAP_Y)

    def _relayout(self) -> None:
        rows: dict[int, int] = {}
        for path, node in self._nodes.items():
            depth = self._depth(path)
            row = rows.get(depth, 0)
            rows[depth] = row + 1
            node.setPos(MARGIN + depth * (NODE_W + GAP_X), MARGIN + row * (NODE_H + GAP_Y))
            parent = path.rsplit("/", 1)[0]
            if parent in self._nodes:
                self._sync_edge(path, parent)
        rect = self.itemsBoundingRect()
        self.setSceneRect(rect.adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN))

    def _sync_edge(self, child: str, parent: str) -> None:
        edge = self._edges.get(child)
        if edge is None:
            edge = QGraphicsLineItem()
            edge.setPen(_pen(self._theme.color("border"), 1.0))
            edge.setZValue(-1)
            self.addItem(edge)
            self._edges[child] = edge
        p = self._nodes[parent].pos()
        c = self._nodes[child].pos()
        edge.setLine(p.x() + NODE_W, p.y() + NODE_H / 2, c.x(), c.y() + NODE_H / 2)
