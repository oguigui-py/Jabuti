"""Layout retangular: x = distância da raiz, y = ordem das folhas."""

from __future__ import annotations

from dataclasses import dataclass, field

from jabuti.models.tree import Node, Tree


@dataclass
class RectLayout:
    """Coordenadas em unidades de árvore (x) e índices de folha (y)."""

    pos: dict[Node, tuple[float, float]] = field(default_factory=dict)
    leaf_order: list[Node] = field(default_factory=list)
    max_x: float = 0.0
    uses_lengths: bool = True


def node_depths(tree: Tree, use_lengths: bool = True) -> tuple[dict[Node, float], bool]:
    """Distância de cada nó à raiz.

    Sem comprimentos (ou ``use_lengths=False``) gera cladograma com folhas alinhadas.
    """
    has_lengths = use_lengths and any(
        n.length is not None for n in tree.root.traverse_preorder() if n is not tree.root
    )
    depth: dict[Node, float] = {}
    if has_lengths:
        for node in tree.root.traverse_preorder():
            if node.parent is None:
                depth[node] = 0.0
            else:
                depth[node] = depth[node.parent] + max(node.length or 0.0, 0.0)
        return depth, True
    # cladograma: altura = nº máximo de passos até uma folha
    height: dict[Node, int] = {}
    for node in tree.root.traverse_postorder():
        height[node] = 0 if node.is_leaf else 1 + max(height[c] for c in node.children)
    total = height[tree.root]
    for node in tree.root.traverse_preorder():
        depth[node] = float(total - height[node])
    return depth, False


def rectangular_layout(tree: Tree, use_lengths: bool = True) -> RectLayout:
    depth, used = node_depths(tree, use_lengths)
    lay = RectLayout(uses_lengths=used)
    y: dict[Node, float] = {}
    for node in tree.root.traverse_postorder():
        if node.is_leaf:
            y[node] = float(len(lay.leaf_order))
            lay.leaf_order.append(node)
        else:
            y[node] = (y[node.children[0]] + y[node.children[-1]]) / 2
    for node, yy in y.items():
        lay.pos[node] = (depth[node], yy)
    lay.max_x = max(depth.values(), default=0.0)
    return lay
