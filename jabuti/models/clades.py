"""Clados: detecção automática (k, suporte, distância), definição manual e resolução.

Clados são guardados por conjunto de nomes de folhas, não por objeto ``Node``:
assim sobrevivem a reenraizamentos e podem ir para presets JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from jabuti.layout.rectangular import node_depths
from jabuti.models.tree import Node, Tree, support_value

CladeSource = Literal["auto", "manual"]


@dataclass
class Clade:
    name: str
    leaves: frozenset[str]
    color: str | None = None        # None = cor da paleta pela posição
    visible: bool = True
    source: CladeSource = "auto"


@dataclass
class ResolvedClade:
    clade: Clade
    node: Node | None               # MRCA na árvore atual
    color: str
    valid: bool                     # False: folhas ausentes ou não monofilético
    problem: str = ""


@dataclass
class CladeSet:
    """Lista ordenada de clados + modo da última detecção automática."""

    clades: list[Clade] = field(default_factory=list)
    auto_mode: str | None = None

    def replace_auto(self, groups: list[frozenset[str]], mode: str, prefix: str = "Clado") -> None:
        manual = [c for c in self.clades if c.source == "manual"]
        auto = [Clade(f"{prefix} {i + 1}", g) for i, g in enumerate(groups)]
        self.clades = auto + manual
        self.auto_mode = mode

    def clear_auto(self) -> None:
        self.clades = [c for c in self.clades if c.source == "manual"]
        self.auto_mode = None

    def add_manual(self, leaves: frozenset[str], name: str | None = None, color: str | None = None) -> Clade:
        existing = self.find(leaves)
        if existing is not None:
            existing.source = "manual"
            if name:
                existing.name = name
            if color:
                existing.color = color
            return existing
        n = sum(1 for c in self.clades if c.source == "manual") + 1
        clade = Clade(name or f"Clado manual {n}", leaves, color, True, "manual")
        self.clades.append(clade)
        return clade

    def find(self, leaves: frozenset[str]) -> Clade | None:
        return next((c for c in self.clades if c.leaves == leaves), None)

    def remove(self, clade: Clade) -> None:
        self.clades = [c for c in self.clades if c is not clade]


# --------------------------------------------------------------- detecção
def _ordered(tree: Tree, nodes: list[Node]) -> list[frozenset[str]]:
    """Grupos na ordem das folhas (as cores seguem a volta da árvore)."""
    order = {leaf: i for i, leaf in enumerate(tree.leaves())}
    groups = [(min(order[l] for l in n.leaves()), frozenset(l.name for l in n.leaves())) for n in nodes]
    return [g for _, g in sorted(groups, key=lambda t: t[0])]


def clades_by_k(tree: Tree, k: int, use_lengths: bool = True) -> list[frozenset[str]]:
    """Corta a árvore em ~k grupos monofiléticos.

    Abre sempre o grupo cujo nó está mais perto da raiz (corte por altura).
    Em politomias o resultado pode passar de k (ex.: raiz com 3 filhos e k=2).
    """
    n_leaves = len(tree.leaves())
    k = max(1, min(int(k), n_leaves))
    depth, _ = node_depths(tree, use_lengths)
    order = {node: i for i, node in enumerate(tree.root.traverse_preorder())}
    groups: list[Node] = [tree.root]
    while len(groups) < k:
        splittable = [g for g in groups if g.children]
        if not splittable:
            break
        g = min(splittable, key=lambda n: (depth[n], order[n]))
        groups.remove(g)
        groups.extend(g.children)
    return _ordered(tree, groups)


def clades_by_support(
    tree: Tree, threshold: float, index: int = -1, min_size: int = 2
) -> list[frozenset[str]]:
    """Clados maximais (mais próximos da raiz) com suporte >= limiar."""
    found: list[Node] = []
    stack = list(reversed(tree.root.children))
    while stack:
        node = stack.pop()
        if node.is_leaf:
            continue
        ok = bool(node.supports) and support_value(node.supports, index) >= threshold
        if ok and len(node.leaves()) >= min_size:
            found.append(node)
            continue
        stack.extend(reversed(node.children))
    return _ordered(tree, found)


def clades_by_distance(tree: Tree, distance: float, use_lengths: bool = True) -> list[frozenset[str]]:
    """Subárvores cujo ramo cruza a distância ``distance`` da raiz.

    Folhas que terminam antes do corte ficam sem clado.
    """
    if distance <= 0:
        return []
    depth, _ = node_depths(tree, use_lengths)
    nodes = [
        n
        for n in tree.root.traverse_preorder()
        if n.parent is not None and depth[n.parent] < distance <= depth[n]
    ]
    return _ordered(tree, nodes)


# -------------------------------------------------------------- resolução
def mrca(tree: Tree, names: frozenset[str]) -> Node | None:
    leaves = [l for l in tree.leaves() if l.name in names]
    if not leaves:
        return None
    path = [leaves[0], *leaves[0].ancestors()]
    common = set(map(id, path))
    for leaf in leaves[1:]:
        common &= set(map(id, [leaf, *leaf.ancestors()]))
    return next(n for n in path if id(n) in common)


def resolve_clades(tree: Tree, clades: list[Clade], palette: list[str],
                   hidden: set[str] | frozenset[str] = frozenset()) -> list[ResolvedClade]:
    """Nó de cada clado na árvore atual. Folhas ocultas (``hidden``) não contam."""
    present = set(tree.leaf_names())
    out: list[ResolvedClade] = []
    for i, clade in enumerate(clades):
        color = clade.color or palette[i % len(palette)]
        target = clade.leaves - set(hidden)
        missing = target - present
        node = mrca(tree, target) if target and not missing else None
        if not target:
            out.append(ResolvedClade(clade, None, color, False, "todas as folhas estão ocultas"))
        elif missing:
            out.append(ResolvedClade(clade, None, color, False, f"{len(missing)} folha(s) ausente(s)"))
        elif node is None or frozenset(l.name for l in node.leaves()) != target:
            out.append(ResolvedClade(clade, None, color, False, "não monofilético nesta raiz"))
        else:
            out.append(ResolvedClade(clade, node, color, True))
    return out


def assign_nodes(tree: Tree, resolved: list[ResolvedClade]) -> dict[Node, ResolvedClade]:
    """Clado de cada nó; em clados aninhados vale o mais interno."""
    by_node: dict[int, ResolvedClade] = {}
    for rc in resolved:
        if rc.valid and rc.clade.visible and rc.node is not None:
            by_node[id(rc.node)] = rc   # o último com o mesmo nó vence
    out: dict[Node, ResolvedClade] = {}
    stack: list[tuple[Node, ResolvedClade | None]] = [(tree.root, None)]
    while stack:
        node, current = stack.pop()
        current = by_node.get(id(node), current)
        if current is not None:
            out[node] = current
        stack.extend((c, current) for c in node.children)
    return out
