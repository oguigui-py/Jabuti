"""Layout retangular: x = distância da raiz, y = ordem das folhas."""

from __future__ import annotations

from dataclasses import dataclass, field

from jabuti.models.tree import Node, Tree


@dataclass
class RectLayout:
    """Coordenadas em unidades de árvore (x) e posições de folha (y).

    Só contém nós visíveis: descendentes de nós colapsados ficam de fora.
    """

    pos: dict[Node, tuple[float, float]] = field(default_factory=dict)
    leaf_order: list[Node] = field(default_factory=list)       # folhas visíveis
    max_x: float = 0.0
    uses_lengths: bool = True
    span: dict[Node, tuple[float, float]] = field(default_factory=dict)  # faixa y ocupada
    collapsed: dict[Node, float] = field(default_factory=dict)  # nó -> x da folha mais distante
    n_slots: float = 0.0


COLLAPSED_SLOTS = 2.0  # posições ocupadas por um clado colapsado (triângulo)


def visible_nodes(tree: Tree, collapsed: set[Node] | frozenset[Node] = frozenset()) -> list[Node]:
    """Pré-ordem sem descer em nós colapsados (que aparecem como pontas)."""
    out: list[Node] = []
    stack = [tree.root]
    while stack:
        node = stack.pop()
        out.append(node)
        if node not in collapsed:
            stack.extend(reversed(node.children))
    return out


def tip_slots(
    tree: Tree, collapsed: set[Node] | frozenset[Node] = frozenset(), slots: float = COLLAPSED_SLOTS
) -> tuple[dict[Node, float], dict[Node, tuple[float, float]], list[Node], float]:
    """Centro e faixa (em posições) de cada nó visível.

    Folha ocupa 1 posição, clado colapsado ocupa ``slots``. Centro da folha i = i.
    Devolve (centro, faixa, folhas visíveis, total de posições).
    """
    center: dict[Node, float] = {}
    span: dict[Node, tuple[float, float]] = {}
    leaves: list[Node] = []
    cum = 0.0
    visible = set(visible_nodes(tree, collapsed))
    stack: list[tuple[Node, bool]] = [(tree.root, False)]
    while stack:
        node, done = stack.pop()
        is_tip = node.is_leaf or node in collapsed
        if is_tip:
            s = 1.0 if node.is_leaf else slots
            center[node] = cum + (s - 1) / 2
            span[node] = (cum - 0.5, cum + s - 0.5)
            cum += s
            if node.is_leaf:
                leaves.append(node)
        elif done:
            first, last = node.children[0], node.children[-1]
            center[node] = (center[first] + center[last]) / 2
            span[node] = (span[first][0], span[last][1])
        else:
            stack.append((node, True))
            stack.extend((c, False) for c in reversed(node.children) if c in visible)
    return center, span, leaves, cum


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


def collapsed_far(depth: dict[Node, float], collapsed: set[Node] | frozenset[Node]) -> dict[Node, float]:
    """Distância da folha mais distante de cada clado colapsado (fim do triângulo)."""
    return {n: max(depth[l] for l in n.leaves()) for n in collapsed}


def rectangular_layout(
    tree: Tree, use_lengths: bool = True, collapsed: set[Node] | frozenset[Node] = frozenset()
) -> RectLayout:
    depth, used = node_depths(tree, use_lengths)
    lay = RectLayout(uses_lengths=used)
    center, span, leaves, total = tip_slots(tree, collapsed)
    lay.leaf_order = leaves
    lay.span = span
    lay.n_slots = total
    for node, yy in center.items():
        lay.pos[node] = (depth[node], yy)
    lay.collapsed = collapsed_far(depth, collapsed)
    lay.max_x = max(depth.values(), default=0.0)
    return lay
