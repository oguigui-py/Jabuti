"""QGraphicsView com zoom no scroll, pan por arraste, destaque e seleção de folhas.

Seleção: Cmd/Ctrl+clique alterna uma folha; Shift+clique seleciona o intervalo
na ordem desenhada; clique simples numa folha seleciona só ela; clique simples
em área vazia ou Esc limpa. A seleção é guardada por nome (sobrevive a redesenhos)
e não vai para o arquivo exportado."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QContextMenuEvent,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene, QGraphicsView

from jabuti.views.tree_renderer import RenderResult, make_highlight


class TreeCanvas(QGraphicsView):
    node_context_requested = Signal(object, QPoint)  # (Node, posição global)
    selection_changed = Signal(list)                 # nomes das folhas selecionadas
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
        self.selected: list[str] = []
        self._sel_items: list = []
        self._sel_anchor: str | None = None
        self._press_pos: QPoint | None = None

    EMPTY_TEXT = ("Nenhuma árvore aberta\n\n"
                  "Arquivo → Abrir árvore… (Cmd/Ctrl+O)\n"
                  "ou arraste um arquivo .nwk / .treefile para esta área")

    @property
    def tree_scene(self) -> QGraphicsScene:
        return self._scene

    def is_empty(self) -> bool:
        return not self._scene.items()

    def drawForeground(self, painter: QPainter, rect) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        """Estado vazio: instrução no meio da tela (só na tela; a exportação desenha a cena)."""
        super().drawForeground(painter, rect)
        if not self.is_empty():
            return
        painter.save()
        painter.resetTransform()
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * 1.15)
        painter.setFont(f)
        painter.setPen(QColor("#7a7a7a"))
        painter.drawText(QRectF(self.viewport().rect()), int(Qt.AlignmentFlag.AlignCenter), self.EMPTY_TEXT)
        painter.restore()

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

    def leaf_at(self, view_pos: QPoint) -> str | None:
        """Folha sob o ponto: rótulo (forma real, inclusive girado) ou ponta do ramo."""
        if self.result is None:
            return None
        scene_pt = self.mapToScene(view_pos)
        for name, items in self.result.leaf_items.items():
            for it in items:
                if it.contains(it.mapFromScene(scene_pt)):
                    return name
        bg = self.result.label_backgrounds
        hits = [name for name, item in bg.items() if item.contains(item.mapFromScene(scene_pt))]
        if hits:
            # fundo compartilhado por várias folhas (bloco): a folha da linha clicada. Primeiro
            # a distância perpendicular ao texto (a linha; no circular, a direção tangencial),
            # depois ao longo dele. Medir até o centro do texto falhava com nomes de tamanhos
            # muito diferentes: o centro de um nome longo na linha vizinha ficava mais perto.
            def dist(name: str) -> tuple[float, float]:
                it = self.result.leaf_items[name][0]
                p, r = it.mapFromScene(scene_pt), it.boundingRect()
                across = abs(p.y() - r.center().y())
                along = max(r.left() - p.x(), 0.0, p.x() - r.right())
                return across, along

            return min(hits, key=dist)
        scale = self.transform().m11() or 1.0
        tol = (self.PICK_TOLERANCE_PX / scale) ** 2
        best, best_d = None, tol
        for name, p in self.result.leaf_points.items():
            d = (p.x() - scene_pt.x()) ** 2 + (p.y() - scene_pt.y()) ** 2
            if d <= best_d:
                best, best_d = name, d
        return best

    # ------------------------------------------------------------ seleção
    def set_selection(self, names, anchor: str | None = None) -> None:  # type: ignore[no-untyped-def]
        drawn = self.result.leaf_points if self.result is not None else {}
        new = [n for n in dict.fromkeys(names) if n in drawn]
        changed = new != self.selected
        self.selected = new
        self._sel_anchor = anchor if anchor in new else (new[-1] if new else None)
        self._draw_selection()
        if changed:
            self.selection_changed.emit(list(self.selected))

    def clear_selection(self) -> None:
        self.set_selection([])

    def click_leaf(self, name: str, modifiers: Qt.KeyboardModifier) -> None:
        """Aplica a regra de seleção de um clique (usado pelo mouse e pelos testes)."""
        order = list(self.result.leaf_points) if self.result is not None else []
        if modifiers & Qt.KeyboardModifier.ShiftModifier and self._sel_anchor in order and name in order:
            i, j = sorted((order.index(self._sel_anchor), order.index(name)))
            rng = order[i:j + 1]
            keep = self.selected if modifiers & (Qt.KeyboardModifier.ControlModifier
                                                 | Qt.KeyboardModifier.MetaModifier) else []
            self.set_selection([*keep, *rng], anchor=self._sel_anchor)
        elif modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            if name in self.selected:
                self.set_selection([n for n in self.selected if n != name])
            else:
                self.set_selection([*self.selected, name], anchor=name)
        else:
            self.set_selection([name], anchor=name)

    def _draw_selection(self) -> None:
        for item in self._sel_items:
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._sel_items = []
        if self.result is None:
            return
        pen = QPen(QColor("#1971c2"), 1.2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        for name in self.selected:
            items = self.result.leaf_items.get(name) or []
            if not items:
                continue
            shared = name in self.result.shared_backgrounds   # bloco de várias folhas: contorna o texto
            ref = (None if shared else self.result.label_backgrounds.get(name)) or items[0]
            rect = QGraphicsRectItem(ref.boundingRect().adjusted(-1.5, -1, 1.5, 1))
            rect.setPen(pen)
            rect.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            rect.setTransformOriginPoint(ref.transformOriginPoint())
            rect.setRotation(ref.rotation())
            rect.setPos(ref.pos())
            rect.setZValue(5)
            rect.setData(0, "selection")
            self._scene.addItem(rect)
            self._sel_items.append(rect)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._press_pos = None
        if event.button() == Qt.MouseButton.LeftButton:
            mods = event.modifiers()
            selecting = mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
                                | Qt.KeyboardModifier.ShiftModifier)
            if selecting:
                name = self.leaf_at(event.position().toPoint())
                if name is not None:
                    self.click_leaf(name, mods)
                    event.accept()
                    return
            else:
                self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        press, self._press_pos = self._press_pos, None
        super().mouseReleaseEvent(event)
        if press is None or event.button() != Qt.MouseButton.LeftButton:
            return
        if (event.position().toPoint() - press).manhattanLength() > 4:
            return  # foi arraste (pan), não clique
        name = self.leaf_at(press)
        if name is not None:
            self.click_leaf(name, Qt.KeyboardModifier.NoModifier)
        elif self.selected:
            self.clear_selection()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.selected:
            self.clear_selection()
            event.accept()
            return
        super().keyPressEvent(event)

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

    def show_transparency(self, transparent: bool) -> None:
        """Fundo transparente: mostra xadrez na tela (a cena fica sem fundo)."""
        if transparent:
            pm = QPixmap(16, 16)
            pm.fill(QColor("#ffffff"))
            p = QPainter(pm)
            p.fillRect(0, 0, 8, 8, QColor("#e6e6e6"))
            p.fillRect(8, 8, 8, 8, QColor("#e6e6e6"))
            p.end()
            self.setBackgroundBrush(QBrush(pm))
        else:
            self.setBackgroundBrush(QBrush(Qt.BrushStyle.NoBrush))  # usa o fundo da cena

    def set_result(self, result: RenderResult) -> None:
        self.result = result
        self._highlights = []
        self._sel_items = []        # a cena foi limpa; redesenha a seleção por nome
        self.set_selection(self.selected, self._sel_anchor)

    def clear_highlights(self) -> None:
        for item in self._highlights:
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._highlights = []

    def search(self, query: str) -> list[str]:
        """Destaca folhas cujo nome (original ou exibido) contém ``query`` (sem diferenciar maiúsculas)."""
        self.clear_highlights()
        q = query.strip().lower()
        if not q or self.result is None:
            return []
        shown = self.result.display

        def texts(n: str) -> tuple[str, str]:
            return n.lower(), shown.get(n, n).lower()

        # o nome original e o nome exibido valem na busca
        exact = [n for n in self.result.leaf_items if q in texts(n)]      # igual a um dos dois
        matches = exact or [n for n in self.result.leaf_items if any(q in t for t in texts(n))]
        for name in matches:
            for item in self.result.leaf_items[name]:
                self._highlights.append(make_highlight(self._scene, item))
        if matches:
            first = self.result.leaf_items[matches[0]][0]
            self.centerOn(first.sceneBoundingRect().center())
        return matches
