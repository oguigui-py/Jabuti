"""Layout circular: raio = distância da raiz, ângulo = ordem das folhas."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from jabuti.layout.rectangular import node_depths
from jabuti.models.tree import Node, Tree


@dataclass
class CircLayout:
    """``pos[node] = (raio_em_unidades_de_árvore, ângulo_em_radianos)``."""

    pos: dict[Node, tuple[float, float]] = field(default_factory=dict)
    leaf_order: list[Node] = field(default_factory=list)
    max_r: float = 0.0
    uses_lengths: bool = True


def circular_layout(tree: Tree, use_lengths: bool = True, arc_degrees: float = 360.0) -> CircLayout:
    depth, used = node_depths(tree, use_lengths)
    lay = CircLayout(uses_lengths=used)
    leaves = [n for n in tree.root.traverse_postorder() if n.is_leaf]
    n = len(leaves)
    arc = math.radians(min(max(arc_degrees, 10.0), 360.0))
    # círculo completo: passo uniforme (inclusive entre a última e a primeira folha);
    # leque parcial: folhas nas duas extremidades do arco
    full = arc_degrees >= 359.999
    step = arc / n if full else arc / max(n - 1, 1)
    theta: dict[Node, float] = {}
    for i, leaf in enumerate(leaves):
        theta[leaf] = i * step
    lay.leaf_order = leaves
    for node in tree.root.traverse_postorder():
        if not node.is_leaf:
            theta[node] = (theta[node.children[0]] + theta[node.children[-1]]) / 2
    for node, th in theta.items():
        lay.pos[node] = (depth[node], th)
    lay.max_r = max(depth.values(), default=0.0)
    return lay
