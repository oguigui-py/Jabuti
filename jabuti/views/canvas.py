"""QGraphicsView com zoom no scroll, pan por arraste e destaque de folhas."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QContextMenuEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from jabuti.views.tree_renderer import RenderResult, make_highlight


class TreeCanvas(QGraphicsView):
    node_context_requested = Signal(object, QPoint)  # (Node, posição global)
    PICK_TOLERANCE_PX = 14
    MIN_ZOOM = 0.02
    MAX_ZOOM = 60.0

    def __init__(self, parent=None) -> None:  # type: ignore[no-untyped-def]
        self._scene = QGraphicsScene()
        self._scene.setBackgroundBrush(QColor("white"))
        super().__init__(self._scene, parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.result: RenderResult | None = None
        self._highlights: list = []

    @property
    def tree_scene(self) -> QGraphicsScene:
        return self._scene

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta == 0:
            return
        factor = 1.0015 ** delta
        current = self.transform().m11()
        new = min(max(current * factor, self.MIN_ZOOM), self.MAX_ZOOM)
        self.scale(new / current, new / current)

    def zoom_by(self, factor: float) -> None:
        current = self.transform().m11()
        new = min(max(current * factor, self.MIN_ZOOM), self.MAX_ZOOM)
        self.scale(new / current, new / current)

    def node_at(self, view_pos: QPoint):  # type: ignore[no-untyped-def]
        """Nó mais próximo do ponto (em px de tela), dentro da tolerância."""
        if self.result is None or not self.result.node_points:
            return None
        scene_pt = self.mapToScene(view_pos)
        scale = self.transform().m11() or 1.0
        tol = self.PICK_TOLERANCE_PX / scale
        best, best_d = None, tol * tol
        for node, p in self.result.node_points.items():
            d = (p.x() - scene_pt.x()) ** 2 + (p.y() - scene_pt.y()) ** 2
            if d <= best_d:
                best, best_d = node, d
        if best is None:  # clique sobre um rótulo de folha
            for name, items in self.result.leaf_items.items():
                if any(it.sceneBoundingRect().contains(scene_pt) for it in items):
                    best = next((n for n in self.result.node_points if n.is_leaf and n.name == name), None)
                    break
        return best

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        node = self.node_at(event.pos())
        if node is not None:
            self.node_context_requested.emit(node, event.globalPos())
            event.accept()
        else:
            super().contextMenuEvent(event)

    def fit(self) -> None:
        rect = self._scene.sceneRect()
        if not rect.isEmpty():
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def set_result(self, result: RenderResult) -> None:
        self.result = result
        self._highlights = []

    def clear_highlights(self) -> None:
        for item in self._highlights:
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._highlights = []

    def search(self, query: str) -> list[str]:
        """Destaca folhas cujo nome contém ``query`` (sem diferenciar maiúsculas)."""
        self.clear_highlights()
        q = query.strip().lower()
        if not q or self.result is None:
            return []
        exact = [n for n in self.result.leaf_items if n.lower() == q]
        matches = exact or [n for n in self.result.leaf_items if q in n.lower()]
        for name in matches:
            for item in self.result.leaf_items[name]:
                self._highlights.append(make_highlight(self._scene, item))
        if matches:
            first = self.result.leaf_items[matches[0]][0]
            self.centerOn(first.sceneBoundingRect().center())
        return matches
