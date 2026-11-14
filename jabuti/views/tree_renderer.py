"""Monta os itens da QGraphicsScene a partir do layout, do estilo e dos clados."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
)

from jabuti.layout.circular import CircGeometry, circular_geometry, circular_layout
from jabuti.layout.rectangular import rectangular_layout
from jabuti.models.clades import Clade, ResolvedClade, assign_nodes, resolve_clades
from jabuti.models.tree import SUPPORT_ALL, Node, Tree, support_value
from jabuti.style import LayoutKind, RenderStyle

HIGHLIGHT = QColor("#ffe066")

# marcas em item.data(1) — usadas por testes e pelo export
TAG_BRANCHES = "branches"
TAG_GUIDES = "tip-guides"
TAG_CLADE_BG = "clade-background"
TAG_CLADE_STRIP = "clade-strip"
TAG_CLADE_NAME = "clade-name"
TAG_CUT = "cut-line"


@dataclass
class RenderResult:
    leaf_items: dict[str, list[QGraphicsSimpleTextItem]] = field(default_factory=dict)
    leaf_points: dict[str, QPointF] = field(default_factory=dict)
    node_points: dict[Node, QPointF] = field(default_factory=dict)
    clades: list[ResolvedClade] = field(default_factory=list)


def _fmt_support(values: list[float], index: int) -> str:
    def f(v: float) -> str:
        return f"{v:g}" if v != int(v) or abs(v) >= 1 else f"{v:.2f}"

    if index == SUPPORT_ALL or len(values) == 1:
        return "/".join(f(v) for v in values)
    i = index if -len(values) <= index < len(values) else -1
    return f(values[i])


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


def _qt_deg(theta: float) -> float:
    """Ângulo do layout (rad, horário com y para baixo) -> graus do Qt."""
    return -math.degrees(theta)


def annular_sector(r0: float, r1: float, th0: float, th1: float) -> QPainterPath:
    """Setor de coroa circular entre raios r0<r1 e ângulos th0<th1 (radianos do layout)."""
    path = QPainterPath()
    outer = QRectF(-r1, -r1, 2 * r1, 2 * r1)
    sweep = _qt_deg(th1) - _qt_deg(th0)
    path.arcMoveTo(outer, _qt_deg(th0))
    path.arcTo(outer, _qt_deg(th0), sweep)
    if r0 > 0:
        inner = QRectF(-r0, -r0, 2 * r0, 2 * r0)
        path.arcTo(inner, _qt_deg(th1), -sweep)
    else:
        path.lineTo(0, 0)
    path.closeSubpath()
    return path


class _EdgeBatch:
    """Agrupa segmentos por (cor, espessura) em poucos QGraphicsPathItem."""

    def __init__(self) -> None:
        self.paths: dict[tuple[str, float], QPainterPath] = {}

    def path(self, color: str, width: float) -> QPainterPath:
        return self.paths.setdefault((color, width), QPainterPath())

    def seg(self, color: str, width: float, a: QPointF, b: QPointF) -> None:
        p = self.path(color, width)
        p.moveTo(a)
        p.lineTo(b)

    def arc(self, color: str, width: float, r: float, th0: float, th1: float) -> None:
        if r <= 0:
            return
        p = self.path(color, width)
        rect = QRectF(-r, -r, 2 * r, 2 * r)
        p.arcMoveTo(rect, _qt_deg(th0))
        p.arcTo(rect, _qt_deg(th0), _qt_deg(th1) - _qt_deg(th0))

    def flush(self, scene: QGraphicsScene) -> None:
        for (color, width), path in self.paths.items():
            pen = QPen(QColor(color), width)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setData(1, TAG_BRANCHES)
            scene.addItem(item)


class TreeRenderer:
    def __init__(self, scene: QGraphicsScene) -> None:
        self.scene = scene
        self.geometry: CircGeometry | None = None  # do último desenho circular

    def render(self, tree: Tree, style: RenderStyle, clades: list[Clade] | None = None) -> RenderResult:
        self.scene.clear()
        self.style = style
        font = QFont()
        font.setPointSizeF(style.label.size)
        self._font = font
        self._fm = QFontMetricsF(font)
        self.geometry = None
        res = RenderResult()
        res.clades = resolve_clades(tree, clades or [], style.palette_colors())
        self._assign = assign_nodes(tree, res.clades)
        self._has_clades = bool(self._assign)
        if style.layout == LayoutKind.CIRCULAR:
            self._render_circular(tree, style, res)
        else:
            self._render_rectangular(tree, style, res)
        margin = 30
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-margin, -margin, margin, margin))
        return res

    # ------------------------------------------------------------ cores
    def _clade_of(self, node: Node | None) -> ResolvedClade | None:
        return self._assign.get(node) if node is not None else None

    def _branch_color(self, owner: Node | None) -> str:
        """Cor de um segmento pertencente a ``owner`` (o nó pai do ramo, ou o nó do arco)."""
        cs = self.style.clades
        if self._has_clades and cs.color_branches:
            rc = self._clade_of(owner)
            return rc.color if rc else cs.neutral_color
        return self.style.branch.color

    def _label_color(self, leaf: Node) -> str:
        cs = self.style.clades
        if self._has_clades and cs.color_labels:
            rc = self._clade_of(leaf)
            return rc.color if rc else cs.neutral_color
        return self.style.label.color

    def _visible_clades(self, res: RenderResult) -> list[ResolvedClade]:
        return [rc for rc in res.clades if rc.valid and rc.clade.visible and rc.node is not None]

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

    def _add_path(self, path: QPainterPath, color: str, width: float, tag: str | None = None) -> QGraphicsPathItem:
        pen = QPen(QColor(color), width)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        if tag:
            item.setData(1, tag)
        self.scene.addItem(item)
        return item

    def _fill(self, path: QPainterPath, color: str, alpha: float, tag: str, z: float) -> QGraphicsPathItem:
        c = QColor(color)
        c.setAlphaF(max(0.0, min(alpha, 1.0)))
        item = QGraphicsPathItem(path)
        item.setBrush(QBrush(c))
        item.setPen(QPen(Qt.PenStyle.NoPen))
        item.setZValue(z)
        item.setData(1, tag)
        self.scene.addItem(item)
        return item

    def _cut_pen(self) -> QPen:
        pen = QPen(QColor("#d62728"), 1.0)
        pen.setStyle(Qt.PenStyle.DashLine)
        return pen

    def _support_items(self, tree: Tree, style: RenderStyle, place) -> None:  # type: ignore[no-untyped-def]
        sup = style.support
        if not sup.show:
            return
        small = max(style.label.size * 0.75, 4)
        for node in tree.root.traverse_preorder():
            if node.is_leaf or not node.supports or node is tree.root:
                continue
            if support_value(node.supports, sup.index) < sup.threshold:
                continue
            item = self._text(_fmt_support(node.supports, sup.index), small, "#555555")
            place(node, item)

    # ----------------------------------------------------- rectangular
    def _render_rectangular(self, tree: Tree, style: RenderStyle, res: RenderResult) -> None:
        lay = rectangular_layout(tree, style.use_lengths)
        sx = (style.base_width * style.branch_scale) / lay.max_x if lay.max_x > 0 else 1.0
        sy = style.label.size * style.leaf_spacing
        bw = style.branch.width
        pad = style.label.size * 0.5
        cs = style.clades

        def pt(node: Node) -> QPointF:
            x, y = lay.pos[node]
            return QPointF(x * sx, y * sy)

        edges = _EdgeBatch()
        for node in tree.root.traverse_preorder():
            p = pt(node)
            res.node_points[node] = p
            if node.parent is not None:
                pp = pt(node.parent)
                edges.seg(self._branch_color(node.parent), bw, QPointF(pp.x(), p.y()), p)
            if node.children:
                top, bot = pt(node.children[0]), pt(node.children[-1])
                edges.seg(self._branch_color(node), bw, QPointF(p.x(), top.y()), QPointF(p.x(), bot.y()))
        edges.flush(self.scene)

        tree_right = lay.max_x * sx
        label_right = tree_right
        for leaf in lay.leaf_order:
            p = pt(leaf)
            res.leaf_points[leaf.name] = p
            if not style.label.show:
                continue
            item = self._text(leaf.name, color=self._label_color(leaf))
            h = item.boundingRect().height()
            item.setPos(p.x() + pad, p.y() - h / 2)
            res.leaf_items.setdefault(leaf.name, []).append(item)
            label_right = max(label_right, item.sceneBoundingRect().right())

        visible = self._visible_clades(res)

        def y_range(node: Node) -> tuple[float, float]:
            ys = [lay.pos[l][1] * sy for l in node.leaves()]
            return min(ys) - sy / 2, max(ys) + sy / 2

        x = label_right + pad
        if cs.outer_strip and visible:
            for rc in visible:
                y0, y1 = y_range(rc.node)
                path = QPainterPath()
                path.addRect(QRectF(x, y0, cs.strip_width, y1 - y0))
                self._fill(path, rc.color, 1.0, TAG_CLADE_STRIP, 0)
            x += cs.strip_width + pad
        if cs.background and visible:
            for rc in visible:
                y0, y1 = y_range(rc.node)
                x0 = pt(rc.node).x() - pad / 2
                path = QPainterPath()
                path.addRect(QRectF(x0, y0, x - pad / 2 - x0, y1 - y0))
                self._fill(path, rc.color, cs.background_alpha, TAG_CLADE_BG, -2)
        if cs.show_names and visible:
            for rc in visible:
                y0, y1 = y_range(rc.node)
                bracket = QPainterPath()
                bracket.moveTo(x, y0 + 2)
                bracket.lineTo(x, y1 - 2)
                self._add_path(bracket, rc.color, max(bw, 1.5), TAG_CLADE_NAME)
                t = self._text(rc.clade.name, color=rc.color)
                t.setData(1, TAG_CLADE_NAME)
                t.setPos(x + pad, (y0 + y1) / 2 - t.boundingRect().height() / 2)

        if cs.cut_distance is not None and lay.max_x > 0:
            cx = cs.cut_distance * sx
            line = QPainterPath()
            line.moveTo(cx, -sy)
            line.lineTo(cx, len(lay.leaf_order) * sy)
            item = QGraphicsPathItem(line)
            item.setPen(self._cut_pen())
            item.setData(1, TAG_CUT)
            self.scene.addItem(item)

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
        spacing = style.label.size * style.leaf_spacing
        pad = style.label.size * 0.5
        bw = style.branch.width
        cs = style.clades
        visible = self._visible_clades(res)
        strip = cs.outer_strip and bool(visible)

        # largura máxima dos rótulos (para reservar espaço quando não alinhados)
        max_label_w = 0.0
        if style.label.show:
            max_label_w = max((self._fm.horizontalAdvance(l.name) for l in lay.leaf_order), default=0.0)

        geom = circular_geometry(
            lay,
            font_size=style.label.size,
            leaf_spacing=style.leaf_spacing,
            base_width=style.base_width,
            branch_scale=style.branch_scale,
            align_tips=style.align_tips,
            ring_widths=(cs.strip_width,) if strip else (),
            inner_extent=0.0 if style.align_tips else max_label_w + pad,
        )
        self.geometry = geom
        sr = geom.scale
        n = len(lay.leaf_order)
        half_step = math.pi / n if n else 0.0

        def pt(r_px: float, th: float) -> QPointF:
            return QPointF(r_px * math.cos(th), r_px * math.sin(th))

        def rad(node: Node) -> float:
            return geom.tip_radius(lay, node)

        edges = _EdgeBatch()
        for node in tree.root.traverse_preorder():
            r, th = rad(node), lay.pos[node][1]
            res.node_points[node] = pt(r, th)
            if node.parent is not None:
                edges.seg(self._branch_color(node.parent), bw, pt(rad(node.parent), th), pt(r, th))
            if node.children:
                edges.arc(self._branch_color(node), bw, r,
                          lay.pos[node.children[0]][1], lay.pos[node.children[-1]][1])
        edges.flush(self.scene)

        # linhas-guia: da ponta do ramo até o anel externo
        if geom.align_tips:
            guides = QPainterPath()
            for leaf in lay.leaf_order:
                tip, th = rad(leaf), lay.pos[leaf][1]
                if geom.tip_ring - tip > 0.5:
                    guides.moveTo(pt(tip, th))
                    guides.lineTo(pt(geom.tip_ring, th))
            if not guides.isEmpty():
                pen = QPen(QColor(style.guide.color), max(bw * 0.5, 0.5))
                pen.setStyle(Qt.PenStyle.DotLine)
                item = QGraphicsPathItem(guides)
                item.setPen(pen)
                item.setData(1, TAG_GUIDES)
                self.scene.addItem(item)

        for leaf in lay.leaf_order:
            th = lay.pos[leaf][1]
            res.leaf_points[leaf.name] = pt(geom.leaf_end_radius(lay, leaf), th)
            if not style.label.show:
                continue
            start = geom.label_radius if geom.align_tips else rad(leaf) + pad
            item = self._text(leaf.name, color=self._label_color(leaf))
            self._rotate_radial(item, pt(start, th), th)
            res.leaf_items.setdefault(leaf.name, []).append(item)

        # raio externo ocupado pelos rótulos (ou anéis)
        label_outer = (geom.label_radius if geom.align_tips else geom.tip_ring + pad) + max_label_w
        outer = max(label_outer, geom.rings_end)

        def th_range(node: Node) -> tuple[float, float]:
            ths = [lay.pos[l][1] for l in node.leaves()]
            return min(ths) - half_step, max(ths) + half_step

        if strip:
            for rc in visible:
                th0, th1 = th_range(rc.node)
                self._fill(annular_sector(geom.rings_start, geom.rings_end, th0, th1),
                           rc.color, 1.0, TAG_CLADE_STRIP, 0)
        if cs.background and visible:
            for rc in visible:
                th0, th1 = th_range(rc.node)
                r0 = max(rad(rc.node) - pad / 2, 0.0)
                self._fill(annular_sector(r0, outer + pad / 2, th0, th1),
                           rc.color, cs.background_alpha, TAG_CLADE_BG, -2)
        if cs.show_names and visible:
            r_name = outer + pad * 2
            for rc in visible:
                th0, th1 = th_range(rc.node)
                mid = (th0 + th1) / 2
                if cs.name_mode == "radial":
                    t = self._text(rc.clade.name, color=rc.color)
                    t.setData(1, TAG_CLADE_NAME)
                    self._rotate_radial(t, pt(r_name, mid), mid)
                else:
                    self._curved_text(rc.clade.name, r_name, mid, rc.color)

        if cs.cut_distance is not None and lay.max_r > 0:
            rc_px = cs.cut_distance * sr
            circle = QPainterPath()
            circle.addEllipse(QPointF(0, 0), rc_px, rc_px)
            item = QGraphicsPathItem(circle)
            item.setPen(self._cut_pen())
            item.setData(1, TAG_CUT)
            self.scene.addItem(item)

        def place(node: Node, item: QGraphicsSimpleTextItem) -> None:
            p = pt(rad(node), lay.pos[node][1])
            br = item.boundingRect()
            item.setPos(p.x() - br.width() / 2, p.y() - br.height() / 2)

        self._support_items(tree, style, place)

        if lay.uses_lengths and lay.max_r > 0:
            box = self.scene.itemsBoundingRect()
            self._scale_bar(QPointF(box.left(), box.bottom() + spacing), lay.max_r, sr)

    def _rotate_radial(self, item: QGraphicsSimpleTextItem, anchor: QPointF, th: float) -> None:
        """Texto radial começando em ``anchor``; invertido na metade esquerda para leitura."""
        br = item.boundingRect()
        deg = math.degrees(th) % 360
        if 90 < deg < 270:
            item.setTransformOriginPoint(br.width(), br.height() / 2)
            item.setRotation(deg - 180)
            item.setPos(anchor.x() - br.width(), anchor.y() - br.height() / 2)
        else:
            item.setTransformOriginPoint(0, br.height() / 2)
            item.setRotation(deg)
            item.setPos(anchor.x(), anchor.y() - br.height() / 2)

    def _curved_text(self, text: str, radius: float, mid: float, color: str) -> list[QGraphicsItem]:
        """Texto ao longo do arco, centrado em ``mid``; na metade de baixo segue no sentido
        inverso para não ficar de cabeça para baixo."""
        widths = [self._fm.horizontalAdvance(ch) for ch in text]
        total = sum(widths)
        if radius <= 0 or total == 0:
            return []
        bottom = 0 < (math.degrees(mid) % 360) < 180  # y para baixo: 0–180° é a metade de baixo
        span = total / radius
        direction = -1.0 if bottom else 1.0
        th = mid - direction * span / 2
        items: list[QGraphicsItem] = []
        for ch, w in zip(text, widths):
            center = th + direction * (w / 2) / radius
            item = self._text(ch, color=color)
            item.setData(1, TAG_CLADE_NAME)
            br = item.boundingRect()
            # topo do caractere voltado para fora (em cima) ou para dentro (embaixo)
            rot = math.degrees(center) + (90 if not bottom else -90)
            item.setTransformOriginPoint(br.width() / 2, br.height() / 2)
            item.setRotation(rot)
            p = QPointF(radius * math.cos(center), radius * math.sin(center))  # centro sobre o arco
            item.setPos(p.x() - br.width() / 2, p.y() - br.height() / 2)
            items.append(item)
            th += direction * w / radius
        return items

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
        self._add_path(path, self.style.branch.color, self.style.branch.width)
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
