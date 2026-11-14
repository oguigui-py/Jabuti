"""Edições de visualização da árvore: ladderize, rotações e colapsos.

Como os clados, são guardadas por conjunto de nomes de folhas: sobrevivem a
reenraizamentos e podem ir para presets JSON. A árvore enraizada nunca é
alterada; ``apply_edits`` devolve uma cópia ordenada para desenhar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jabuti.models.clades import mrca
from jabuti.models.tree import Node, Tree

LADDERIZE = {"none": "Ordem do arquivo", "asc": "Crescente (clados menores primeiro)",
             "desc": "Decrescente (clados maiores primeiro)"}


@dataclass
class ShortBranch:
    """Ramo exibido mais curto (com a marca "//"); identificado pelas folhas abaixo dele."""

    leaves: frozenset[str]
    max_length: float


@dataclass
class TreeEdits:
    ladderize: str = "none"                                   # chave de LADDERIZE
    rotations: list[frozenset[str]] = field(default_factory=list)
    collapsed: list[frozenset[str]] = field(default_factory=list)
    hidden: set[str] = field(default_factory=set)             # folhas ocultas (podadas do desenho)
    shortened: list[ShortBranch] = field(default_factory=list)

    def hide(self, names) -> None:  # type: ignore[no-untyped-def]
        self.hidden |= set(names)

    def restore(self, names=None) -> None:  # type: ignore[no-untyped-def]
        """Restaura as folhas indicadas (todas, sem argumento)."""
        self.hidden = set() if names is None else self.hidden - set(names)

    def short_branch(self, leaves: frozenset[str]) -> ShortBranch | None:
        return next((b for b in self.shortened if b.leaves == leaves), None)

    def set_short(self, leaves: frozenset[str], max_length: float) -> ShortBranch:
        b = self.short_branch(leaves)
        if b is None:
            b = ShortBranch(leaves, max_length)
            self.shortened.append(b)
        b.max_length = max_length
        return b

    def unshort(self, leaves: frozenset[str]) -> None:
        self.shortened = [b for b in self.shortened if b.leaves != leaves]

    def toggle_rotation(self, leaves: frozenset[str]) -> None:
        """Girar duas vezes o mesmo nó desfaz a rotação."""
        if leaves in self.rotations:
            self.rotations.remove(leaves)
        else:
            self.rotations.append(leaves)

    def collapse(self, leaves: frozenset[str]) -> None:
        if leaves not in self.collapsed:
            self.collapsed.append(leaves)

    def expand(self, leaves: frozenset[str]) -> None:
        self.collapsed = [c for c in self.collapsed if c != leaves]

    def is_collapsed(self, leaves: frozenset[str]) -> bool:
        return leaves in self.collapsed


def _leafset(node: Node) -> frozenset[str]:
    return frozenset(l.name for l in node.leaves())


def resolve_nodes(tree: Tree, sets: list[frozenset[str]]) -> list[Node]:
    """Nós cujo conjunto de folhas é exatamente o pedido (ignora os não monofiléticos).

    Folhas que não estão na árvore (ex.: ocultas) são desconsideradas."""
    present = set(tree.leaf_names())
    out: list[Node] = []
    for leaves in sets:
        target = leaves & present
        node = mrca(tree, target) if target else None
        if node is not None and _leafset(node) == target:
            out.append(node)
    return out


def prune(tree: Tree, hidden: set[str]) -> None:
    """Remove as folhas ``hidden`` (in place), juntando os ramos que ficam com um só filho.

    O comprimento do ramo resultante é a soma; o suporte que fica é o do filho (a mesma
    bipartição depois da poda), ou o do pai se o filho não tiver."""
    if not hidden:
        return
    keep: dict[Node, bool] = {}
    for node in tree.root.traverse_postorder():
        keep[node] = (node.name not in hidden) if node.is_leaf else any(keep[c] for c in node.children)
    for node in list(tree.root.traverse_preorder()):
        removed = [c for c in node.children if not keep[c]]
        for c in removed:
            c.parent = None
        node.children = [c for c in node.children if keep[c]]
    for node in list(tree.root.traverse_postorder()):
        if node.parent is not None and len(node.children) == 1:
            child, parent = node.children[0], node.parent
            parent.children[parent.children.index(node)] = child
            child.parent = parent
            if child.length is not None or node.length is not None:
                child.length = (child.length or 0.0) + (node.length or 0.0)
            if not child.supports:
                child.supports = list(node.supports)
    root = tree.root
    while len(root.children) == 1:
        root = root.children[0]
    if root is not tree.root:
        tree.root = root
        root.parent = None
        root.length = None


def apply_shortened(tree: Tree, shortened: list[ShortBranch]) -> set[Node]:
    """Limita o comprimento exibido dos ramos indicados; devolve os nós marcados com "//"."""
    marked: set[Node] = set()
    for b in shortened:
        (node,) = resolve_nodes(tree, [b.leaves]) or (None,)
        if node is None or node.parent is None or node.length is None:
            continue
        if node.length > b.max_length:
            node.length = max(b.max_length, 0.0)
            marked.add(node)
    return marked


def ladderize(tree: Tree, direction: str) -> None:
    """Ordena os filhos de cada nó pelo nº de folhas (in place)."""
    if direction not in ("asc", "desc"):
        return
    size: dict[Node, int] = {}
    for node in tree.root.traverse_postorder():
        size[node] = 1 if node.is_leaf else sum(size[c] for c in node.children)
    for node in tree.root.traverse_preorder():
        node.children.sort(key=lambda c: size[c], reverse=direction == "desc")


def apply_edits(tree: Tree, edits: TreeEdits) -> Tree:
    """Cópia da árvore com ladderize, rotações, folhas ocultas e ramos encurtados.

    ``out.broken`` guarda os nós cujo ramo foi encurtado (marca "//")."""
    out = tree.copy()
    ladderize(out, edits.ladderize)
    for node in resolve_nodes(out, edits.rotations):
        node.children.reverse()
    hidden = edits.hidden & set(out.leaf_names())
    if hidden and len(out.leaves()) - len(hidden) >= 2:   # pelo menos 2 folhas continuam
        prune(out, hidden)
    out.broken = apply_shortened(out, edits.shortened)
    return out


def collapsed_nodes(tree: Tree, edits: TreeEdits) -> set[Node]:
    """Nós colapsados mais externos (um colapso dentro de outro é ignorado)."""
    nodes = {n for n in resolve_nodes(tree, edits.collapsed) if not n.is_leaf}
    return {n for n in nodes if not any(a in nodes for a in n.ancestors())}
