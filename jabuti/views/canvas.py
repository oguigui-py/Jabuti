"""QGraphicsView com zoom no scroll, pan por arraste e destaque de folhas."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QWheelEvent
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from jabuti.views.tree_renderer import RenderResult, make_highlight


class TreeCanvas(QGraphicsView):
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
