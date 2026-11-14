"""Layout não enraizado (radial): algoritmo equal-angle e refinamento "equal daylight".

Equal-angle (Felsenstein, *Inferring Phylogenies*, cap. 34): cada subárvore recebe uma fatia
angular proporcional ao seu nº de folhas e os ramos saem no meio da fatia, com comprimento
proporcional ao do ramo. Garante que ramos não se cruzam, mas costuma deixar folhas
"amontoadas"; o refinamento equal daylight gira as subárvores em volta de cada nó interno
para igualar os vãos ("daylight") entre elas.

Coordenadas em unidades de comprimento de ramo; clados colapsados contam como uma ponta.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from jabuti.layout.rectangular import COLLAPSED_SLOTS, visible_nodes
from jabuti.models.tree import Node, Tree

MAX_DAYLIGHT_LEAVES = 2000
DAYLIGHT_PASSES = 5


@dataclass
class UnrootedLayout:
    pos: dict[Node, tuple[float, float]] = field(default_factory=dict)   # só nós visíveis
    wedge: dict[Node, tuple[float, float]] = field(default_factory=dict) # fatia angular (equal-angle)
    leaf_order: list[Node] = field(default_factory=list)                  # folhas visíveis
    collapsed: dict[Node, float] = field(default_factory=dict)            # nó -> comprimento até a folha mais distante
    uses_lengths: bool = True
    extent: float = 0.0             # maior distância de um nó à origem

    def edge_angle(self, node: Node) -> float:
        """Direção do ramo pai → nó."""
        (x0, y0), (x1, y1) = self.pos[node.parent], self.pos[node]
        if abs(x1 - x0) < 1e-12 and abs(y1 - y0) < 1e-12:
            a0, a1 = self.wedge[node]
            return (a0 + a1) / 2
        return math.atan2(y1 - y0, x1 - x0)


def _edge_len(node: Node, use_lengths: bool) -> float:
    if not use_lengths:
        return 1.0
    return max(node.length or 0.0, 0.0)


def unrooted_layout(tree: Tree, use_lengths: bool = True, collapsed: set[Node] | frozenset[Node] = frozenset(),
                    daylight: bool = False, rotation: float = 0.0, mirror: bool = False) -> UnrootedLayout:
    has_lengths = use_lengths and any(n.length is not None for n in tree.root.traverse_preorder()
                                      if n is not tree.root)
    lay = UnrootedLayout(uses_lengths=has_lengths)
    visible = visible_nodes(tree, collapsed)
    vis = set(visible)
    weight: dict[Node, float] = {}
    for node in tree.root.traverse_postorder():
        if node not in vis:
            continue
        if node in collapsed:
            weight[node] = COLLAPSED_SLOTS
        elif node.is_leaf:
            weight[node] = 1.0
        else:
            weight[node] = sum(weight[c] for c in node.children)
    lay.pos[tree.root] = (0.0, 0.0)
    lay.wedge[tree.root] = (0.0, 2 * math.pi)
    for node in visible:
        if node is tree.root:
            pass
        else:
            a0, a1 = lay.wedge[node]
            mid = (a0 + a1) / 2
            px, py = lay.pos[node.parent]
            d = _edge_len(node, has_lengths)
            lay.pos[node] = (px + d * math.cos(mid), py + d * math.sin(mid))
        if node in collapsed or node.is_leaf:
            continue
        a0, a1 = lay.wedge[node]
        total = weight[node] or 1.0
        cur = a0
        for c in node.children:
            span = (a1 - a0) * weight[c] / total
            lay.wedge[c] = (cur, cur + span)
            cur += span
    lay.leaf_order = [n for n in visible if n.is_leaf]
    for node in collapsed:
        if node in vis:
            far = 0.0
            for leaf in node.leaves():
                d, n = 0.0, leaf
                while n is not node:
                    d += _edge_len(n, has_lengths)
                    n = n.parent  # type: ignore[assignment]
                far = max(far, d)
            lay.collapsed[node] = far
    if daylight and len(lay.leaf_order) <= MAX_DAYLIGHT_LEAVES:
        _equal_daylight(tree, lay, vis, collapsed)
    _transform(lay, rotation, mirror)
    lay.extent = max((math.hypot(x, y) for x, y in lay.pos.values()), default=0.0)
    return lay


def _transform(lay: UnrootedLayout, rotation: float, mirror: bool) -> None:
    """Espelha (eixo horizontal) e gira as coordenadas — o texto é posicionado depois, legível."""
    th = math.radians(rotation)
    c, s = math.cos(th), math.sin(th)
    for node, (x, y) in list(lay.pos.items()):
        if mirror:
            y = -y
        lay.pos[node] = (x * c - y * s, x * s + y * c)
    for node, (a0, a1) in list(lay.wedge.items()):
        if mirror:
            a0, a1 = -a1, -a0
        lay.wedge[node] = (a0 + th, a1 + th)


# --------------------------------------------------------------- daylight
def _subtree(node: Node, vis: set[Node], collapsed) -> list[Node]:  # type: ignore[no-untyped-def]
    out, stack = [], [node]
    while stack:
        n = stack.pop()
        out.append(n)
        if n not in collapsed:
            stack.extend(c for c in n.children if c in vis)
    return out


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _equal_daylight(tree: Tree, lay: UnrootedLayout, vis: set[Node], collapsed) -> None:  # type: ignore[no-untyped-def]
    """Gira as subárvores em volta de cada nó interno para igualar os vãos entre elas."""
    all_nodes = [n for n in tree.root.traverse_preorder() if n in vis]
    tips = {n for n in all_nodes if n.is_leaf or n in collapsed}
    for _ in range(DAYLIGHT_PASSES):
        moved = 0.0
        for v in all_nodes:
            if v in tips:
                continue
            groups: list[list[Node]] = [_subtree(c, vis, collapsed) for c in v.children if c in vis]
            if v.parent is not None:
                below = set(_subtree(v, vis, collapsed))
                groups.append([n for n in all_nodes if n not in below])
            if len(groups) < 2:
                continue
            vx, vy = lay.pos[v]
            arcs = []                      # (início, fim, grupo) em ângulos absolutos em volta de v
            for g in groups:
                pts = [lay.pos[n] for n in g if n in tips]
                if not pts:
                    continue
                angs = [math.atan2(y - vy, x - vx) for x, y in pts]
                ref = math.atan2(sum(math.sin(a) for a in angs), sum(math.cos(a) for a in angs))
                rel = [_wrap(a - ref) for a in angs]
                arcs.append((ref + min(rel), ref + max(rel), g))
            if len(arcs) < 2:
                continue
            extent = sum(b - a for a, b, _g in arcs)
            gap = (2 * math.pi - extent) / len(arcs)
            if gap <= 0:
                continue
            arcs.sort(key=lambda t: t[0])
            cur = arcs[0][1]
            for a, b, g in arcs[1:]:
                target = cur + gap
                rot = target - a
                if abs(rot) > 1e-9:
                    moved = max(moved, abs(rot))
                    c, s = math.cos(rot), math.sin(rot)
                    for n in g:
                        x, y = lay.pos[n]
                        dx, dy = x - vx, y - vy
                        lay.pos[n] = (vx + dx * c - dy * s, vy + dx * s + dy * c)
                        if n in lay.wedge:
                            w0, w1 = lay.wedge[n]
                            lay.wedge[n] = (w0 + rot, w1 + rot)
                cur = target + (b - a)
        if moved < 1e-4:
            break
