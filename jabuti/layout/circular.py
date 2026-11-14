"""Layout circular: raio = distância da raiz, ângulo = ordem das folhas."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from jabuti.layout.rectangular import collapsed_far, node_depths, tip_slots
from jabuti.models.tree import Node, Tree


@dataclass
class CircLayout:
    """``pos[node] = (raio_em_unidades_de_árvore, ângulo_em_radianos)`` (só nós visíveis)."""

    pos: dict[Node, tuple[float, float]] = field(default_factory=dict)
    leaf_order: list[Node] = field(default_factory=list)       # folhas visíveis
    max_r: float = 0.0
    uses_lengths: bool = True
    span: dict[Node, tuple[float, float]] = field(default_factory=dict)  # faixa angular ocupada
    collapsed: dict[Node, float] = field(default_factory=dict)  # nó -> raio da folha mais distante
    n_slots: float = 0.0
    arc: float = 2 * math.pi        # ângulo total ocupado (rad)
    start: float = 0.0              # ângulo onde o arco começa (rad)

    @property
    def full(self) -> bool:
        return self.arc >= 2 * math.pi - 1e-9


def circular_layout(
    tree: Tree,
    use_lengths: bool = True,
    arc_degrees: float = 360.0,
    collapsed: set[Node] | frozenset[Node] = frozenset(),
    start_degrees: float = 0.0,
) -> CircLayout:
    depth, used = node_depths(tree, use_lengths)
    lay = CircLayout(uses_lengths=used)
    center, span, leaves, total = tip_slots(tree, collapsed)
    arc = math.radians(min(max(arc_degrees, 10.0), 360.0))
    full = arc_degrees >= 359.999
    lay.leaf_order = leaves
    lay.n_slots = total
    lay.arc = 2 * math.pi if full else arc
    if full:
        # círculo completo: passo uniforme (inclusive entre a última e a primeira posição)
        step = arc / total
        for node, c in center.items():
            lay.pos[node] = (depth[node], c * step)
        lay.span = {n: (a * step, b * step) for n, (a, b) in span.items()}
    else:
        # leque: as faixas das folhas preenchem exatamente o arco (nada no vão)
        step = arc / max(total, 1)
        start = math.radians(start_degrees)
        lay.start = start

        def ang(x: float) -> float:
            return start + (x + 0.5) * step

        for node, c in center.items():
            lay.pos[node] = (depth[node], ang(c))
        lay.span = {n: (ang(a), ang(b)) for n, (a, b) in span.items()}
    lay.collapsed = collapsed_far(depth, collapsed)
    lay.max_r = max(depth.values(), default=0.0)
    return lay


# --------------------------------------------------------------------------
# Geometria em pixels (fonte única de verdade para os anéis)
# --------------------------------------------------------------------------
@dataclass
class CircGeometry:
    """Raios em pixels de cena, todos medidos a partir da raiz (centro)."""

    scale: float           # px por unidade de comprimento de ramo
    tip_ring: float        # anel externo: onde todas as pontas terminam (se alinhadas)
    rings_start: float     # início da área de anéis de anotação (Fase 2)
    rings_end: float       # fim da área de anéis de anotação
    label_radius: float    # onde os rótulos alinhados começam
    align_tips: bool
    ring_widths: tuple[float, ...] = ()
    ring_gap: float = 2.0

    def ring_bounds(self, i: int) -> tuple[float, float]:
        """Raio interno e externo do i-ésimo anel de anotação."""
        r0 = self.rings_start + sum(self.ring_widths[:i]) + self.ring_gap * i
        return r0, r0 + self.ring_widths[i]

    def tip_radius(self, lay: CircLayout, node: Node) -> float:
        """Fim real do ramo do nó (proporcional ao comprimento)."""
        return lay.pos[node][0] * self.scale

    def leaf_end_radius(self, lay: CircLayout, leaf: Node) -> float:
        """Raio final da folha: o anel externo quando alinhado, senão a ponta do ramo."""
        return self.tip_ring if self.align_tips else self.tip_radius(lay, leaf)


def outer_ring_radius(
    n_leaves: int,
    font_size: float,
    leaf_spacing: float,
    base_width: float,
    branch_scale: float,
    arc: float = 2 * math.pi,
) -> float:
    """Raio (px) do anel externo das pontas.

    Única função que define esse raio: o heatmap e as faixas de cor da Fase 2
    são desenhados em anéis concêntricos a partir dele. Nunca fica menor que o
    necessário para os rótulos não se sobreporem.
    """
    min_r = n_leaves * font_size * leaf_spacing / max(arc, 1e-6)   # leque: arco menor, raio maior
    return max(base_width * 0.5 * branch_scale, min_r)


def circular_geometry(
    lay: CircLayout,
    font_size: float,
    leaf_spacing: float,
    base_width: float,
    branch_scale: float,
    align_tips: bool = True,
    ring_widths: tuple[float, ...] = (),
    ring_gap: float = 2.0,
    inner_extent: float = 0.0,
    marker: float = 0.0,
) -> CircGeometry:
    """Raios do desenho circular.

    ``inner_extent``: espaço extra entre o anel das pontas e os anéis de anotação
    (usado quando os rótulos ficam nas pontas, sem alinhamento, para não cobrir os anéis).
    ``marker``: tamanho do símbolo desenhado na ponta (empurra anéis e rótulos para fora).
    """
    tip_ring = outer_ring_radius(math.ceil(lay.n_slots), font_size, leaf_spacing, base_width, branch_scale,
                                 lay.arc)
    scale = tip_ring / lay.max_r if lay.max_r > 0 else 1.0
    pad = font_size * 0.5
    after_tip = tip_ring + marker / 2
    rings_start = after_tip + ((pad + inner_extent) if ring_widths else 0.0)
    rings_end = rings_start + sum(ring_widths) + ring_gap * max(len(ring_widths) - 1, 0)
    return CircGeometry(
        scale=scale,
        tip_ring=tip_ring,
        rings_start=rings_start,
        rings_end=rings_end,
        label_radius=rings_end + pad,
        align_tips=align_tips,
        ring_widths=tuple(ring_widths),
        ring_gap=ring_gap,
    )
