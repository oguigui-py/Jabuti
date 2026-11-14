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
from jabuti.layout.rectangular import rectangular_layout, visible_nodes
from jabuti.models.clades import Clade, ResolvedClade, assign_nodes, resolve_clades
from jabuti.models.annotations import ContextGene, LeafColumn, context_extent
from jabuti.models.document import TreeEdits, collapsed_nodes
from jabuti.models.label_groups import LabelGroup, LabelGroupSet
from jabuti.models.tree import SUPPORT_ALL, Node, Tree, support_value
from jabuti.style import GuideStyle, LayoutKind, RenderStyle

HIGHLIGHT = QColor("#ffe066")

# marcas em item.data(1) — usadas por testes e pelo export
TAG_BRANCHES = "branches"
TAG_GUIDES = "tip-guides"
TAG_CLADE_BG = "clade-background"
TAG_CLADE_STRIP = "clade-strip"
TAG_CLADE_NAME = "clade-name"
TAG_CUT = "cut-line"
TAG_TIP_SYMBOL = "tip-symbol"
TAG_SUPPORT_SYMBOL = "support-symbol"
TAG_SCALE = "scale-bar"
TAG_COLLAPSED = "collapsed"
TAG_HEATMAP = "heatmap"
TAG_META_STRIP = "metadata-strip"
TAG_COLUMN_HEADER = "column-header"
TAG_CONTEXT = "gene-context"
TAG_LABEL_BG = "label-background"


@dataclass
class RenderResult:
    leaf_items: dict[str, list[QGraphicsSimpleTextItem]] = field(default_factory=dict)
    leaf_points: dict[str, QPointF] = field(default_factory=dict)
    node_points: dict[Node, QPointF] = field(default_factory=dict)
    clades: list[ResolvedClade] = field(default_factory=list)
    label_backgrounds: dict[str, QGraphicsPathItem] = field(default_factory=dict)
    label_groups: dict[str, LabelGroup] = field(default_factory=dict)  # folha -> grupo efetivo


@dataclass
class _LabelSpec:
    """Como desenhar o rótulo de uma folha (fonte, cor, fundo)."""

    font: QFont
    color: str
    width: float                    # largura do texto
    bg: str | None = None
    bg_alpha: float = 1.0
    pad: float = 0.0                # margem interna do fundo (0 sem fundo)
    radius: float = 0.0

    @property
    def extent(self) -> float:
        """Largura ocupada, incluindo o fundo."""
        return self.width + 2 * self.pad


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


def guide_pen(guide: GuideStyle) -> QPen | None:
    """Caneta da linha de ligação folha→anel; ``None`` para "nenhuma"."""
    if guide.kind == "none":
        return None
    color = QColor(guide.color)
    color.setAlphaF(max(0.0, min(guide.opacity, 1.0)))
    width = max(guide.width, 0.1)
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    if guide.kind == "dash":
        pen.setDashPattern([5.0, 3.0])
    elif guide.kind == "dots":
        pen.setDashPattern([1.0, 2.0])
    elif guide.kind == "bigdots":
        # pontos redondos: traço quase nulo + cap redondo, caneta mais grossa
        pen.setWidthF(max(width * 2.5, 1.5))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setDashPattern([0.01, 2.2])
    return pen


def cap_style(cap: str) -> Qt.PenCapStyle:
    return Qt.PenCapStyle.RoundCap if cap == "round" else Qt.PenCapStyle.FlatCap


class _EdgeBatch:
    """Agrupa segmentos por (cor, espessura) em poucos QGraphicsPathItem."""

    def __init__(self, cap: str = "flat") -> None:
        self.paths: dict[tuple[str, float], QPainterPath] = {}
        self.cap = cap_style(cap)

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
            pen.setCapStyle(self.cap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin if self.cap == Qt.PenCapStyle.RoundCap
                             else Qt.PenJoinStyle.MiterJoin)
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setData(1, TAG_BRANCHES)
            scene.addItem(item)


class TreeRenderer:
    def __init__(self, scene: QGraphicsScene) -> None:
        self.scene = scene
        self.geometry: CircGeometry | None = None  # do último desenho circular

    def render(
        self,
        tree: Tree,
        style: RenderStyle,
        clades: list[Clade] | None = None,
        collapsed: list[frozenset[str]] | None = None,
        columns: list[LeafColumn] | None = None,
        meta_colors: dict[str, str] | None = None,
        context: dict[str, list[ContextGene]] | None = None,
        label_groups: LabelGroupSet | None = None,
    ) -> RenderResult:
        self.scene.clear()
        self._context = context or {}
        self._columns = list(columns or [])
        self._meta_node = self._propagate_meta(tree, meta_colors or {})
        self.style = style
        bg = style.background
        self.scene.setBackgroundBrush(QBrush(QColor(bg)) if bg else QBrush(Qt.BrushStyle.NoBrush))
        self._collapsed = collapsed_nodes(tree, TreeEdits(collapsed=list(collapsed or [])))
        self._visible = set(visible_nodes(tree, self._collapsed))
        lab = style.label
        font = QFont(lab.family) if lab.family else QFont()
        font.setPointSizeF(lab.size)
        self._font = font
        self._fm = QFontMetricsF(font)
        leaf_font = QFont(font)
        leaf_font.setBold(lab.bold)
        leaf_font.setItalic(lab.italic)
        self._leaf_font = leaf_font
        self._leaf_fm = QFontMetricsF(leaf_font)
        sym = style.symbols
        self._marker = sym.size if sym.shape != "none" else 0.0
        self.geometry = None
        res = RenderResult()
        self._groups = label_groups.effective(tree.leaf_names()) if label_groups is not None else {}
        res.label_groups = dict(self._groups)
        res.clades = resolve_clades(tree, clades or [], style.palette_colors())
        self._assign = assign_nodes(tree, res.clades)
        self._has_clades = bool(self._assign)
        self._prepare_widths(tree)
        self._collapsed_names = {
            id(rc.node): rc.clade.name for rc in res.clades if rc.valid and rc.node in self._collapsed
        }
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

    @staticmethod
    def _propagate_meta(tree: Tree, leaf_colors: dict[str, str]) -> dict[Node, str]:
        """Cor de metadado por nó: a da folha, ou a comum a todos os descendentes."""
        out: dict[Node, str] = {}
        if not leaf_colors:
            return out
        for node in tree.root.traverse_postorder():
            if node.is_leaf:
                if node.name in leaf_colors:
                    out[node] = leaf_colors[node.name]
            else:
                kids = [out.get(c) for c in node.children]
                if kids and kids[0] is not None and all(k == kids[0] for k in kids):
                    out[node] = kids[0]
        return out

    def _edge_color(self, node: Node) -> str:
        """Ramo que termina em ``node``: metadado do próprio nó (se ativo) ou regra dos clados."""
        md = self.style.metadata
        if md.color_branches and node in self._meta_node:
            return self._meta_node[node]
        return self._branch_color(node.parent)

    def _node_color(self, node: Node) -> str:
        """Conector/arco que sai de ``node``."""
        md = self.style.metadata
        if md.color_branches and node in self._meta_node:
            return self._meta_node[node]
        return self._branch_color(node)

    def _branch_color(self, owner: Node | None) -> str:
        """Cor de um segmento pertencente a ``owner`` (o nó pai do ramo, ou o nó do arco)."""
        cs = self.style.clades
        if self._has_clades and cs.color_branches:
            rc = self._clade_of(owner)
            return rc.color if rc else cs.neutral_color
        return self.style.branch.color

    def _label_color(self, leaf: Node) -> str:
        md = self.style.metadata
        if md.color_labels and leaf in self._meta_node:
            return self._meta_node[leaf]
        cs = self.style.clades
        if self._has_clades and cs.color_labels:
            rc = self._clade_of(leaf)
            return rc.color if rc else cs.neutral_color
        return self.style.label.color

    def _label_spec(self, leaf: Node) -> _LabelSpec:
        """Grupo de rótulo > metadados > clado > padrão (campos vazios do grupo herdam)."""
        g = self._groups.get(leaf.name)
        look = g.look if g is not None else None
        font, fm = self._leaf_font, self._leaf_fm
        if look is not None and (look.bold is not None or look.italic is not None or look.size_scale != 1.0):
            font = QFont(self._leaf_font)
            if look.bold is not None:
                font.setBold(look.bold)
            if look.italic is not None:
                font.setItalic(look.italic)
            font.setPointSizeF(max(self.style.label.size * look.size_scale, 1.0))
            fm = QFontMetricsF(font)
        color = look.text_color if look is not None and look.text_color else self._label_color(leaf)
        spec = _LabelSpec(font, color, fm.horizontalAdvance(leaf.name))
        cs = self.style.clades
        if look is not None and look.background:
            spec.bg, spec.bg_alpha = look.background, look.background_alpha
        elif cs.label_background and self._has_clades:
            rc = self._clade_of(leaf)
            if rc is not None:
                spec.bg, spec.bg_alpha = rc.color, cs.label_background_alpha
        if spec.bg:
            spec.pad = look.padding if look is not None else 2.0
            spec.radius = look.radius if look is not None else 3.0
        return spec

    def _leaf_text(self, leaf: Node, spec: _LabelSpec) -> QGraphicsSimpleTextItem:
        item = QGraphicsSimpleTextItem(leaf.name)
        item.setFont(spec.font)
        item.setBrush(QBrush(QColor(spec.color)))
        self.scene.addItem(item)
        return item

    def _label_background(self, leaf: Node, item: QGraphicsSimpleTextItem, spec: _LabelSpec,
                          max_h: float, res: RenderResult) -> QGraphicsPathItem | None:
        """Fundo (marca-texto) atrás de um rótulo já posicionado: mesma origem de
        transformação, rotação e posição do texto, então gira junto no circular.
        A altura fica limitada a ``max_h`` para não invadir as folhas vizinhas."""
        if not spec.bg:
            return None
        br = item.boundingRect()
        h = br.height()
        full = h + 2 * spec.pad
        height = min(full, max_h) if max_h > 0 else full
        rect = QRectF(-spec.pad, h / 2 - height / 2, br.width() + 2 * spec.pad, height)
        r = max(min(spec.radius, height / 2, rect.width() / 2), 0.0)
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)
        bg = QGraphicsPathItem(path)
        c = QColor(spec.bg)
        c.setAlphaF(max(0.0, min(spec.bg_alpha, 1.0)))
        bg.setBrush(QBrush(c))
        bg.setPen(QPen(Qt.PenStyle.NoPen))
        bg.setTransformOriginPoint(item.transformOriginPoint())
        bg.setRotation(item.rotation())
        bg.setPos(item.pos())
        bg.setZValue(-1)
        bg.setData(1, TAG_LABEL_BG)
        bg.setData(2, leaf.name)
        self.scene.addItem(bg)
        res.label_backgrounds[leaf.name] = bg
        return bg

    def _prepare_widths(self, tree: Tree) -> None:
        b = self.style.branch
        self._width_by_support = b.width_by_support and tree.max_support_values() > 0
        idx = self.style.support.index
        vals = [support_value(n.supports, idx) for n in tree.root.traverse_preorder() if n.supports]
        self._support_max = max(vals, default=0.0) or 1.0

    def _width(self, node: Node | None) -> float:
        """Espessura do ramo que termina em ``node`` (e do conector/arco que sai dele)."""
        b = self.style.branch
        if not self._width_by_support:
            return b.width
        if node is None or not node.supports:
            return b.min_width
        frac = max(0.0, min(support_value(node.supports, self.style.support.index) / self._support_max, 1.0))
        return round(b.min_width + (b.max_width - b.min_width) * frac, 2)

    def _visible_clades(self, res: RenderResult) -> list[ResolvedClade]:
        return [rc for rc in res.clades
                if rc.valid and rc.clade.visible and rc.node is not None and rc.node in self._visible]

    def _tips(self, lay) -> list[tuple[Node, list[str]]]:  # type: ignore[no-untyped-def]
        """Pontas visíveis: folhas e clados colapsados (com as folhas que representam)."""
        tips = [(l, [l.name]) for l in lay.leaf_order]
        tips += [(n, [l.name for l in n.leaves()]) for n in lay.collapsed]
        return tips

    def _cell_color(self, col: LeafColumn, names: list[str]) -> str:
        return col.color_for(names[0]) if len(names) == 1 else col.color_for_group(names)

    def _flush_cells(self, by_color: dict[str, QPainterPath], col: LeafColumn) -> None:
        hm = self.style.heatmap
        pen = QPen(QColor("#bfbfbf"), 0.5) if hm.borders else QPen(Qt.PenStyle.NoPen)
        for color, path in by_color.items():
            item = QGraphicsPathItem(path)
            item.setBrush(QBrush(QColor(color)))
            item.setPen(pen)
            item.setData(1, TAG_HEATMAP if col.kind == "genes" else TAG_META_STRIP)
            item.setData(2, col.key)
            self.scene.addItem(item)

    def _cell_text(self, text: str, center: QPointF, bg: str) -> None:
        c = QColor(bg)
        lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        t = self._text(text, max(self.style.label.size * 0.7, 4), "#ffffff" if lum < 140 else "#202020")
        t.setData(1, TAG_HEATMAP)
        br = t.boundingRect()
        t.setPos(center.x() - br.width() / 2, center.y() - br.height() / 2)

    def _draw_context(self, lay, x0: float, sy: float, pad: float) -> float:  # type: ignore[no-untyped-def]
        """Setas dos genes vizinhos por folha (retangular). Devolve o x final."""
        cst = self.style.context
        extent = context_extent(self._context) or 1.0
        half = cst.width / 2
        scale = half / extent
        cx = x0 + half
        h = sy * cst.arrow_height
        base_pen = QPen(QColor("#9a9a9a"), 0.6)
        outline = QPen(QColor("#555555"), 0.5)
        # nome dentro da seta (nunca invade a linha vizinha); fonte pela altura da seta
        inner = QFont(self._font)
        inner.setPointSizeF(max(min(h * 0.55, self.style.label.size * 0.75), 3.5))
        inner_fm = QFontMetricsF(inner)
        for leaf in lay.leaf_order:
            track = self._context.get(leaf.name)
            if not track:
                continue
            y = lay.pos[leaf][1] * sy
            line = QPainterPath()
            line.moveTo(cx + track[0].start * scale, y)
            line.lineTo(cx + track[-1].end * scale, y)
            self._add_path(line, "#9a9a9a", 0.6, TAG_CONTEXT).setPen(base_pen)
            for g in track:
                a, b = cx + g.start * scale, cx + g.end * scale
                w = b - a
                head = min(w * 0.45, h * 0.9)
                path = QPainterPath()
                if g.forward:
                    path.moveTo(a, y - h * 0.3)
                    path.lineTo(b - head, y - h * 0.3)
                    path.lineTo(b - head, y - h / 2)
                    path.lineTo(b, y)
                    path.lineTo(b - head, y + h / 2)
                    path.lineTo(b - head, y + h * 0.3)
                    path.lineTo(a, y + h * 0.3)
                else:
                    path.moveTo(b, y - h * 0.3)
                    path.lineTo(a + head, y - h * 0.3)
                    path.lineTo(a + head, y - h / 2)
                    path.lineTo(a, y)
                    path.lineTo(a + head, y + h / 2)
                    path.lineTo(a + head, y + h * 0.3)
                    path.lineTo(b, y + h * 0.3)
                path.closeSubpath()
                item = QGraphicsPathItem(path)
                item.setBrush(QBrush(QColor(g.color)))
                pen = QPen(QColor("#202020"), 1.2) if g.is_anchor else outline
                item.setPen(pen)
                item.setData(1, TAG_CONTEXT)
                item.setData(2, g.label)
                self.scene.addItem(item)
                body = w - head  # parte retangular da seta
                if cst.show_labels and g.label and inner_fm.horizontalAdvance(g.label) <= body - 2:
                    c = QColor(g.color)
                    lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
                    t = QGraphicsSimpleTextItem(g.label)
                    t.setFont(inner)
                    t.setBrush(QBrush(QColor("#ffffff" if lum < 140 else "#202020")))
                    t.setData(1, TAG_CONTEXT)
                    br = t.boundingRect()
                    body_mid = (a + b - head) / 2 if g.forward else (a + head + b) / 2
                    t.setPos(body_mid - br.width() / 2, y - br.height() / 2)
                    t.setZValue(1)
                    self.scene.addItem(t)
        return x0 + cst.width

    def _collapsed_label(self, node: Node) -> str:
        n = len(node.leaves())
        name = self._collapsed_names.get(id(node))
        return f"{name} ({n})" if name else f"{n} folhas"

    def _collapsed_triangle(self, path: QPainterPath, node: Node) -> None:
        color = self._branch_color(node)
        c = QColor(color)
        c.setAlphaF(0.35)
        item = QGraphicsPathItem(path)
        item.setBrush(QBrush(c))
        pen = QPen(QColor(color), self._width(node))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        item.setPen(pen)
        item.setData(1, TAG_COLLAPSED)
        self.scene.addItem(item)

    # ----------------------------------------------------------- helpers
    def _text(self, text: str, size: float | None = None, color: str = "#202020",
              leaf: bool = False) -> QGraphicsSimpleTextItem:
        item = QGraphicsSimpleTextItem(text)
        f = QFont(self._leaf_font if leaf else self._font)
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

    def _support_items(self, tree: Tree, style: RenderStyle, place, point) -> None:  # type: ignore[no-untyped-def]
        """Suporte como números (``place`` posiciona o texto) ou símbolos (em ``point(node)``)."""
        sup = style.support
        if sup.mode == "none":
            return
        nodes = [n for n in tree.root.traverse_preorder()
                 if not n.is_leaf and n.supports and n is not tree.root and n in self._visible]
        if sup.mode == "numbers":
            small = max(style.label.size * 0.75, 4)
            for node in nodes:
                if support_value(node.supports, sup.index) < sup.threshold:
                    continue
                place(node, self._text(_fmt_support(node.supports, sup.index), small, sup.color))
            return
        vmax = max((support_value(n.supports, sup.index) for n in nodes), default=0.0) or 1.0
        filled, hollow = QPainterPath(), QPainterPath()
        for node in nodes:
            v = support_value(node.supports, sup.index)
            d = sup.symbol_size
            if sup.size_by_value:
                d *= 0.35 + 0.65 * max(0.0, min(v / vmax, 1.0))
            (filled if v >= sup.threshold else hollow).addEllipse(point(node), d / 2, d / 2)
        pen = QPen(QColor(sup.color), max(sup.symbol_size * 0.15, 0.6))
        for path, brush in ((filled, QBrush(QColor(sup.color))), (hollow, QBrush(QColor("white")))):
            if path.isEmpty():
                continue
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setBrush(brush)
            item.setZValue(2)
            item.setData(1, TAG_SUPPORT_SYMBOL)
            self.scene.addItem(item)

    def _tip_symbols(self, leaves: list[Node], point) -> None:  # type: ignore[no-untyped-def]
        sym = self.style.symbols
        if sym.shape == "none":
            return
        by_color: dict[str, QPainterPath] = {}
        r = sym.size / 2
        for leaf in leaves:
            color = sym.color
            if sym.use_clade_color:
                rc = self._clade_of(leaf)
                if rc is not None:
                    color = rc.color
            path = by_color.setdefault(color, QPainterPath())
            c = point(leaf)
            if sym.shape == "circle":
                path.addEllipse(c, r, r)
            elif sym.shape == "square":
                path.addRect(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))
            else:  # losango
                path.moveTo(c.x(), c.y() - r)
                path.lineTo(c.x() + r, c.y())
                path.lineTo(c.x(), c.y() + r)
                path.lineTo(c.x() - r, c.y())
                path.closeSubpath()
        for color, path in by_color.items():
            item = QGraphicsPathItem(path)
            item.setBrush(QBrush(QColor(color)))
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setZValue(2)
            item.setData(1, TAG_TIP_SYMBOL)
            self.scene.addItem(item)

    # ----------------------------------------------------- rectangular
    def _render_rectangular(self, tree: Tree, style: RenderStyle, res: RenderResult) -> None:
        lay = rectangular_layout(tree, style.use_lengths, self._collapsed)
        sx = (style.base_width * style.branch_scale) / lay.max_x if lay.max_x > 0 else 1.0
        sy = style.label.size * style.leaf_spacing
        bw = style.branch.width
        pad = style.label.size * 0.5
        cs = style.clades

        def pt(node: Node) -> QPointF:
            x, y = lay.pos[node]
            return QPointF(x * sx, y * sy)

        edges = _EdgeBatch(style.branch.cap)
        for node in visible_nodes(tree, self._collapsed):
            p = pt(node)
            res.node_points[node] = p
            if node.parent is not None:
                pp = pt(node.parent)
                edges.seg(self._edge_color(node), self._width(node), QPointF(pp.x(), p.y()), p)
            if node in self._collapsed:
                continue
            if node.children:
                top, bot = pt(node.children[0]), pt(node.children[-1])
                edges.seg(self._node_color(node), self._width(node), QPointF(p.x(), top.y()), QPointF(p.x(), bot.y()))
        edges.flush(self.scene)

        tree_right = lay.max_x * sx
        label_right = tree_right
        for node, far in lay.collapsed.items():
            p = pt(node)
            y0, y1 = lay.span[node][0] * sy + sy * 0.15, lay.span[node][1] * sy - sy * 0.15
            tri = QPainterPath()
            tri.moveTo(p)
            tri.lineTo(far * sx, y0)
            tri.lineTo(far * sx, y1)
            tri.closeSubpath()
            self._collapsed_triangle(tri, node)
            if style.label.show:
                t = self._text(self._collapsed_label(node), color=self._branch_color(node))
                t.setData(1, TAG_COLLAPSED)
                t.setPos(far * sx + pad, p.y() - t.boundingRect().height() / 2)
                label_right = max(label_right, t.sceneBoundingRect().right())
        for leaf in lay.leaf_order:
            p = pt(leaf)
            res.leaf_points[leaf.name] = p
            if not style.label.show:
                continue
            spec = self._label_spec(leaf)
            item = self._leaf_text(leaf, spec)
            h = item.boundingRect().height()
            item.setPos(p.x() + pad + self._marker / 2 + spec.pad, p.y() - h / 2)
            res.leaf_items.setdefault(leaf.name, []).append(item)
            label_right = max(label_right, item.sceneBoundingRect().right())
            bg = self._label_background(leaf, item, spec, sy - 1, res)
            if bg is not None:
                label_right = max(label_right, bg.sceneBoundingRect().right())

        visible = self._visible_clades(res)

        def y_range(node: Node) -> tuple[float, float]:
            a, b = lay.span[node]
            return a * sy, b * sy

        x = label_right + pad
        if cs.outer_strip and visible:
            for rc in visible:
                y0, y1 = y_range(rc.node)
                path = QPainterPath()
                path.addRect(QRectF(x, y0, cs.strip_width, y1 - y0))
                self._fill(path, rc.color, 1.0, TAG_CLADE_STRIP, 0)
            x += cs.strip_width + pad
        if self._columns:
            hm = style.heatmap
            top = lay.span[tree.root][0] * sy
            for col in self._columns:
                cw = col.width if col.width else sy * hm.cell_width
                by_color: dict[str, QPainterPath] = {}
                for node, names in self._tips(lay):
                    a, b = lay.span[node]
                    color = self._cell_color(col, names)
                    rect = QRectF(x, a * sy, cw, (b - a) * sy)
                    by_color.setdefault(color, QPainterPath()).addRect(rect)
                    if len(names) == 1 and names[0] in col.texts:
                        self._cell_text(col.texts[names[0]], rect.center(), color)
                self._flush_cells(by_color, col)
                if hm.show_headers:
                    size = max(style.label.size * 0.85, 4)
                    h = self._text(col.header, size)
                    h.setData(1, TAG_COLUMN_HEADER)
                    hh = h.boundingRect().height()
                    while hh > cw and size > 4:  # coluna estreita: fonte menor até caber
                        size = max(size * min(cw / hh, 0.92), 4)
                        f = h.font()
                        f.setPointSizeF(size)
                        h.setFont(f)
                        hh = h.boundingRect().height()
                    # vertical (lido de baixo para cima), centrado na coluna: não se sobrepõe
                    # mesmo com colunas estreitas
                    h.setTransformOriginPoint(0, hh)
                    h.setRotation(-90)
                    h.setPos(x + cw / 2 + hh / 2, top - 3 - hh)
                x += cw
            x += pad
        if self._context:
            x = self._draw_context(lay, x, sy, pad) + pad
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
            line.lineTo(cx, lay.n_slots * sy)
            item = QGraphicsPathItem(line)
            item.setPen(self._cut_pen())
            item.setData(1, TAG_CUT)
            self.scene.addItem(item)

        def place(node: Node, item: QGraphicsSimpleTextItem) -> None:
            p = pt(node)
            r = item.boundingRect()
            item.setPos(p.x() - r.width() - 2, p.y() - r.height())

        self._tip_symbols(lay.leaf_order, pt)
        self._support_items(tree, style, place, pt)

        if lay.uses_lengths and lay.max_x > 0:
            self._scale_bar(lay.max_x, sx, sy)

    # -------------------------------------------------------- circular
    def _render_circular(self, tree: Tree, style: RenderStyle, res: RenderResult) -> None:
        lay = circular_layout(tree, style.use_lengths, collapsed=self._collapsed)
        spacing = style.label.size * style.leaf_spacing
        pad = style.label.size * 0.5
        cs = style.clades
        visible = self._visible_clades(res)
        strip = cs.outer_strip and bool(visible)
        col_w = spacing * style.heatmap.cell_width
        ring_widths = ([cs.strip_width] if strip else []) + [c.width or col_w for c in self._columns]

        # largura máxima dos rótulos (para reservar espaço quando não alinhados)
        max_label_w = 0.0
        specs: dict[Node, _LabelSpec] = {}
        if style.label.show:
            specs = {l: self._label_spec(l) for l in lay.leaf_order}
            max_label_w = max((sp.extent for sp in specs.values()), default=0.0)
            max_label_w = max([max_label_w, *(self._fm.horizontalAdvance(self._collapsed_label(n))
                                                for n in lay.collapsed)])

        geom = circular_geometry(
            lay,
            font_size=style.label.size,
            leaf_spacing=style.leaf_spacing,
            base_width=style.base_width,
            branch_scale=style.branch_scale,
            align_tips=style.align_tips,
            ring_widths=tuple(ring_widths),
            inner_extent=0.0 if style.align_tips else max_label_w + pad,
            marker=self._marker,
        )
        self.geometry = geom
        sr = geom.scale

        def pt(r_px: float, th: float) -> QPointF:
            return QPointF(r_px * math.cos(th), r_px * math.sin(th))

        def rad(node: Node) -> float:
            return geom.tip_radius(lay, node)

        edges = _EdgeBatch(style.branch.cap)
        for node in visible_nodes(tree, self._collapsed):
            r, th = rad(node), lay.pos[node][1]
            res.node_points[node] = pt(r, th)
            if node.parent is not None:
                edges.seg(self._edge_color(node), self._width(node), pt(rad(node.parent), th), pt(r, th))
            if node in self._collapsed:
                continue
            if node.children:
                edges.arc(self._node_color(node), self._width(node), r,
                          lay.pos[node.children[0]][1], lay.pos[node.children[-1]][1])
        edges.flush(self.scene)

        # clados colapsados: triângulo do nó até a folha mais distante
        tri_tips: list[tuple[float, float]] = []  # (raio final, ângulo) para ligações e rótulos
        for node, far in lay.collapsed.items():
            a, b = lay.span[node]
            inset = (b - a) * 0.08
            r_far = far * sr
            tri = QPainterPath()
            tri.moveTo(pt(rad(node), lay.pos[node][1]))
            tri.lineTo(pt(r_far, a + inset))
            rect = QRectF(-r_far, -r_far, 2 * r_far, 2 * r_far)
            tri.arcTo(rect, _qt_deg(a + inset), _qt_deg(b - inset) - _qt_deg(a + inset))
            tri.closeSubpath()
            self._collapsed_triangle(tri, node)
            tri_tips.append((r_far, lay.pos[node][1]))

        # linhas-guia: da ponta do ramo até o anel externo
        gpen = guide_pen(style.guide)
        if geom.align_tips and gpen is not None:
            guides = QPainterPath()
            ends = [(rad(leaf), lay.pos[leaf][1]) for leaf in lay.leaf_order] + tri_tips
            for tip, th in ends:
                if geom.tip_ring - tip > 0.5:
                    guides.moveTo(pt(tip, th))
                    guides.lineTo(pt(geom.tip_ring, th))
            if not guides.isEmpty():
                item = QGraphicsPathItem(guides)
                item.setPen(gpen)
                item.setData(1, TAG_GUIDES)
                self.scene.addItem(item)

        for leaf in lay.leaf_order:
            th = lay.pos[leaf][1]
            res.leaf_points[leaf.name] = pt(geom.leaf_end_radius(lay, leaf), th)
            if not style.label.show:
                continue
            start = geom.label_radius if geom.align_tips else rad(leaf) + self._marker / 2 + pad
            spec = specs[leaf]
            item = self._leaf_text(leaf, spec)
            self._rotate_radial(item, pt(start + spec.pad, th), th)
            res.leaf_items.setdefault(leaf.name, []).append(item)
            if spec.bg:
                # corda entre folhas vizinhas na borda interna do fundo
                a, b = lay.span[leaf]
                chord = 2 * start * math.sin(max(b - a, 0.0) / 2)
                self._label_background(leaf, item, spec, max(chord - 1, 2.0), res)

        if style.label.show:
            for node, far in lay.collapsed.items():
                th = lay.pos[node][1]
                start = geom.label_radius if geom.align_tips else far * sr + pad
                t = self._text(self._collapsed_label(node), color=self._branch_color(node))
                t.setData(1, TAG_COLLAPSED)
                self._rotate_radial(t, pt(start, th), th)

        # raio externo ocupado pelos rótulos (ou anéis)
        label_outer = (geom.label_radius if geom.align_tips
                       else geom.tip_ring + self._marker / 2 + pad) + max_label_w
        outer = max(label_outer, geom.rings_end)

        def th_range(node: Node) -> tuple[float, float]:
            return lay.span[node]

        if strip:
            r0, r1 = geom.ring_bounds(0)
            for rc in visible:
                th0, th1 = th_range(rc.node)
                self._fill(annular_sector(r0, r1, th0, th1), rc.color, 1.0, TAG_CLADE_STRIP, 0)
        first_col_ring = 1 if strip else 0
        for i, col in enumerate(self._columns):
            r0, r1 = geom.ring_bounds(first_col_ring + i)
            by_color: dict[str, QPainterPath] = {}
            for node, names in self._tips(lay):
                a, b = lay.span[node]
                color = self._cell_color(col, names)
                by_color.setdefault(color, QPainterPath()).addPath(annular_sector(r0, r1, a, b))
                if len(names) == 1 and names[0] in col.texts:
                    mid = (a + b) / 2
                    self._cell_text(col.texts[names[0]], pt((r0 + r1) / 2, mid), color)
            self._flush_cells(by_color, col)
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

        self._tip_symbols(lay.leaf_order,
                          lambda leaf: pt(geom.leaf_end_radius(lay, leaf), lay.pos[leaf][1]))
        self._support_items(tree, style, place, lambda node: pt(rad(node), lay.pos[node][1]))

        if lay.uses_lengths and lay.max_r > 0:
            self._scale_bar(lay.max_r, sr, spacing)

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
    def _scale_bar(self, max_len: float, px_per_unit: float, gap: float) -> None:
        """Barra de escala num canto do desenho (posição/comprimento do estilo)."""
        sb = self.style.scale_bar
        if not sb.show:
            return
        val = sb.length if sb.length and sb.length > 0 else _nice_scale(max_len)
        if val <= 0:
            return
        box = self.scene.itemsBoundingRect()
        w = val * px_per_unit
        tick = 4.0
        label = self._text(f"{val:g}", max(self._font.pointSizeF() * 0.8, 4), self.style.branch.color)
        label.setData(1, TAG_SCALE)
        lh = label.boundingRect().height()
        left = "left" in sb.position
        top = sb.position.startswith("top")
        x0 = box.left() if left else box.right() - w
        y = box.top() - gap - lh - tick if top else box.bottom() + gap
        path = QPainterPath()
        path.moveTo(x0, y)
        path.lineTo(x0 + w, y)
        for x in (x0, x0 + w):
            path.moveTo(x, y - tick)
            path.lineTo(x, y + tick)
        self._add_path(path, self.style.branch.color, self.style.branch.width, TAG_SCALE)
        label.setPos(x0 + w / 2 - label.boundingRect().width() / 2, y + tick + 1)


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
