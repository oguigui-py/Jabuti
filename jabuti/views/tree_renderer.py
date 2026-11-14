"""Monta os itens da QGraphicsScene a partir do layout e do estilo."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
)

from jabuti.layout.circular import circular_layout
from jabuti.layout.rectangular import rectangular_layout
from jabuti.models.tree import Node, Tree
from jabuti.style import LayoutKind, RenderStyle

HIGHLIGHT = QColor("#ffe066")


@dataclass
class RenderResult:
    leaf_items: dict[str, list[QGraphicsSimpleTextItem]] = field(default_factory=dict)
    leaf_points: dict[str, QPointF] = field(default_factory=dict)


def _fmt_support(values: list[float], index: int) -> str:
    def f(v: float) -> str:
        return f"{v:g}" if v != int(v) or abs(v) >= 1 else f"{v:.2f}"

    if index == 99 or len(values) == 1:
        return "/".join(f(v) for v in values)
    i = index if -len(values) <= index < len(values) else -1
    return f(values[i])


def _support_value(values: list[float], index: int) -> float:
    if index == 99:
        return min(values)
    i = index if -len(values) <= index < len(values) else -1
    return values[i]


def _nice_scale(max_len: float) -> float:
    """Comprimento 'redondo' para a barra de escala (~1/5 da árvore)."""
    if max_len <= 0:
        return 0.0
    target = max_len / 5
    exp = math.floor(math.log10(target))
    for m in (1, 2, 5, 10):
        val = m * 10**exp
        if val >= target:
            return val
    return 10 ** (exp + 1)


class TreeRenderer:
    def __init__(self, scene: QGraphicsScene) -> None:
        self.scene = scene

    def render(self, tree: Tree, style: RenderStyle) -> RenderResult:
        self.scene.clear()
        font = QFont()
        font.setPointSizeF(style.font_size)
        self._font = font
        self._fm = QFontMetricsF(font)
        self._pen = QPen(QColor("#202020"), style.branch_width)
        self._pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        self._pen.setCosmetic(False)
        res = RenderResult()
        if style.layout == LayoutKind.CIRCULAR:
            self._render_circular(tree, style, res)
        else:
            self._render_rectangular(tree, style, res)
        margin = 30
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-margin, -margin, margin, margin))
        return res

    # ----------------------------------------------------------- helpers
    def _text(self, text: str, size: float | None = None, color: str = "#202020") -> QGraphicsSimpleTextItem:
        item = QGraphicsSimpleTextItem(text)
        f = QFont(self._font)
        if size is not None:
            f.setPointSizeF(size)
        item.setFont(f)
        item.setBrush(QBrush(QColor(color)))
        self.scene.addItem(item)
        return item

    def _add_path(self, path: QPainterPath) -> None:
        item = QGraphicsPathItem(path)
        item.setPen(self._pen)
        self.scene.addItem(item)

    def _support_items(self, tree: Tree, style: RenderStyle, place) -> None:  # type: ignore[no-untyped-def]
        if not style.show_support:
            return
        small = max(style.font_size * 0.75, 4)
        for node in tree.root.traverse_preorder():
            if node.is_leaf or not node.supports or node is tree.root:
                continue
            if _support_value(node.supports, style.support_index) < style.support_threshold:
                continue
            item = self._text(_fmt_support(node.supports, style.support_index), small, "#555555")
            place(node, item)

    # ----------------------------------------------------- rectangular
    def _render_rectangular(self, tree: Tree, style: RenderStyle, res: RenderResult) -> None:
        lay = rectangular_layout(tree, style.use_lengths)
        sx = (style.base_width * style.branch_scale) / lay.max_x if lay.max_x > 0 else 1.0
        sy = style.font_size * style.leaf_spacing

        def pt(node: Node) -> QPointF:
            x, y = lay.pos[node]
            return QPointF(x * sx, y * sy)

        path = QPainterPath()
        for node in tree.root.traverse_preorder():
            p = pt(node)
            if node.parent is not None:
                pp = pt(node.parent)
                path.moveTo(pp.x(), p.y())
                path.lineTo(p)
            if node.children:
                top, bot = pt(node.children[0]), pt(node.children[-1])
                path.moveTo(p.x(), top.y())
                path.lineTo(p.x(), bot.y())
        self._add_path(path)

        label_x_pad = style.font_size * 0.5
        if style.show_leaf_labels:
            for leaf in lay.leaf_order:
                p = pt(leaf)
                item = self._text(leaf.name)
                h = item.boundingRect().height()
                item.setPos(p.x() + label_x_pad, p.y() - h / 2)
                res.leaf_items.setdefault(leaf.name, []).append(item)
                res.leaf_points[leaf.name] = p

        def place(node: Node, item: QGraphicsSimpleTextItem) -> None:
            p = pt(node)
            r = item.boundingRect()
            item.setPos(p.x() - r.width() - 2, p.y() - r.height())

        self._support_items(tree, style, place)

        if lay.uses_lengths and lay.max_x > 0:
            n = len(lay.leaf_order)
            self._scale_bar(QPointF(0, n * sy + sy), lay.max_x, sx)

    # -------------------------------------------------------- circular
    def _render_circular(self, tree: Tree, style: RenderStyle, res: RenderResult) -> None:
        lay = circular_layout(tree, style.use_lengths)
        n = len(lay.leaf_order)
        spacing = style.font_size * style.leaf_spacing
        # raio mínimo para as folhas não se sobreporem
        min_r = n * spacing / (2 * math.pi)
        r_target = max(style.base_width * 0.5, min_r) * style.branch_scale
        sr = r_target / lay.max_r if lay.max_r > 0 else 1.0

        def pt(r: float, th: float) -> QPointF:
            return QPointF(r * sr * math.cos(th), r * sr * math.sin(th))

        path = QPainterPath()
        for node in tree.root.traverse_preorder():
            r, th = lay.pos[node]
            if node.parent is not None:
                pr, _ = lay.pos[node.parent]
                path.moveTo(pt(pr, th))
                path.lineTo(pt(r, th))
            if node.children:
                th0 = lay.pos[node.children[0]][1]
                th1 = lay.pos[node.children[-1]][1]
                rad = r * sr
                if rad > 0:
                    rect = QRectF(-rad, -rad, 2 * rad, 2 * rad)
                    # Qt: ângulos em graus, sentido anti-horário, eixo y para baixo
                    path.arcMoveTo(rect, -math.degrees(th0))
                    path.arcTo(rect, -math.degrees(th0), -math.degrees(th1 - th0))
        self._add_path(path)

        pad = style.font_size * 0.5
        if style.show_leaf_labels:
            for leaf in lay.leaf_order:
                r, th = lay.pos[leaf]
                item = self._text(leaf.name)
                br = item.boundingRect()
                deg = math.degrees(th) % 360
                flip = 90 < deg < 270
                anchor = pt(r, th)
                anchor = QPointF(anchor.x() + pad * math.cos(th), anchor.y() + pad * math.sin(th))
                if flip:
                    item.setTransformOriginPoint(br.width(), br.height() / 2)
                    item.setRotation(deg - 180)
                    item.setPos(anchor.x() - br.width(), anchor.y() - br.height() / 2)
                else:
                    item.setTransformOriginPoint(0, br.height() / 2)
                    item.setRotation(deg)
                    item.setPos(anchor.x(), anchor.y() - br.height() / 2)
                res.leaf_items.setdefault(leaf.name, []).append(item)
                res.leaf_points[leaf.name] = pt(r, th)

        def place(node: Node, item: QGraphicsSimpleTextItem) -> None:
            r, th = lay.pos[node]
            p = pt(r, th)
            br = item.boundingRect()
            item.setPos(p.x() - br.width() / 2, p.y() - br.height() / 2)

        self._support_items(tree, style, place)

        if lay.uses_lengths and lay.max_r > 0:
            outer = self.scene.itemsBoundingRect()
            self._scale_bar(QPointF(outer.left(), outer.bottom() + spacing), lay.max_r, sr)

    # ------------------------------------------------------- escala
    def _scale_bar(self, origin: QPointF, max_len: float, px_per_unit: float) -> None:
        val = _nice_scale(max_len)
        if val <= 0:
            return
        w = val * px_per_unit
        path = QPainterPath()
        path.moveTo(origin)
        path.lineTo(origin.x() + w, origin.y())
        tick = 4
        for x in (origin.x(), origin.x() + w):
            path.moveTo(x, origin.y() - tick)
            path.lineTo(x, origin.y() + tick)
        self._add_path(path)
        label = self._text(f"{val:g}", max(self._font.pointSizeF() * 0.8, 4))
        label.setPos(origin.x() + w / 2 - label.boundingRect().width() / 2, origin.y() + tick + 1)


def make_highlight(scene: QGraphicsScene, item: QGraphicsSimpleTextItem) -> QGraphicsRectItem:
    """Retângulo amarelo atrás de um rótulo (respeita rotação)."""
    rect = QGraphicsRectItem(item.boundingRect().adjusted(-2, -1, 2, 1))
    rect.setBrush(QBrush(HIGHLIGHT))
    rect.setPen(QPen(Qt.PenStyle.NoPen))
    rect.setTransformOriginPoint(item.transformOriginPoint())
    rect.setRotation(item.rotation())
    rect.setPos(item.pos())
    rect.setZValue(-1)
    rect.setData(0, "highlight")
    scene.addItem(rect)
    return rect
