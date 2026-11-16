"""Monta os itens da QGraphicsScene a partir do layout, do estilo e dos clados."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
)

from jabuti.layout.circular import CircGeometry, circular_geometry, circular_layout
from jabuti.layout.rectangular import rectangular_layout, visible_nodes
from jabuti.models.color_rules import ColorRules, blend, propagate_meta
from jabuti.models.clades import Clade, ResolvedClade, resolve_clades
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
TAG_RANGE_BG = "range-background"        # faixa "range" do iTOL
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
TAG_LABEL_GUIDE = "label-guide"   # linha da folha até o rótulo afastado (não enraizada)
TAG_BAR = "bar"
TAG_BAR_MISSING = "bar-missing"
TAG_BAR_REF = "bar-reference"
TAG_BAR_AXIS = "bar-axis"
TAG_BAR_VALUE = "bar-value"
TAG_STACKED = "stacked-bar"
TAG_MATRIX = "matrix"
TAG_BINARY = "binary"            # formas de presença/ausência (iTOL DATASET_BINARY)
TAG_ITOL_SYMBOL = "itol-symbol"  # símbolos do iTOL sobre os ramos
TAG_ITOL_TEXT = "itol-text"      # textos do iTOL (sobre os ramos ou em coluna)
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


def shape_path(shape: int, c: QPointF, size: float) -> QPainterPath:
    """Formas do iTOL: 1 quadrado, 2 círculo, 3 estrela, 4 triângulo p/ direita,
    5 triângulo p/ esquerda, 6 "check" (traço), 7/8/9 linha contínua/tracejada/pontilhada,
    10/11/12 seta p/ esquerda/direita/dupla; outras = quadrado."""
    h = size / 2
    x, y = c.x(), c.y()
    path = QPainterPath()
    if shape == 2:
        path.addEllipse(c, h, h)
    elif shape == 3:
        pts = []
        for k in range(10):
            r = h if k % 2 == 0 else h * 0.45
            a = -math.pi / 2 + k * math.pi / 5
            pts.append(QPointF(x + r * math.cos(a), y + r * math.sin(a)))
        path.addPolygon(QPolygonF(pts))
        path.closeSubpath()
    elif shape in (4, 5):
        s = 1 if shape == 4 else -1
        path.addPolygon(QPolygonF([QPointF(x - s * h, y - h), QPointF(x + s * h, y), QPointF(x - s * h, y + h)]))
        path.closeSubpath()
    elif shape == 6:
        path.moveTo(x - h, y)
        path.lineTo(x - h * 0.25, y + h * 0.75)
        path.lineTo(x + h, y - h * 0.8)
    elif shape in (7, 8, 9):                 # linha contínua, tracejada, pontilhada (traço)
        path.moveTo(x - h, y)
        path.lineTo(x + h, y)
    elif shape in (10, 11, 12):              # seta p/ esquerda, p/ direita, dupla
        t = h * 0.45                         # meia altura da haste
        if shape == 11:
            pts = [(-h, -t), (0, -t), (0, -h), (h, 0), (0, h), (0, t), (-h, t)]
        elif shape == 10:
            pts = [(h, -t), (0, -t), (0, -h), (-h, 0), (0, h), (0, t), (h, t)]
        else:
            pts = [(-h, 0), (-h * 0.4, -h), (-h * 0.4, -t), (h * 0.4, -t), (h * 0.4, -h), (h, 0),
                   (h * 0.4, h), (h * 0.4, t), (-h * 0.4, t), (-h * 0.4, h)]
        path.addPolygon(QPolygonF([QPointF(x + a, y + b) for a, b in pts]))
        path.closeSubpath()
    else:
        path.addRect(QRectF(x - h, y - h, size, size))
    return path


def branch_text_pose(a: QPointF, b: QPointF, p: QPointF, w: float, h: float, orientation: str,
                     offset: float) -> tuple[QPointF, QPointF, float]:
    """(posição, origem da rotação, ângulo) de um texto ``w``×``h`` no ponto ``p`` do ramo a→b.

    * ``along``: paralelo ao ramo, centrado, do lado de "cima" e sempre de pé (nunca de ponta-cabeça);
    * ``tangent``: perpendicular ao ramo, começando a ``offset`` dele;
    * ``horizontal``: como antes (centrado acima do ponto, sem girar).
    """
    dx, dy = b.x() - a.x(), b.y() - a.y()
    if orientation not in ("along", "tangent") or math.hypot(dx, dy) < 1e-9:
        origin = QPointF(w / 2, h)
        return QPointF(p.x() - w / 2, p.y() - h - offset), origin, 0.0
    ang = math.degrees(math.atan2(dy, dx)) + (90.0 if orientation == "tangent" else 0.0)
    ang = (ang + 180.0) % 360.0 - 180.0          # (-180, 180]
    if ang > 90.0:
        ang -= 180.0
    elif ang <= -90.0:
        ang += 180.0
    r = math.radians(ang)
    if orientation == "along":
        up = QPointF(math.sin(r), -math.cos(r))  # "cima" do texto depois de girar
        origin = QPointF(w / 2, h)               # meio da base encostado no ramo (+ offset)
        q = p + up * offset
    else:
        fwd = QPointF(math.cos(r), math.sin(r))
        origin = QPointF(0.0, h / 2)              # começo do texto, na altura do meio
        q = p + fwd * offset
    return q - origin, origin, ang


def symbol_clearance(p: QPointF, half_extent: float, symbols: list[tuple[QPointF, float]]) -> float:
    """Afastamento extra de um texto centrado em ``p`` (meia extensão ao longo do ramo
    ``half_extent``) para não cobrir símbolos do mesmo ramo: a metade do maior símbolo que
    cai dentro do texto; 0 se nenhum."""
    extra = 0.0
    for c, size in symbols:
        if math.hypot(c.x() - p.x(), c.y() - p.y()) < half_extent + size / 2:
            extra = max(extra, size / 2)
    return extra


class _EdgeBatch:
    """Agrupa segmentos por (cor, espessura) em poucos QGraphicsPathItem."""

    def __init__(self, cap: str = "flat") -> None:
        self.paths: dict[tuple[str, float, bool], QPainterPath] = {}
        self.cap = cap_style(cap)

    def path(self, color: str, width: float, dashed: bool = False) -> QPainterPath:
        return self.paths.setdefault((color, width, dashed), QPainterPath())

    def seg(self, color: str, width: float, a: QPointF, b: QPointF, dashed: bool = False) -> None:
        p = self.path(color, width, dashed)
        p.moveTo(a)
        p.lineTo(b)

    def arc(self, color: str, width: float, r: float, th0: float, th1: float, dashed: bool = False) -> None:
        if r <= 0:
            return
        p = self.path(color, width, dashed)
        rect = QRectF(-r, -r, 2 * r, 2 * r)
        p.arcMoveTo(rect, _qt_deg(th0))
        p.arcTo(rect, _qt_deg(th0), _qt_deg(th1) - _qt_deg(th0))

    def flush(self, scene: QGraphicsScene) -> None:
        for (color, width, dashed), path in self.paths.items():
            pen = QPen(QColor(color), width)
            pen.setCapStyle(self.cap)
            if dashed:
                pen.setDashPattern([4.0, 3.0])
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
        branch_looks: tuple[dict, dict] | None = None,
        ranges: list | None = None,
        marks: list | None = None,
    ) -> RenderResult:
        """``branch_looks`` = (ramo que termina no nó, conector que sai do nó) → ``BranchLook``;
        ``ranges`` = faixas de fundo por clado (``RangeBackground``) — ambos do iTOL."""
        self.scene.clear()
        self._edge_looks, self._node_looks = branch_looks or ({}, {})
        self._marks = list(marks or [])        # símbolos/textos do iTOL nos ramos (BranchMark)
        # faixas maiores primeiro: uma faixa dentro de outra fica por cima e continua visível
        self._ranges = sorted((r for r in (ranges or []) if r.node is not None),
                              key=lambda r: -len(r.node.leaves()))
        self.notes: list[str] = []
        self._context = context or {}
        tracks = list(columns or [])
        if CLADE_STRIP not in tracks and style.clades.outer_strip:
            tracks.insert(0, CLADE_STRIP)       # padrão: faixa de clados logo após os rótulos
        if not style.clades.outer_strip:
            tracks = [t for t in tracks if t != CLADE_STRIP]
        self._tracks = tracks
        self._columns = [t for t in tracks if isinstance(t, LeafColumn)]
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
        self._rules = ColorRules(tree, style, res.clades, meta_colors, (self._edge_looks, self._node_looks),
                                 self._groups)
        self._assign = self._rules.assign
        self._has_clades = self._rules.has_clades
        self._width_by_support = self._rules.width_by_support
        self._collapsed_names = {
            id(rc.node): rc.clade.name for rc in res.clades if rc.valid and rc.node in self._collapsed
        }
        layout = LayoutKind(style.layout)
        if layout.is_radial:
            self._render_circular(tree, style, res)
        elif layout == LayoutKind.UNROOTED:
            if self._ranges:
                self.notes.append("faixas “range” do iTOL não aparecem na árvore não enraizada")
            self._render_unrooted(tree, style, res)
        else:
            self._render_rectangular(tree, style, res)
        if style.legend.in_figure:
            cs = style.clades
            if cs.label_mode == "background":
                # a amostra mostra a cor que se vê atrás dos nomes (marca-texto)
                under = style.background or "#ffffff"
                clade_entries = [(rc.clade.name, blend(rc.color, cs.label_background_alpha, under))
                                 for rc in res.clades if rc.valid and rc.clade.visible]
            else:
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
        return propagate_meta(tree, leaf_colors)

    def _edge_pen(self, node: Node) -> tuple[str, float, bool]:
        return self._rules.edge_pen(node)

    def _node_pen(self, node: Node) -> tuple[str, float, bool]:
        return self._rules.node_pen(node)

    def _edge_color(self, node: Node) -> str:
        return self._rules.edge_color(node)

    def _node_color(self, node: Node) -> str:
        return self._rules.node_color(node)

    def _branch_color(self, owner: Node | None) -> str:
        return self._rules.branch_color(owner)

    def _label_color(self, leaf: Node) -> str:
        return self._rules.label_color(leaf)

    def _label_spec(self, leaf: Node) -> _LabelSpec:
        """Grupo de rótulo > metadados > clado > padrão (``ColorRules.label_paint``)."""
        paint = self._rules.label_paint(leaf)
        font, fm = self._leaf_font, self._leaf_fm
        lab = self.style.label
        if paint.bold != lab.bold or paint.italic != lab.italic or paint.size_scale != 1.0:
            font = QFont(self._leaf_font)
            font.setBold(paint.bold)
            font.setItalic(paint.italic)
            font.setPointSizeF(max(lab.size * paint.size_scale, 1.0))
            fm = QFontMetricsF(font)
        spec = _LabelSpec(font, paint.color, fm.horizontalAdvance(self._shown(leaf)))
        if paint.background:
            spec.bg, spec.bg_alpha = paint.background, paint.background_alpha
            spec.pad, spec.radius = paint.padding, paint.radius
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

    @staticmethod
    def _bg_local_rect(item: QGraphicsSimpleTextItem, spec: _LabelSpec, height: float,
                       length: float | None) -> QRectF:
        """Retângulo do fundo nas coordenadas do texto. ``length`` = comprimento total do
        fundo a partir do começo do rótulo (todos os fundos terminam no mesmo x/raio);
        ``None`` = só o texto mais a margem. Texto invertido (metade esquerda do círculo):
        o começo do rótulo fica do lado direito do texto, e o fundo cresce para a esquerda."""
        br = item.boundingRect()
        h = br.height()
        own = br.width() + 2 * spec.pad
        w = own if length is None else max(length, own)
        x0 = br.width() + spec.pad - w if item.transformOriginPoint().x() > 0 else -spec.pad
        return QRectF(x0, h / 2 - height / 2, w, height)

    def _label_background(self, leaf: Node, item: QGraphicsSimpleTextItem, spec: _LabelSpec,
                          max_h: float, res: RenderResult, length: float | None = None) -> QGraphicsPathItem | None:
        """Fundo (marca-texto) atrás de um rótulo já posicionado: mesma origem de
        transformação, rotação e posição do texto, então gira junto no circular.
        A altura fica limitada a ``max_h`` para não invadir as folhas vizinhas; ``length``
        estende o fundo até o fim comum (ver ``_bg_local_rect``)."""
        if not spec.bg:
            return None
        br = item.boundingRect()
        h = br.height()
        full = h + 2 * spec.pad
        height = min(full, max_h) if max_h > 0 else full
        rect = self._bg_local_rect(item, spec, height, length)
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

    def _width(self, node: Node | None) -> float:
        """Espessura do ramo que termina em ``node`` (e do conector/arco que sai dele)."""
        return self._rules.width(node)

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

    def _binary_cell(self, col: LeafColumn, names: list[str], center: QPointF, size: float) -> None:
        """Forma do iTOL (DATASET_BINARY) no centro da célula: cheia (1) ou vazada (0)."""
        got = col.shapes.get(names[0]) if len(names) == 1 else col.shape_for_group(names)
        if got is None or size <= 0:
            return
        one = names[0] if len(names) == 1 else None
        if one is not None and one in col.shape_sizes:
            size *= max(min(col.shape_sizes[one], 1.0), 0.05)
        color = col.shape_colors.get(one, col.shape_color) if one is not None else col.shape_color
        item = self._shape_item(got[0], got[1], center, size, color)
        item.setData(1, TAG_BINARY)
        item.setData(2, col.key)

    def _shape_item(self, shape: int, filled: bool, center: QPointF, size: float, color: str) -> QGraphicsPathItem:
        item = QGraphicsPathItem(shape_path(shape, center, size))
        c = QColor(color)
        line = shape in (6, 7, 8, 9)
        pen = QPen(c, max(min(size * 0.12, 1.2), 0.5) * (1.6 if line else 1.0))
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        if shape == 8:
            pen.setDashPattern([3.0, 2.0])
        elif shape == 9:
            pen.setDashPattern([1.0, 1.5])
        item.setPen(pen)
        item.setBrush(QBrush(c) if filled and not line else QBrush(Qt.BrushStyle.NoBrush))
        self.scene.addItem(item)
        return item

    def _styled_text(self, text: str, color: str, style: tuple[bool, bool, float]) -> QGraphicsSimpleTextItem:
        bold, italic, factor = style
        t = self._text(text, max(self.style.label.size * factor, 3.0), color)
        f = t.font()
        f.setBold(bold)
        f.setItalic(italic)
        t.setFont(f)
        return t

    def _text_column_width(self, col: LeafColumn) -> float:
        best = 0.0
        for leaf, text in col.texts.items():
            bold, italic, factor = col.text_styles.get(leaf, (False, False, 1.0))
            f = QFont(self._font)
            f.setPointSizeF(max(self.style.label.size * factor, 3.0))
            f.setBold(bold)
            f.setItalic(italic)
            best = max(best, QFontMetricsF(f).horizontalAdvance(text))
        return best + 6

    def _text_cell(self, col: LeafColumn, names: list[str]):  # type: ignore[no-untyped-def]
        """Texto da célula (folha, ou clado colapsado com o mesmo texto em todas)."""
        texts = {col.texts.get(n) for n in names}
        if len(texts) != 1 or None in texts:
            return None
        n = names[0]
        t = self._styled_text(texts.pop(), col.text_colors.get(n, "#202020"),
                              col.text_styles.get(n, (False, False, 1.0)))
        t.setData(1, TAG_ITOL_TEXT)
        t.setData(2, col.key)
        return t

    def _draw_marks(self, seg_of) -> None:  # type: ignore[no-untyped-def]
        """Símbolos e textos do iTOL sobre os ramos (posição 0–1 do ramo que chega ao nó).

        Símbolos primeiro: um texto que cairia sobre um símbolo do mesmo ramo é afastado do
        ramo pela metade do símbolo, além da distância mínima."""
        placed: dict[int, list[tuple[QPointF, float]]] = {}      # id(nó) -> (centro, tamanho)
        texts = []
        for m in self._marks:
            seg = seg_of(m.node)
            if seg is None:
                continue
            a, b = seg
            p = a + (b - a) * max(0.0, min(m.frac, 1.0))
            if m.kind != "symbol":
                texts.append((m, a, b, p))
                continue
            size = self.style.label.size * 1.3 * max(min(m.size, 1.0), 0.05)
            item = self._shape_item(m.shape, m.filled, p, size, m.color)
            item.setData(1, TAG_ITOL_SYMBOL)
            item.setZValue(2)
            placed.setdefault(id(m.node), []).append((p, size))
        bt = self.style.figure.branch_text
        for m, a, b, p in texts:
            t = self._styled_text(m.text, m.color, (m.bold, m.italic, m.size))
            t.setData(1, TAG_ITOL_TEXT)
            t.setZValue(2)
            br = t.boundingRect()
            # quanto o texto ocupa ao longo do ramo, a partir de p (tangente: só a altura)
            half = br.height() / 2 if bt.orientation == "tangent" else br.width() / 2
            extra = symbol_clearance(p, half, placed.get(id(m.node), []))
            pos, origin, rot = branch_text_pose(a, b, p, br.width(), br.height(), bt.orientation,
                                                bt.offset + extra)
            t.setTransformOriginPoint(origin)
            t.setRotation(rot + m.rotation)
            t.setPos(pos)
            t.setData(3, extra)
            if bt.halo:
                self._add_halo(t)

    def _add_halo(self, t: QGraphicsSimpleTextItem) -> None:
        """Contorno claro atrás do texto (filho do item: acompanha rotação e posição)."""
        f = t.font()
        path = QPainterPath()
        path.addText(0, QFontMetricsF(f).ascent(), f, t.text())
        halo = QGraphicsPathItem(path, t)
        c = QColor(self.style.background or "#ffffff")
        c.setAlphaF(0.85)
        pen = QPen(c, max(f.pointSizeF() * 0.28, 1.5))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        halo.setPen(pen)
        halo.setBrush(QBrush(c))
        halo.setFlag(QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent)
        halo.setData(1, TAG_ITOL_TEXT)
        halo.setData(0, "halo")

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

    def _merged_label_bgs_rect(self, lay, pending: dict, sy: float, res: RenderResult,  # type: ignore[no-untyped-def]
                               right: float) -> None:
        """Fundos de rótulos vizinhos de mesma cor num caminho só: entre as folhas o fundo
        vai até o meio do espaço; nas pontas, margem e cantos como antes. Todos terminam no
        mesmo x (``right``): a borda direita é reta, sem degraus."""
        for block in self._label_blocks(lay, pending):
            n = len(block.tips)
            if n == 1 and not block.before and not block.after:
                item, spec = pending[block.tips[0]]
                self._label_background(block.tips[0], item, spec, sy - 1, res,
                                       right - (item.pos().x() - spec.pad))
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
                w = max(right - x0, br.width() + 2 * spec.pad)
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

    def _merged_label_bgs_circ(self, lay, pending: dict, res: RenderResult,  # type: ignore[no-untyped-def]
                               r_out: float) -> None:
        """Circular/leque: entre folhas vizinhas o fundo é um setor com bordas radiais no
        ângulo médio; nas pontas do bloco, o retângulo arredondado girado de sempre. Todos
        vão até o mesmo raio ``r_out``: a borda externa é um arco contínuo."""
        for block in self._label_blocks(lay, pending):
            n = len(block.tips)
            if n == 1 and not block.before and not block.after:
                item, spec, start, max_h = pending[block.tips[0]]
                self._label_background(block.tips[0], item, spec, max_h, res, r_out - start)
                continue
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            for i, leaf in enumerate(block.tips):
                item, spec, start, max_h = pending[leaf]
                th = lay.pos[leaf][1]
                a, b = lay.span[leaf]
                r_in = start
                lo_kind = self._side(i, n, block.before, True)
                hi_kind = self._side(i, n, block.after, False)
                lo = {"inner": a, "neighbor": a - SEAM_OVERLAP / max(r_in, 1.0), "outer": th}[lo_kind]
                hi = {"inner": b, "neighbor": b, "outer": th}[hi_kind]
                if "outer" in (lo_kind, hi_kind):
                    br = item.boundingRect()
                    h = br.height()
                    height = min(h + 2 * spec.pad, max_h)
                    local = QPainterPath()
                    rect = self._bg_local_rect(item, spec, height, r_out - start)
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

    def _track_extent(self, track, cell_w: float, margin: bool = True) -> float:  # type: ignore[no-untyped-def]
        """Largura (px) ocupada pela trilha: coluna no retangular, anel no circular."""
        if track == CLADE_STRIP:
            return self.style.clades.strip_width
        m = getattr(track, "margin", 0.0) if margin else 0.0
        if isinstance(track, LeafColumn) and track.kind == "text":
            return m + (track.width or self._text_column_width(track))
        if isinstance(track, BarTrack):
            return m + track.width + self._value_text_width(track)
        if isinstance(track, StackedTrack):
            return m + track.width
        return m + (track.width or cell_w)

    def _bar_color(self, track: BarTrack, node: Node, names: list[str]) -> str:
        if track.color_mode == "clade":
            rc = self._clade_of(node)
            return rc.color if rc is not None else self.style.clades.neutral_color
        if track.color_mode == "metadata":
            if len(names) == 1:
                return track.colors.get(names[0], track.color)
            return self._rules.meta_node.get(node, track.color)
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
            x += getattr(track, "margin", 0.0) if track != CLADE_STRIP else 0.0
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
                x += self._track_extent(track, 0, margin=False) + pad
            elif isinstance(track, StackedTrack):
                self._stacked_rect(track, lay, x, sy, top, bottom)
                x += track.width + pad
            elif track.kind == "text":
                cw = self._track_extent(track, 0, margin=False)
                for node, names in self._tips(lay):
                    t = self._text_cell(track, names)
                    if t is not None:
                        t.setPos(x + 3, lay.pos[node][1] * sy - t.boundingRect().height() / 2)
                if hm.show_headers:
                    self._column_header(track.header, x, cw, top, horizontal_ok=True)
                x += cw
            elif track.kind == "binary":
                cw = track.width if track.width else sy * hm.cell_width
                for node, names in self._tips(lay):
                    a, b = lay.span[node]
                    size = min(cw, (b - a) * sy) * 0.7
                    self._binary_cell(track, names, QPointF(x + cw / 2, lay.pos[node][1] * sy), size)
                self._column_header(track.header, x, cw, top, rotation=track.header_rotation)
                x += cw
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
                if hm.show_headers or track.always_header:
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
        self._axis_rect(track.key, x0, w, bottom, track.axis_ticks(), track.frac)
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
                c, w, d = self._edge_pen(node)
                edges.seg(c, w, start, p, d)
            if node in self._collapsed:
                continue
            if node.children and not slanted:
                top, bot = pt(node.children[0]), pt(node.children[-1])
                c, w, d = self._node_pen(node)
                edges.seg(c, w, QPointF(p.x(), top.y()), QPointF(p.x(), bot.y()), d)
        edges.flush(self.scene)

        def seg_rect(node: Node):  # type: ignore[no-untyped-def]
            if node not in res.node_points:
                return None
            p = res.node_points[node]
            if node.parent is None:
                return p, p
            pp = pt(node.parent)
            return (pp if slanted else QPointF(pp.x(), p.y())), p

        self._draw_marks(seg_rect)
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
        text_end = tree_right             # maior fim de texto (folhas e colapsados)
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
                text_end = max(text_end, t.sceneBoundingRect().right())
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
            text_end = max(text_end, item.pos().x() + item.boundingRect().width() + spec.pad)
            if spec.bg:
                label_bgs[leaf] = (item, spec)
        if label_bgs:
            # todos os fundos terminam no mesmo x: o maior fim de texto + folga
            bg_right = text_end + max(cs.label_background_gap, 0.0)
            label_right = max(label_right, bg_right)
            if self._merge:
                self._merged_label_bgs_rect(lay, label_bgs, sy, res, bg_right)
            else:
                for leaf, (item, spec) in label_bgs.items():
                    self._label_background(leaf, item, spec, sy - 1, res, bg_right - (item.pos().x() - spec.pad))

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
        if self._ranges:          # faixas "range" do iTOL (TREE_COLORS): como o fundo de clado
            groups = (self._clade_bg_groups(lay, self._ranges) if self._merge
                      else [(r.color, [r], set()) for r in self._ranges])
            for color, group, lead_in in groups:
                path = QPainterPath()
                path.setFillRule(Qt.FillRule.WindingFill)
                for rg in group:
                    y0, y1 = y_range(rg.node)
                    y0 -= SEAM_OVERLAP if id(rg) in lead_in else 0.0
                    x0 = pt(rg.node).x() - pad / 2
                    path.addRect(QRectF(x0, y0, x - pad / 2 - x0, y1 - y0))
                self._fill(path, color, group[0].alpha, TAG_RANGE_BG, -2.5)
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
        bg_gap = max(cs.label_background_gap, 0.0) if any(sp.bg for sp in specs.values()) else 0.0

        geom = circular_geometry(
            lay,
            font_size=style.label.size,
            leaf_spacing=style.leaf_spacing,
            base_width=style.base_width,
            branch_scale=style.branch_scale,
            align_tips=style.align_tips,
            ring_widths=tuple(ring_widths),
            # sem alinhar, os anéis vêm depois dos rótulos (e do fim comum dos fundos)
            inner_extent=0.0 if style.align_tips else max_label_w + pad + bg_gap,
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
                c, w, d = self._edge_pen(node)
                edges.seg(c, w, pt(rad(node.parent), th), pt(r, th), d)
            if node in self._collapsed:
                continue
            if node.children:
                c, w, d = self._node_pen(node)
                edges.arc(c, w, r, lay.pos[node.children[0]][1], lay.pos[node.children[-1]][1], d)
        edges.flush(self.scene)

        def seg_circ(node: Node):  # type: ignore[no-untyped-def]
            if node not in res.node_points:
                return None
            if node.parent is None:
                return res.node_points[node], res.node_points[node]
            th = lay.pos[node][1]
            return pt(rad(node.parent), th), pt(rad(node), th)

        self._draw_marks(seg_circ)
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
        text_end = 0.0                    # maior raio de fim de texto (folhas e colapsados)
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
            text_end = max(text_end, start + spec.extent)
            if spec.bg:
                # corda entre folhas vizinhas na borda interna do fundo
                a, b = lay.span[leaf]
                chord = 2 * start * math.sin(max(b - a, 0.0) / 2)
                circ_bgs[leaf] = (item, spec, start, max(chord - 1, 2.0))

        if style.label.show:
            for node, far in lay.collapsed.items():
                th = lay.pos[node][1]
                start = geom.label_radius if geom.align_tips else far * sr + pad
                t = self._text(self._collapsed_label(node), color=self._branch_color(node))
                t.setData(1, TAG_COLLAPSED)
                self._rotate_radial(t, pt(start, th), th)
                text_end = max(text_end, start + t.boundingRect().width())

        # todos os fundos dos nomes vão até o mesmo raio: o maior fim de texto + folga
        bg_outer = text_end + bg_gap
        if circ_bgs:
            if self._merge:
                self._merged_label_bgs_circ(lay, circ_bgs, res, bg_outer)
            else:
                for leaf, (item, spec, start, max_h) in circ_bgs.items():
                    self._label_background(leaf, item, spec, max_h, res, bg_outer - start)

        # raio externo ocupado pelos rótulos (ou anéis)
        label_outer = (geom.label_radius if geom.align_tips
                       else geom.tip_ring + self._marker / 2 + pad) + max_label_w
        if circ_bgs:
            label_outer = max(label_outer, bg_outer)
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
            if track != CLADE_STRIP:
                r0 += getattr(track, "margin", 0.0)
            if track == CLADE_STRIP:
                for rc in visible:
                    th0, th1 = th_range(rc.node)
                    self._fill(annular_sector(r0, r1, th0, th1), rc.color, 1.0, TAG_CLADE_STRIP, 0)
            elif isinstance(track, BarTrack):
                self._bars_circ(track, lay, r0, root_span, pt)
            elif isinstance(track, StackedTrack):
                self._stacked_circ(track, lay, r0, pt)
            elif track.kind == "text":
                for node, names in self._tips(lay):
                    t = self._text_cell(track, names)
                    if t is not None:
                        a, b = lay.span[node]
                        self._rotate_radial(t, pt(r0 + 3, (a + b) / 2), (a + b) / 2)
            elif track.kind == "binary":
                for node, names in self._tips(lay):
                    a, b = lay.span[node]
                    rm = (r0 + r1) / 2
                    size = min(r1 - r0, 2 * rm * math.sin(max(b - a, 1e-6) / 2)) * 0.7
                    self._binary_cell(track, names, pt(rm, (a + b) / 2), size)
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
        if self._ranges:          # faixas "range" do iTOL (TREE_COLORS): como o fundo de clado
            groups = (self._clade_bg_groups(lay, self._ranges) if self._merge
                      else [(r.color, [r], set()) for r in self._ranges])
            for color, group, lead_in in groups:
                path = QPainterPath()
                path.setFillRule(Qt.FillRule.WindingFill)
                for rg in group:
                    th0, th1 = th_range(rg.node)
                    r0 = max(rad(rg.node) - pad / 2, 0.0)
                    if id(rg) in lead_in:
                        th0 -= SEAM_OVERLAP / max(r0, 1.0)
                    path.addPath(annular_sector(r0, outer + pad / 2, th0, th1))
                self._fill(path, color, group[0].alpha, TAG_RANGE_BG, -2.5)
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
                c, w, d = self._edge_pen(node)
                edges.seg(c, w, pt(node.parent), p, d)
        edges.flush(self.scene)
        self._draw_marks(lambda n: None if n not in res.node_points else (
            (res.node_points[n], res.node_points[n]) if n.parent is None else (pt(n.parent), res.node_points[n])))
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
        pending = []
        for leaf in lay.leaf_order:
            p = pt(leaf)
            res.leaf_points[leaf.name] = p
            if not style.label.show:
                continue
            ang = lay.edge_angle(leaf) if leaf.parent is not None else 0.0
            spec = self._label_spec(leaf)
            item = self._leaf_text(leaf, spec)
            pending.append((leaf, p, ang, spec, item, pad + self._marker / 2 + spec.pad))
        placed = self._unrooted_label_positions(pending, row_h) if style.unrooted.avoid_overlap else {}
        for leaf, p, ang, spec, item, start in pending:
            where = placed.get(leaf.name)
            if where is not None:
                ang, start = where.angle, where.offset + spec.pad
                if where.guide:
                    self._label_guide(p, ang, start - spec.pad)
            anchor = p + QPointF(math.cos(ang), math.sin(ang)) * start
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

    def _unrooted_label_positions(self, pending: list, row_h: float) -> dict:  # type: ignore[type-arg]
        """Ajuste dos rótulos (só os textos se movem; folhas e ramos ficam onde estão)."""
        from jabuti.layout.label_placement import LabelBox, place_labels

        boxes = []
        for leaf, p, ang, spec, item, start in pending:
            br = item.boundingRect()
            boxes.append(LabelBox(leaf.name, p.x(), p.y(), ang, start - spec.pad, br.width() + 2 * spec.pad,
                                  min(br.height() + 2 * spec.pad, max(row_h, br.height()))))
        out = {pl.key: pl for pl in place_labels(boxes)}
        self.label_moves = sum(1 for b in boxes if (out[b.key].angle, out[b.key].offset) != (b.angle, b.offset))
        unresolved = sum(1 for pl in out.values() if not pl.resolved)
        if unresolved:
            self.notes.append(f"{unresolved} rótulo(s) sem lugar livre na árvore não enraizada")
        return out

    def _label_guide(self, leaf_point: QPointF, ang: float, start: float) -> None:
        """Linha fina da folha até o rótulo afastado."""
        u = QPointF(math.cos(ang), math.sin(ang))
        path = QPainterPath()
        path.moveTo(leaf_point + u * (self._marker / 2 + 1.0))
        path.lineTo(leaf_point + u * max(start - 1.0, self._marker / 2 + 1.0))
        item = QGraphicsPathItem(path)
        pen = QPen(QColor("#9a9a9a"), 0.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        item.setPen(pen)
        item.setZValue(-0.5)
        item.setData(1, TAG_LABEL_GUIDE)
        self.scene.addItem(item)

    def _fan_headers(self, lay, geom: CircGeometry, pt) -> None:  # type: ignore[no-untyped-def]
        """Leque: nomes das colunas/anéis no vão, logo antes do início do arco, um por anel."""
        if 2 * math.pi - lay.arc < math.radians(15) or not (self.style.heatmap.show_headers or any(
                isinstance(t, LeafColumn) and t.always_header for t in self._ring_tracks)):
            return
        th = lay.start
        u = th - math.pi / 2                    # tangente apontando para dentro do vão
        for i, track in enumerate(self._ring_tracks):
            if track == CLADE_STRIP:
                continue
            r0, r1 = geom.ring_bounds(i)
            r0 += getattr(track, "margin", 0.0)
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
                ticks = list(group.ticks)
                # extremos sempre; os do meio só se não encostarem em outro rótulo
                order = [0, len(ticks) - 1, *range(1, len(ticks) - 1)] if len(ticks) > 1 else list(range(len(ticks)))
                placed: list[tuple[float, float]] = []
                for k in order:
                    frac, text = ticks[k]
                    lab = self._text(text, small, "#202020")
                    br = lab.boundingRect()
                    tx = min(max(frac * bar_w - br.width() / 2, 0), bar_w - br.width())
                    if any(tx < b + 2 and tx + br.width() > a - 2 for a, b in placed):
                        self.scene.removeItem(lab)
                        continue
                    placed.append((tx, tx + br.width()))
                    lab.setPos(tx, y)
                    items.append(lab)
                    lh = max(lh, br.height())
                y += lh + 1
            for i, (text, color) in enumerate(group.entries):
                label = self._text(text, size, "#202020")
                lh = label.boundingRect().height()
                shape = group.shape_at(i)
                if color is not None and shape is not None and shape[0] != 1:
                    # mesma forma desenhada na coluna (símbolo, presença/ausência)
                    mark = self._shape_item(shape[0], shape[1], QPointF(sw / 2, y + lh / 2), sw, color)
                    mark.setData(3, shape)
                    items.append(mark)
                    label.setPos(sw + size * 0.5, y)
                elif color is not None:
                    square = QGraphicsRectItem(0, y + (lh - sw) / 2, sw, sw)
                    filled = shape is None or shape[1]
                    square.setBrush(QBrush(QColor(color)) if filled else QBrush(Qt.BrushStyle.NoBrush))
                    square.setPen(QPen(QColor("#777777" if filled else color), 0.5 if filled else 1.0))
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
