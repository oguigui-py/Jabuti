"""Monta os itens da QGraphicsScene a partir do layout, do estilo e dos clados."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainterPath, QPen
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
from jabuti.models.annotations import ContextGene, LeafColumn, LegendGroup, context_extent
from jabuti.models.document import TreeEdits, collapsed_nodes
from jabuti.models.label_groups import LabelGroup, LabelGroupSet
from jabuti.models.tracks import CLADE_STRIP, BarTrack, StackedTrack, fmt_value
from jabuti.views.background_blocks import SEAM_OVERLAP, blocks
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
TAG_LEGEND = "legend"
TAG_BAR = "bar"
TAG_BAR_MISSING = "bar-missing"
TAG_BAR_REF = "bar-reference"
TAG_BAR_AXIS = "bar-axis"
TAG_BAR_VALUE = "bar-value"
TAG_STACKED = "stacked-bar"
TAG_MATRIX = "matrix"
TAG_BREAK = "branch-break"
TAG_ROW_HIGHLIGHT = "row-highlight"
TAG_SUPPORT_LEVEL = "support-level"


@dataclass
class RenderResult:
    leaf_items: dict[str, list[QGraphicsSimpleTextItem]] = field(default_factory=dict)
    leaf_points: dict[str, QPointF] = field(default_factory=dict)
    node_points: dict[Node, QPointF] = field(default_factory=dict)
    clades: list[ResolvedClade] = field(default_factory=list)
    label_backgrounds: dict[str, QGraphicsPathItem] = field(default_factory=dict)
    label_groups: dict[str, LabelGroup] = field(default_factory=dict)  # folha -> grupo efetivo
    notes: list[str] = field(default_factory=list)                      # avisos para a barra de status
    display: dict[str, str] = field(default_factory=dict)               # nome original -> exibido
    shared_backgrounds: set[str] = field(default_factory=set)           # folhas cujo fundo é um bloco


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
        self.notes: list[str] = []

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
        legend: list[LegendGroup] | None = None,
        hidden: set[str] | frozenset[str] = frozenset(),
        names: dict[str, str] | None = None,
        highlights: list | None = None,
    ) -> RenderResult:
        self.scene.clear()
        self.notes: list[str] = []
        self._context = context or {}
        tracks = list(columns or [])
        if CLADE_STRIP not in tracks and style.clades.outer_strip:
            tracks.insert(0, CLADE_STRIP)       # padrão: faixa de clados logo após os rótulos
        if not style.clades.outer_strip:
            tracks = [t for t in tracks if t != CLADE_STRIP]
        self._tracks = tracks
        self._columns = [t for t in tracks if isinstance(t, LeafColumn)]
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
        self._merge = getattr(style, "merge_backgrounds", True)
        self._names = dict(names or {})
        self._highlights = list(highlights or [])
        res.display = dict(self._names)
        self._groups = label_groups.effective(tree.leaf_names()) if label_groups is not None else {}
        res.label_groups = dict(self._groups)
        res.clades = resolve_clades(tree, clades or [], style.palette_colors(), hidden)
        self._assign = assign_nodes(tree, res.clades)
        self._has_clades = bool(self._assign)
        self._prepare_widths(tree)
        self._collapsed_names = {
            id(rc.node): rc.clade.name for rc in res.clades if rc.valid and rc.node in self._collapsed
        }
        layout = LayoutKind(style.layout)
        if layout.is_radial:
            self._render_circular(tree, style, res)
        elif layout == LayoutKind.UNROOTED:
            self._render_unrooted(tree, style, res)
        else:
            self._render_rectangular(tree, style, res)
        if style.legend.in_figure:
            clade_entries = [(rc.clade.name, rc.color) for rc in res.clades if rc.valid and rc.clade.visible]
            sections = ([LegendGroup("Clados", clade_entries)] if clade_entries else [])
            sections += [g for g in (legend or []) if not g.is_empty()]
            self._draw_legend(sections)
        margin = 30
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-margin, -margin, margin, margin))
        res.notes = list(self.notes)
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
        spec = _LabelSpec(font, color, fm.horizontalAdvance(self._shown(leaf)))
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

    def _shown(self, leaf: Node) -> str:
        """Nome exibido (regras/tabela de nomes); o original identifica a folha."""
        return self._names.get(leaf.name, leaf.name)

    def _leaf_text(self, leaf: Node, spec: _LabelSpec) -> QGraphicsSimpleTextItem:
        item = QGraphicsSimpleTextItem(self._shown(leaf))
        item.setData(3, leaf.name)
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
            item.setData(1, {"genes": TAG_HEATMAP, "matrix": TAG_MATRIX}.get(col.kind, TAG_META_STRIP))
            item.setData(2, col.key)
            self.scene.addItem(item)

    def _cell_text(self, text: str, center: QPointF, bg: str) -> None:
        c = QColor(bg)
        lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        t = self._text(text, max(self.style.label.size * 0.7, 4), "#ffffff" if lum < 140 else "#202020")
        t.setData(1, TAG_HEATMAP)
        t.setZValue(1)            # por cima das células (desenhadas depois)
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

    # ------------------------------------------------- fundos vizinhos unidos
    @staticmethod
    def _tip_order(lay) -> list:  # type: ignore[no-untyped-def]
        """Folhas e clados colapsados na ordem desenhada (pela posição)."""
        return sorted([*lay.leaf_order, *lay.collapsed], key=lambda n: lay.span[n][0])

    @staticmethod
    def _touching(lay):  # type: ignore[no-untyped-def]
        return lambda a, b: abs(lay.span[a][1] - lay.span[b][0]) < 1e-9

    @staticmethod
    def _side(i: int, n: int, neighbor: bool, first: bool) -> str:
        """Tipo da borda da i-ésima ponta do bloco: "inner", "neighbor" ou "outer"."""
        if (i > 0) if first else (i < n - 1):
            return "inner"
        return "neighbor" if neighbor else "outer"

    def _block_item(self, path: QPainterPath, spec: _LabelSpec, names: list[str], res: RenderResult) -> None:
        bg = QGraphicsPathItem(path)
        c = QColor(spec.bg)
        c.setAlphaF(max(0.0, min(spec.bg_alpha, 1.0)))
        bg.setBrush(QBrush(c))
        bg.setPen(QPen(Qt.PenStyle.NoPen))
        bg.setZValue(-1)
        bg.setData(1, TAG_LABEL_BG)
        bg.setData(2, names[0])
        bg.setData(4, list(names))
        self.scene.addItem(bg)
        for name in names:
            res.label_backgrounds[name] = bg
        if len(names) > 1:
            res.shared_backgrounds.update(names)

    def _label_blocks(self, lay, pending: dict):  # type: ignore[no-untyped-def]
        def key(n):  # type: ignore[no-untyped-def]
            if n not in pending:
                return None
            spec = pending[n][1]
            return (spec.bg, round(spec.bg_alpha, 4))

        return blocks(self._tip_order(lay), key, self._touching(lay))

    def _merged_label_bgs_rect(self, lay, pending: dict, sy: float, res: RenderResult) -> None:  # type: ignore[no-untyped-def]
        """Fundos de rótulos vizinhos de mesma cor num caminho só (em "escada"): entre as
        folhas o fundo vai até o meio do espaço; nas pontas, margem e cantos como antes."""
        for block in self._label_blocks(lay, pending):
            n = len(block.tips)
            if n == 1 and not block.before and not block.after:
                item, spec = pending[block.tips[0]]
                self._label_background(block.tips[0], item, spec, sy - 1, res)
                continue
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            for i, leaf in enumerate(block.tips):
                item, spec = pending[leaf]
                br = item.boundingRect()
                h = br.height()
                height = min(h + 2 * spec.pad, sy - 1)
                yc = item.pos().y() + h / 2
                x0 = item.pos().x() - spec.pad
                w = br.width() + 2 * spec.pad
                s0, s1 = lay.span[leaf][0] * sy, lay.span[leaf][1] * sy
                top_kind = self._side(i, n, block.before, True)
                bot_kind = self._side(i, n, block.after, False)
                top = {"inner": s0, "neighbor": s0 - SEAM_OVERLAP, "outer": yc - height / 2}[top_kind]
                bot = {"inner": s1, "neighbor": s1, "outer": yc + height / 2}[bot_kind]
                if "outer" in (top_kind, bot_kind):
                    r = max(min(spec.radius, height / 2, w / 2), 0.0)
                    path.addRoundedRect(QRectF(x0, top, w, bot - top), r, r)
                    mid = (top + bot) / 2
                    if top_kind != "outer":                    # cantos só nas pontas externas
                        path.addRect(QRectF(x0, top, w, mid - top))
                    if bot_kind != "outer":
                        path.addRect(QRectF(x0, mid, w, bot - mid))
                else:
                    path.addRect(QRectF(x0, top, w, bot - top))
            self._block_item(path, pending[block.tips[0]][1], [l.name for l in block.tips], res)

    def _merged_label_bgs_circ(self, lay, pending: dict, res: RenderResult) -> None:  # type: ignore[no-untyped-def]
        """Circular/leque: entre folhas vizinhas o fundo é um setor com bordas radiais no
        ângulo médio; nas pontas do bloco, o retângulo arredondado girado de sempre."""
        for block in self._label_blocks(lay, pending):
            n = len(block.tips)
            if n == 1 and not block.before and not block.after:
                item, spec, _start, max_h = pending[block.tips[0]]
                self._label_background(block.tips[0], item, spec, max_h, res)
                continue
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            for i, leaf in enumerate(block.tips):
                item, spec, start, max_h = pending[leaf]
                th = lay.pos[leaf][1]
                a, b = lay.span[leaf]
                r_in, r_out = start, start + spec.width + 2 * spec.pad
                lo_kind = self._side(i, n, block.before, True)
                hi_kind = self._side(i, n, block.after, False)
                lo = {"inner": a, "neighbor": a - SEAM_OVERLAP / max(r_in, 1.0), "outer": th}[lo_kind]
                hi = {"inner": b, "neighbor": b, "outer": th}[hi_kind]
                if "outer" in (lo_kind, hi_kind):
                    br = item.boundingRect()
                    h = br.height()
                    height = min(h + 2 * spec.pad, max_h)
                    local = QPainterPath()
                    rect = QRectF(-spec.pad, h / 2 - height / 2, br.width() + 2 * spec.pad, height)
                    r = max(min(spec.radius, height / 2, rect.width() / 2), 0.0)
                    local.addRoundedRect(rect, r, r)
                    path.addPath(item.sceneTransform().map(local))
                if hi > lo:
                    path.addPath(annular_sector(r_in, r_out, lo, hi))
            self._block_item(path, pending[block.tips[0]][1], [l.name for l in block.tips], res)

    def _clade_bg_groups(self, lay, visible: list[ResolvedClade]):  # type: ignore[no-untyped-def]
        """Clados com fundo encostados: mesma cor → um grupo (um caminho só); cor diferente →
        o seguinte avança um pouco sob a divisa (``lead_in``) para não sobrar fresta clara."""
        root = {id(rc): id(rc) for rc in visible}

        def find(k: int) -> int:
            while root[k] != k:
                root[k] = root[root[k]]
                k = root[k]
            return k

        lead_in: set = set()
        for a in visible:
            for b in visible:
                if a is b or abs(lay.span[a.node][1] - lay.span[b.node][0]) > 1e-9:
                    continue
                if a.color.lower() == b.color.lower():
                    root[find(id(b))] = find(id(a))
                else:
                    lead_in.add(id(b))
        groups: dict[int, list] = {}
        for rc in visible:
            groups.setdefault(find(id(rc)), []).append(rc)
        return [(g[0].color, g, {id(rc) for rc in g if id(rc) in lead_in}) for g in groups.values()]

    def _highlight_blocks(self, lay):  # type: ignore[no-untyped-def]
        """(destaque, folhas, encostado antes, encostado depois): cada folha fica com o último
        destaque que a contém; destaques de mesmo estilo vizinhos viram um bloco só."""
        owner = {}
        for hl in self._highlights:
            for name in hl.leaves:
                owner[name] = hl

        def key(n):  # type: ignore[no-untyped-def]
            hl = owner.get(n.name) if n.is_leaf else None
            if hl is None:
                return None
            return (hl.color, round(hl.alpha, 4), hl.outline, round(hl.outline_width, 3), round(hl.thickness, 3))

        out = []
        for block in blocks(self._tip_order(lay), key, self._touching(lay)):
            out.append((owner[block.tips[0].name], block.tips, block.before, block.after))
        return out

    # --------------------------------------------------------- destaque de linha
    def _highlight_runs(self, lay):  # type: ignore[no-untyped-def]
        """(destaque, folhas vizinhas) — folhas seguidas viram uma única faixa (contorno inteiro)."""
        out = []
        order = lay.leaf_order
        for hl in self._highlights:
            run: list[Node] = []
            for i, leaf in enumerate(order):
                if leaf.name in hl.leaves:
                    if run and abs(lay.span[run[-1]][1] - lay.span[leaf][0]) > 1e-9:
                        out.append((hl, run))
                        run = []
                    run.append(leaf)
                elif run:
                    out.append((hl, run))
                    run = []
            if run:
                out.append((hl, run))
        return out

    def _row_highlight(self, path: QPainterPath, hl) -> None:  # type: ignore[no-untyped-def]
        c = QColor(hl.color)
        c.setAlphaF(max(0.0, min(hl.alpha, 1.0)))
        item = QGraphicsPathItem(path)
        item.setBrush(QBrush(c))
        if hl.outline and hl.outline_width > 0:
            item.setPen(QPen(QColor(hl.outline), hl.outline_width))
        else:
            item.setPen(QPen(Qt.PenStyle.NoPen))
        item.setZValue(-3)                 # atrás de tudo (inclusive do fundo dos clados)
        item.setData(1, TAG_ROW_HIGHLIGHT)
        self.scene.addItem(item)

    # ------------------------------------------------------------ "//"
    def _broken(self, tree: Tree) -> list[Node]:
        return [n for n in tree.broken if n.parent is not None and n in self._visible and n.parent in self._visible]

    def _break_mark(self, center: QPointF, angle: float, width: float) -> None:
        """Marca "//" sobre o ramo encurtado: duas barras inclinadas com uma lacuna entre elas."""
        size = max(self.style.label.size * 0.55, 4.0)
        gap = max(size * 0.35, width + 1.0)
        d = QPointF(math.cos(angle), math.sin(angle))           # ao longo do ramo
        n = QPointF(-d.y(), d.x())                                # perpendicular
        slant = 0.45
        bg = QColor(self.style.background) if self.style.background else None
        if bg is not None:                                        # apaga o ramo entre as barras
            hole = QPainterPath()
            corners = []
            for s_ in (-1, 1):
                for t in (-1, 1):
                    off = s_ * gap / 2 + t * slant * size
                    corners.append(center + d * off + n * (t * size))
            hole.moveTo(corners[0])
            hole.lineTo(corners[1])
            hole.lineTo(corners[3])
            hole.lineTo(corners[2])
            hole.closeSubpath()
            item = QGraphicsPathItem(hole)
            item.setBrush(QBrush(bg))
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setZValue(1)
            item.setData(1, TAG_BREAK)
            self.scene.addItem(item)
        path = QPainterPath()
        for s_ in (-1, 1):
            c = center + d * (s_ * gap / 2)
            path.moveTo(c - d * (slant * size) - n * size)
            path.lineTo(c + d * (slant * size) + n * size)
        pen = QPen(QColor(self.style.branch.color), max(width, 1.0))
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        item.setZValue(1.1)
        item.setData(1, TAG_BREAK)
        self.scene.addItem(item)

    # ------------------------------------------------------------ trilhas
    def _value_text_width(self, track: BarTrack) -> float:
        if not track.show_values or not track.values:
            return 0.0
        fm = QFontMetricsF(self._small_font())
        return max(fm.horizontalAdvance(fmt_value(v)) for v in track.values.values()) + 4

    def _small_font(self) -> QFont:
        f = QFont(self._font)
        f.setPointSizeF(max(self.style.label.size * 0.7, 4))
        return f

    def _track_extent(self, track, cell_w: float) -> float:  # type: ignore[no-untyped-def]
        """Largura (px) ocupada pela trilha: coluna no retangular, anel no circular."""
        if track == CLADE_STRIP:
            return self.style.clades.strip_width
        if isinstance(track, BarTrack):
            return track.width + self._value_text_width(track)
        if isinstance(track, StackedTrack):
            return track.width
        return track.width or cell_w

    def _bar_color(self, track: BarTrack, node: Node, names: list[str]) -> str:
        if track.color_mode == "clade":
            rc = self._clade_of(node)
            return rc.color if rc is not None else self.style.clades.neutral_color
        if track.color_mode == "metadata":
            if len(names) == 1:
                return track.colors.get(names[0], track.color)
            return self._meta_node.get(node, track.color)
        return track.color

    def _flush_bars(self, by_color: dict[str, QPainterPath], track: BarTrack) -> None:
        for color, path in by_color.items():
            item = QGraphicsPathItem(path)
            item.setBrush(QBrush(QColor(color)))
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setData(1, TAG_BAR)
            item.setData(2, track.key)
            self.scene.addItem(item)

    def _bar_pen(self, kind: str) -> QPen:
        if kind == "ref":
            pen = QPen(QColor("#7a7a7a"), 0.7)
            pen.setDashPattern([4.0, 3.0])
        elif kind == "missing":
            pen = QPen(QColor("#9a9a9a"), 1.2)
        else:
            pen = QPen(QColor("#505050"), 0.6)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        return pen

    def _tagged(self, item: QGraphicsItem, tag: str, key: str) -> QGraphicsItem:
        item.setData(1, tag)
        item.setData(2, key)
        if item.scene() is None:
            self.scene.addItem(item)
        return item

    def _column_header(self, text: str, x: float, cw: float, top: float, horizontal_ok: bool = False,
                       rotation: int = 90) -> None:
        """Nome da coluna acima dela: horizontal se couber, senão vertical (de baixo para cima).

        ``rotation`` 0 ou 45 força horizontal ou diagonal (subindo para a direita)."""
        size = max(self.style.label.size * 0.85, 4)
        h = self._text(text, size)
        h.setData(1, TAG_COLUMN_HEADER)
        if rotation == 0:
            br = h.boundingRect()
            while br.width() > cw and size > 5:     # cabe na largura da coluna?
                size = max(size * min(cw / br.width(), 0.92), 5)
                f = h.font()
                f.setPointSizeF(size)
                h.setFont(f)
                br = h.boundingRect()
            if br.width() <= cw:
                h.setPos(x + cw / 2 - br.width() / 2, top - 3 - br.height())
                return
            # nem com fonte mínima: vertical, para não sobrepor as vizinhas
            note = "nomes de coluna a 0° não cabem em colunas estreitas (desenhados a 90°)"
            if note not in self.notes:
                self.notes.append(note)
            size = max(self.style.label.size * 0.85, 4)
            f = h.font()
            f.setPointSizeF(size)
            h.setFont(f)
        if rotation == 45:
            hh = h.boundingRect().height()
            while hh > cw * 0.7 and size > 4:   # diagonais vizinhas não se encostam
                size = max(size * min(cw * 0.7 / hh, 0.92), 4)
                f = h.font()
                f.setPointSizeF(size)
                h.setFont(f)
                hh = h.boundingRect().height()
            # canto inferior esquerdo do texto sobre o centro da coluna
            h.setTransformOriginPoint(0, hh)
            h.setRotation(-45)
            h.setPos(x + cw / 2 - hh * 0.35, top - 3 - hh)
            return
        if horizontal_ok and h.boundingRect().width() <= cw:
            br = h.boundingRect()
            h.setPos(x + cw / 2 - br.width() / 2, top - 3 - br.height())
            return
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

    def _draw_tracks_rect(self, tree: Tree, lay, x: float, sy: float, pad: float,  # type: ignore[no-untyped-def]
                          visible: list[ResolvedClade], y_range) -> float:
        """Trilhas em colunas à direita dos rótulos, na ordem pedida. Devolve o x final.

        Colunas de células seguidas ficam encostadas; cada bloco é seguido de um espaço."""
        hm = self.style.heatmap
        cs = self.style.clades
        top = lay.span[tree.root][0] * sy
        bottom = lay.span[tree.root][1] * sy
        in_cells = False
        for track in self._tracks:
            is_cell = isinstance(track, LeafColumn)
            if in_cells and not is_cell:
                x += pad
            in_cells = is_cell
            if track == CLADE_STRIP:
                if not visible:
                    continue
                for rc in visible:
                    y0, y1 = y_range(rc.node)
                    path = QPainterPath()
                    path.addRect(QRectF(x, y0, cs.strip_width, y1 - y0))
                    self._fill(path, rc.color, 1.0, TAG_CLADE_STRIP, 0)
                x += cs.strip_width + pad
            elif isinstance(track, BarTrack):
                self._bars_rect(track, lay, x, sy, top, bottom)
                x += self._track_extent(track, 0) + pad
            elif isinstance(track, StackedTrack):
                self._stacked_rect(track, lay, x, sy, top, bottom)
                x += track.width + pad
            else:
                cw = track.width if track.width else sy * hm.cell_width
                by_color: dict[str, QPainterPath] = {}
                for node, names in self._tips(lay):
                    a, b = lay.span[node]
                    color = self._cell_color(track, names)
                    rect = QRectF(x, a * sy, cw, (b - a) * sy)
                    by_color.setdefault(color, QPainterPath()).addRect(rect)
                    if len(names) == 1 and names[0] in track.texts:
                        self._cell_text(track.texts[names[0]], rect.center(), color)
                self._flush_cells(by_color, track)
                if hm.show_headers or track.kind == "matrix":
                    self._column_header(track.header, x, cw, top, rotation=track.header_rotation)
                x += cw
        if in_cells:
            x += pad
        return x

    def _bars_rect(self, track: BarTrack, lay, x0: float, sy: float, top: float, bottom: float) -> None:  # type: ignore[no-untyped-def]
        w = track.width
        base = x0 + track.base * w
        by_color: dict[str, QPainterPath] = {}
        missing = QPainterPath()
        small = self._small_font()
        for node, names in self._tips(lay):
            a, b = lay.span[node]
            yc = lay.pos[node][1] * sy
            h = (b - a) * sy * 0.7
            v = track.value_for(names)
            if v is None:
                missing.moveTo(x0, yc)
                missing.lineTo(x0 + min(6.0, w * 0.1), yc)
                continue
            end = x0 + track.frac(v) * w
            rect = QRectF(min(base, end), yc - h / 2, abs(end - base), h)
            by_color.setdefault(self._bar_color(track, node, names), QPainterPath()).addRect(rect)
            if track.show_values:
                t = QGraphicsSimpleTextItem(fmt_value(v))
                t.setFont(small)
                t.setBrush(QBrush(QColor("#404040")))
                br = t.boundingRect()
                t.setPos(max(base, end) + 2, yc - br.height() / 2)
                self._tagged(t, TAG_BAR_VALUE, track.key)
        self._flush_bars(by_color, track)
        if not missing.isEmpty():
            self._tagged(self._path_item(missing, self._bar_pen("missing")), TAG_BAR_MISSING, track.key)
        refs = QPainterPath()
        for r in track.visible_refs():
            rx = x0 + track.frac(r) * w
            refs.moveTo(rx, top)
            refs.lineTo(rx, bottom)
        if not refs.isEmpty():
            item = self._path_item(refs, self._bar_pen("ref"))
            item.setZValue(-0.5)      # atrás das barras e dos valores, à frente do fundo dos clados
            self._tagged(item, TAG_BAR_REF, track.key)
        # eixo: mínimo, referências e máximo embaixo da coluna
        self._axis_rect(track.key, x0, w, bottom, [track.vmin, *track.visible_refs(), track.vmax], track.frac)
        if self.style.heatmap.show_headers:
            self._column_header(track.header, x0, w, top, horizontal_ok=True)

    def _axis_rect(self, key: str, x0: float, w: float, bottom: float, ticks: list[float], frac) -> None:  # type: ignore[no-untyped-def]
        small = self._small_font()
        ay = bottom + 2
        axis = QPainterPath()
        axis.moveTo(x0, ay)
        axis.lineTo(x0 + w, ay)
        for v in ticks:
            tx = x0 + frac(v) * w
            axis.moveTo(tx, ay)
            axis.lineTo(tx, ay + 3)
        self._tagged(self._path_item(axis, self._bar_pen("axis")), TAG_BAR_AXIS, key)
        # mínimo e máximo sempre aparecem; os intermediários só se não encostarem em outro
        order = [0, len(ticks) - 1, *range(1, len(ticks) - 1)] if len(ticks) > 1 else [0]
        placed: list[tuple[float, float]] = []
        for k in order:
            v = ticks[k]
            t = QGraphicsSimpleTextItem(fmt_value(v))
            t.setFont(small)
            t.setBrush(QBrush(QColor("#505050")))
            br = t.boundingRect()
            # dentro da largura da coluna: não invade a coluna vizinha
            tx = min(max(x0 + frac(v) * w - br.width() / 2, x0), x0 + w - br.width())
            if any(tx < b + 2 and tx + br.width() > a - 2 for a, b in placed):
                continue
            placed.append((tx, tx + br.width()))
            t.setPos(tx, ay + 3)
            self._tagged(t, TAG_BAR_AXIS, key)

    def _stacked_rect(self, track: StackedTrack, lay, x0: float, sy: float, top: float, bottom: float) -> None:  # type: ignore[no-untyped-def]
        w = track.width
        by_color: dict[str, QPainterPath] = {}
        missing = QPainterPath()
        for node, names in self._tips(lay):
            a, b = lay.span[node]
            yc = lay.pos[node][1] * sy
            h = (b - a) * sy * 0.7
            stack = track.stack_for(names)
            if stack is None:
                missing.moveTo(x0, yc)
                missing.lineTo(x0 + min(6.0, w * 0.1), yc)
                continue
            cum = 0.0
            for v, color in zip(stack, track.colors):
                if v <= 0:
                    continue
                s0, s1 = x0 + track.frac(cum) * w, x0 + track.frac(cum + v) * w
                cum += v
                if s1 > s0:
                    by_color.setdefault(color, QPainterPath()).addRect(QRectF(s0, yc - h / 2, s1 - s0, h))
        self._flush_stacked(by_color, track)
        if not missing.isEmpty():
            self._tagged(self._path_item(missing, self._bar_pen("missing")), TAG_BAR_MISSING, track.key)
        self._axis_rect(track.key, x0, w, bottom, [0.0, track.vmax], track.frac)
        if self.style.heatmap.show_headers:
            self._column_header(track.header, x0, w, top, horizontal_ok=True)

    def _stacked_circ(self, track: StackedTrack, lay, r0: float, pt) -> None:  # type: ignore[no-untyped-def]
        w = track.width
        by_color: dict[str, QPainterPath] = {}
        missing = QPainterPath()
        for node, names in self._tips(lay):
            a, b = lay.span[node]
            mid = (a + b) / 2
            half = (b - a) / 2 * 0.7
            stack = track.stack_for(names)
            if stack is None:
                missing.moveTo(pt(r0, mid))
                missing.lineTo(pt(r0 + min(6.0, w * 0.1), mid))
                continue
            cum = 0.0
            for v, color in zip(stack, track.colors):
                if v <= 0:
                    continue
                s0, s1 = r0 + track.frac(cum) * w, r0 + track.frac(cum + v) * w
                cum += v
                if s1 > s0:
                    by_color.setdefault(color, QPainterPath()).addPath(annular_sector(s0, s1, mid - half, mid + half))
        self._flush_stacked(by_color, track)
        if not missing.isEmpty():
            self._tagged(self._path_item(missing, self._bar_pen("missing")), TAG_BAR_MISSING, track.key)

    def _flush_stacked(self, by_color: dict[str, QPainterPath], track: StackedTrack) -> None:
        for color, path in by_color.items():
            item = QGraphicsPathItem(path)
            item.setBrush(QBrush(QColor(color)))
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setData(1, TAG_STACKED)
            item.setData(2, track.key)
            item.setData(3, track.series[track.colors.index(color)] if color in track.colors else "")
            self.scene.addItem(item)

    def _bars_circ(self, track: BarTrack, lay, r0: float, root_span: tuple[float, float], pt) -> None:  # type: ignore[no-untyped-def]
        w = track.width
        rb = r0 + track.base * w
        by_color: dict[str, QPainterPath] = {}
        missing = QPainterPath()
        small = self._small_font()
        for node, names in self._tips(lay):
            a, b = lay.span[node]
            mid = (a + b) / 2
            half = (b - a) / 2 * 0.7
            v = track.value_for(names)
            if v is None:
                missing.moveTo(pt(r0, mid))
                missing.lineTo(pt(r0 + min(6.0, w * 0.1), mid))
                continue
            re_ = r0 + track.frac(v) * w
            lo, hi = sorted((rb, re_))
            if hi - lo > 0:
                by_color.setdefault(self._bar_color(track, node, names), QPainterPath()).addPath(
                    annular_sector(lo, hi, mid - half, mid + half))
            if track.show_values:
                t = QGraphicsSimpleTextItem(fmt_value(v))
                t.setFont(small)
                t.setBrush(QBrush(QColor("#404040")))
                self.scene.addItem(t)
                self._rotate_radial(t, pt(hi + 2, mid), mid)
                self._tagged(t, TAG_BAR_VALUE, track.key)
        self._flush_bars(by_color, track)
        if not missing.isEmpty():
            self._tagged(self._path_item(missing, self._bar_pen("missing")), TAG_BAR_MISSING, track.key)
        refs = QPainterPath()
        th0, th1 = root_span
        for r in track.visible_refs():
            rr = r0 + track.frac(r) * w
            rect = QRectF(-rr, -rr, 2 * rr, 2 * rr)
            refs.arcMoveTo(rect, _qt_deg(th0))
            refs.arcTo(rect, _qt_deg(th0), _qt_deg(th1) - _qt_deg(th0))
        if not refs.isEmpty():
            item = self._path_item(refs, self._bar_pen("ref"))
            item.setZValue(-0.5)      # atrás das barras e dos valores, à frente do fundo dos clados
            self._tagged(item, TAG_BAR_REF, track.key)

    def _path_item(self, path: QPainterPath, pen: QPen) -> QGraphicsPathItem:
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        self.scene.addItem(item)
        return item

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

    def _support_levels(self, tree: Tree, point) -> None:  # type: ignore[no-untyped-def]
        """Círculos nos nós, cor pela faixa de suporte (painel Figura → Suporte)."""
        from jabuti.models.support import level_of

        lv = self.style.figure.support_levels
        if not lv.enabled:
            return
        colors = list(lv.colors) + ["#888888"] * (len(lv.cutoffs) + 1 - len(lv.colors))
        paths: dict[int, QPainterPath] = {}
        r = lv.size / 2
        for node in tree.root.traverse_preorder():
            if node.is_leaf or not node.supports or node is tree.root or node not in self._visible:
                continue
            k = level_of(support_value(node.supports, lv.index), lv.cutoffs)
            paths.setdefault(k, QPainterPath()).addEllipse(point(node), r, r)
        for k, path in sorted(paths.items()):
            item = QGraphicsPathItem(path)
            item.setBrush(QBrush(QColor(colors[k])))
            item.setPen(QPen(QColor("#404040"), max(lv.size * 0.08, 0.4)))
            item.setZValue(2.5)
            item.setData(1, TAG_SUPPORT_LEVEL)
            item.setData(2, k)
            self.scene.addItem(item)

    def _support_items(self, tree: Tree, style: RenderStyle, place, point) -> None:  # type: ignore[no-untyped-def]
        """Suporte como números (``place`` posiciona o texto) ou símbolos (em ``point(node)``)."""
        self._support_levels(tree, point)
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

        slanted = LayoutKind(style.layout) == LayoutKind.SLANTED
        edges = _EdgeBatch(style.branch.cap)
        for node in visible_nodes(tree, self._collapsed):
            p = pt(node)
            res.node_points[node] = p
            if node.parent is not None:
                pp = pt(node.parent)
                start = pp if slanted else QPointF(pp.x(), p.y())   # diagonal: direto do pai
                edges.seg(self._edge_color(node), self._width(node), start, p)
            if node in self._collapsed:
                continue
            if node.children and not slanted:
                top, bot = pt(node.children[0]), pt(node.children[-1])
                edges.seg(self._node_color(node), self._width(node), QPointF(p.x(), top.y()), QPointF(p.x(), bot.y()))
        edges.flush(self.scene)
        for node in self._broken(tree):
            pp = pt(node.parent)
            p = pt(node)
            if slanted:
                ang = math.atan2(p.y() - pp.y(), p.x() - pp.x())
                self._break_mark(QPointF((pp.x() + p.x()) / 2, (pp.y() + p.y()) / 2), ang, self._width(node))
            else:
                self._break_mark(QPointF((pp.x() + p.x()) / 2, p.y()), 0.0, self._width(node))

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
        label_bgs: dict[Node, tuple] = {}
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
            if self._merge and spec.bg:
                label_bgs[leaf] = (item, spec)
                label_right = max(label_right, item.pos().x() + item.boundingRect().width() + spec.pad)
                continue
            bg = self._label_background(leaf, item, spec, sy - 1, res)
            if bg is not None:
                label_right = max(label_right, bg.sceneBoundingRect().right())
        if label_bgs:
            self._merged_label_bgs_rect(lay, label_bgs, sy, res)

        visible = self._visible_clades(res)

        def y_range(node: Node) -> tuple[float, float]:
            a, b = lay.span[node]
            return a * sy, b * sy

        x = label_right + pad
        x = self._draw_tracks_rect(tree, lay, x, sy, pad, visible, y_range)
        if self._context:
            x = self._draw_context(lay, x, sy, pad) + pad
        if self._merge:
            for hl, run, before, after in self._highlight_blocks(lay):
                h = sy * max(min(hl.thickness, 1.0), 0.1)
                x0 = min(pt(l).x() for l in run) + pad / 2
                top = lay.span[run[0]][0] * sy - SEAM_OVERLAP if before else pt(run[0]).y() - h / 2
                bottom = lay.span[run[-1]][1] * sy if after else pt(run[-1]).y() + h / 2
                path = QPainterPath()
                path.addRect(QRectF(x0, top, x - pad / 2 - x0, bottom - top))
                self._row_highlight(path, hl)
        else:
            for hl, run in self._highlight_runs(lay):
                first, last = run[0], run[-1]
                h = sy * max(min(hl.thickness, 1.0), 0.1)
                x0 = min(pt(l).x() for l in run) + pad / 2
                rect = QRectF(x0, pt(first).y() - h / 2, x - pad / 2 - x0, pt(last).y() - pt(first).y() + h)
                path = QPainterPath()
                path.addRect(rect)
                self._row_highlight(path, hl)
        if cs.background and visible:
            if self._merge:
                for color, group, lead_in in self._clade_bg_groups(lay, visible):
                    path = QPainterPath()
                    path.setFillRule(Qt.FillRule.WindingFill)
                    for rc in group:
                        y0, y1 = y_range(rc.node)
                        y0 -= SEAM_OVERLAP if id(rc) in lead_in else 0.0
                        x0 = pt(rc.node).x() - pad / 2
                        path.addRect(QRectF(x0, y0, x - pad / 2 - x0, y1 - y0))
                    self._fill(path, color, cs.background_alpha, TAG_CLADE_BG, -2)
            else:
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
        fan = LayoutKind(style.layout) == LayoutKind.FAN
        lay = circular_layout(tree, style.use_lengths, collapsed=self._collapsed,
                              arc_degrees=style.fan.angle if fan else 360.0,
                              start_degrees=style.fan.start if fan else 0.0)
        spacing = style.label.size * style.leaf_spacing
        pad = style.label.size * 0.5
        cs = style.clades
        visible = self._visible_clades(res)
        col_w = spacing * style.heatmap.cell_width
        self._ring_tracks = [t for t in self._tracks if t != CLADE_STRIP or visible]
        ring_widths = [self._track_extent(t, col_w) for t in self._ring_tracks]

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
        for node in self._broken(tree):
            th = lay.pos[node][1]
            mid = (rad(node.parent) + rad(node)) / 2
            self._break_mark(pt(mid, th), th, self._width(node))

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

        circ_bgs: dict[Node, tuple] = {}
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
                if self._merge:
                    circ_bgs[leaf] = (item, spec, start, max(chord - 1, 2.0))
                else:
                    self._label_background(leaf, item, spec, max(chord - 1, 2.0), res)
        if circ_bgs:
            self._merged_label_bgs_circ(lay, circ_bgs, res)

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

        runs = ([(hl, run, False, False) for hl, run in self._highlight_runs(lay)] if not self._merge
                else self._highlight_blocks(lay))
        for hl, run, before, after in runs:
            frac = max(min(hl.thickness, 1.0), 0.1)
            a0, b0 = lay.span[run[0]]
            a1, b1 = lay.span[run[-1]]
            r0 = geom.tip_ring if geom.align_tips else min(rad(l) for l in run)
            r0 = max(r0 - pad / 2, 0.0)
            th0 = a0 - SEAM_OVERLAP / max(r0, 1.0) if before else (a0 + b0) / 2 - (b0 - a0) / 2 * frac
            th1 = b1 if after else (a1 + b1) / 2 + (b1 - a1) / 2 * frac
            self._row_highlight(annular_sector(r0, outer + pad / 2, th0, th1), hl)

        root_span = lay.span[tree.root]
        for i, track in enumerate(self._ring_tracks):
            r0, r1 = geom.ring_bounds(i)
            if track == CLADE_STRIP:
                for rc in visible:
                    th0, th1 = th_range(rc.node)
                    self._fill(annular_sector(r0, r1, th0, th1), rc.color, 1.0, TAG_CLADE_STRIP, 0)
            elif isinstance(track, BarTrack):
                self._bars_circ(track, lay, r0, root_span, pt)
            elif isinstance(track, StackedTrack):
                self._stacked_circ(track, lay, r0, pt)
            else:
                by_color: dict[str, QPainterPath] = {}
                for node, names in self._tips(lay):
                    a, b = lay.span[node]
                    color = self._cell_color(track, names)
                    by_color.setdefault(color, QPainterPath()).addPath(annular_sector(r0, r1, a, b))
                    if len(names) == 1 and names[0] in track.texts:
                        mid = (a + b) / 2
                        self._cell_text(track.texts[names[0]], pt((r0 + r1) / 2, mid), color)
                self._flush_cells(by_color, track)
        if not lay.full:
            self._fan_headers(lay, geom, pt)
        if cs.background and visible:
            groups = (self._clade_bg_groups(lay, visible) if self._merge
                      else [(rc.color, [rc], set()) for rc in visible])
            for color, group, lead_in in groups:
                path = QPainterPath()
                path.setFillRule(Qt.FillRule.WindingFill)
                for rc in group:
                    th0, th1 = th_range(rc.node)
                    r0 = max(rad(rc.node) - pad / 2, 0.0)
                    if id(rc) in lead_in:
                        th0 -= SEAM_OVERLAP / max(r0, 1.0)
                    path.addPath(annular_sector(r0, outer + pad / 2, th0, th1))
                self._fill(path, color, cs.background_alpha, TAG_CLADE_BG, -2)
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
            if lay.full:
                circle.addEllipse(QPointF(0, 0), rc_px, rc_px)
            else:                                         # leque: só o arco
                th0, th1 = root_span
                rect = QRectF(-rc_px, -rc_px, 2 * rc_px, 2 * rc_px)
                circle.arcMoveTo(rect, _qt_deg(th0))
                circle.arcTo(rect, _qt_deg(th0), _qt_deg(th1) - _qt_deg(th0))
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

    # ------------------------------------------------------- não enraizada
    def _render_unrooted(self, tree: Tree, style: RenderStyle, res: RenderResult) -> None:
        from jabuti.layout.unrooted import unrooted_layout

        ur = style.unrooted
        lay = unrooted_layout(tree, style.use_lengths, self._collapsed, ur.daylight, ur.rotation, ur.mirror)
        scale = (style.base_width * style.branch_scale / 2) / lay.extent if lay.extent > 0 else 1.0
        pad = style.label.size * 0.5
        row_h = style.label.size * style.leaf_spacing
        if any(t != CLADE_STRIP for t in self._tracks):
            self.notes.append("colunas de dados não se aplicam à árvore não enraizada")
        cs = style.clades
        if cs.background or cs.outer_strip or cs.show_names:
            self.notes.append("faixas, fundo e nomes de clado não se aplicam à árvore não enraizada "
                              "(as cores dos clados valem nos ramos e rótulos)")

        def pt(node: Node) -> QPointF:
            x, y = lay.pos[node]
            return QPointF(x * scale, y * scale)

        edges = _EdgeBatch(style.branch.cap)
        for node in visible_nodes(tree, self._collapsed):
            p = pt(node)
            res.node_points[node] = p
            if node.parent is not None:
                edges.seg(self._edge_color(node), self._width(node), pt(node.parent), p)
        edges.flush(self.scene)
        for node in self._broken(tree):
            pp, p = pt(node.parent), pt(node)
            self._break_mark((pp + p) / 2, math.atan2(p.y() - pp.y(), p.x() - pp.x()), self._width(node))

        # clados colapsados: leque triangular a partir do nó, na direção do ramo
        for node, far in lay.collapsed.items():
            ang = lay.edge_angle(node) if node.parent is not None else 0.0
            a0, a1 = lay.wedge[node]
            half = min(max((a1 - a0) / 2, math.radians(4)), math.radians(25))
            p = pt(node)
            r = max(far * scale, style.label.size)
            tri = QPainterPath()
            tri.moveTo(p)
            tri.lineTo(p + QPointF(math.cos(ang - half), math.sin(ang - half)) * r)
            tri.lineTo(p + QPointF(math.cos(ang + half), math.sin(ang + half)) * r)
            tri.closeSubpath()
            self._collapsed_triangle(tri, node)
            if style.label.show:
                t = self._text(self._collapsed_label(node), color=self._branch_color(node))
                t.setData(1, TAG_COLLAPSED)
                self._rotate_radial(t, p + QPointF(math.cos(ang), math.sin(ang)) * (r + pad), ang)

        hl_by_leaf: dict[str, object] = {}
        for hl in self._highlights:
            for name in hl.leaves:
                hl_by_leaf[name] = hl
        for leaf in lay.leaf_order:
            p = pt(leaf)
            res.leaf_points[leaf.name] = p
            if not style.label.show:
                continue
            ang = lay.edge_angle(leaf) if leaf.parent is not None else 0.0
            spec = self._label_spec(leaf)
            item = self._leaf_text(leaf, spec)
            anchor = p + QPointF(math.cos(ang), math.sin(ang)) * (pad + self._marker / 2 + spec.pad)
            self._rotate_radial(item, anchor, ang)
            res.leaf_items.setdefault(leaf.name, []).append(item)
            self._label_background(leaf, item, spec, row_h - 1, res)
            hl = hl_by_leaf.get(leaf.name)
            if hl is not None:                    # sem colunas: o destaque fica atrás do rótulo
                br = item.boundingRect()
                path = QPainterPath()
                path.addRect(br.adjusted(-pad / 2, -1, pad / 2, 1))
                band = QGraphicsPathItem(path)
                band.setTransformOriginPoint(item.transformOriginPoint())
                band.setRotation(item.rotation())
                band.setPos(item.pos())
                c = QColor(hl.color)  # type: ignore[attr-defined]
                c.setAlphaF(max(0.0, min(hl.alpha, 1.0)))  # type: ignore[attr-defined]
                band.setBrush(QBrush(c))
                band.setPen(QPen(QColor(hl.outline), hl.outline_width) if hl.outline  # type: ignore[attr-defined]
                            else QPen(Qt.PenStyle.NoPen))
                band.setZValue(-3)
                band.setData(1, TAG_ROW_HIGHLIGHT)
                self.scene.addItem(band)

        def place(node: Node, item: QGraphicsSimpleTextItem) -> None:
            p = pt(node)
            br = item.boundingRect()
            item.setPos(p.x() + 2, p.y() - br.height())

        self._tip_symbols(lay.leaf_order, pt)
        self._support_items(tree, style, place, pt)
        if lay.uses_lengths and lay.extent > 0:
            self._scale_bar(lay.extent, scale, row_h)

    def _fan_headers(self, lay, geom: CircGeometry, pt) -> None:  # type: ignore[no-untyped-def]
        """Leque: nomes das colunas/anéis no vão, logo antes do início do arco, um por anel."""
        if 2 * math.pi - lay.arc < math.radians(15) or not (self.style.heatmap.show_headers or any(
                isinstance(t, LeafColumn) and t.kind == "matrix" for t in self._ring_tracks)):
            return
        th = lay.start
        u = th - math.pi / 2                    # tangente apontando para dentro do vão
        for i, track in enumerate(self._ring_tracks):
            if track == CLADE_STRIP:
                continue
            r0, r1 = geom.ring_bounds(i)
            ring_w = r1 - r0
            size = max(self.style.label.size * 0.85, 4)
            t = self._text(track.header, size)
            t.setData(1, TAG_COLUMN_HEADER)
            hh = t.boundingRect().height()
            while hh > ring_w * 0.95 and size > 4:       # cabe na largura do anel
                size = max(size * min(ring_w * 0.95 / hh, 0.92), 4)
                f = t.font()
                f.setPointSizeF(size)
                t.setFont(f)
                hh = t.boundingRect().height()
            rm = (r0 + r1) / 2
            anchor = pt(rm, th) + QPointF(math.cos(u), math.sin(u)) * 3
            self._rotate_radial(t, anchor, u)

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
    def _draw_legend(self, sections: list[LegendGroup]) -> None:
        """Legenda (mesmo conteúdo do painel) como itens da cena, ao lado do desenho:
        fica fora da caixa de árvore, heatmap e barra de escala, então nunca os cobre."""
        if not sections:
            return
        box = self.scene.itemsBoundingRect()
        size = max(self.style.label.size * 0.9, 4)
        sw = size * 1.15
        items: list[QGraphicsItem] = []
        y = 0.0
        for k, group in enumerate(sections):
            if k:
                y += size * 0.6
            t = self._text(group.title, size, "#404040")
            f = t.font()
            f.setItalic(True)
            t.setFont(f)
            t.setPos(0, y)
            items.append(t)
            y += t.boundingRect().height() + 1
            if group.kind == "colorbar" and group.stops:
                bar_w = size * 9
                rect = QGraphicsRectItem(0, y, bar_w, sw)
                grad = QLinearGradient(0, 0, bar_w, 0)
                for i, c in enumerate(group.stops):
                    grad.setColorAt(i / max(len(group.stops) - 1, 1), QColor(c))
                rect.setBrush(QBrush(grad))
                rect.setPen(QPen(QColor("#777777"), 0.5))
                self.scene.addItem(rect)
                items.append(rect)
                y += sw + 1
                small = size * 0.85
                lh = 0.0
                for frac, text in group.ticks:
                    lab = self._text(text, small, "#202020")
                    br = lab.boundingRect()
                    lab.setPos(min(max(frac * bar_w - br.width() / 2, 0), bar_w - br.width()), y)
                    items.append(lab)
                    lh = max(lh, br.height())
                y += lh + 1
            for text, color in group.entries:
                label = self._text(text, size, "#202020")
                lh = label.boundingRect().height()
                if color is not None:
                    square = QGraphicsRectItem(0, y + (lh - sw) / 2, sw, sw)
                    square.setBrush(QBrush(QColor(color)))
                    square.setPen(QPen(QColor("#777777"), 0.5))
                    self.scene.addItem(square)
                    items.append(square)
                    label.setPos(sw + size * 0.5, y)
                else:
                    label.setPos(0, y)
                items.append(label)
                y += lh + 1
        local = QRectF()
        for it in items:
            local = local.united(it.sceneBoundingRect())
        origin = _legend_anchor(self.style.legend.position, box, local.width(), local.height(), size * 3)
        for it in items:
            it.moveBy(origin.x() - local.left(), origin.y() - local.top())
            it.setData(1, TAG_LEGEND)

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


def _legend_anchor(position: str, box: QRectF, w: float, h: float, gap: float) -> QPointF:
    """Canto de cima/baixo, sempre ao lado (fora) do desenho."""
    x = box.left() - gap - w if position.endswith("left") else box.right() + gap
    y = box.bottom() - h if position.startswith("bottom") else box.top()
    return QPointF(x, y)


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
