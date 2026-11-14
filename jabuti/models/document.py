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
class TreeEdits:
    ladderize: str = "none"                                   # chave de LADDERIZE
    rotations: list[frozenset[str]] = field(default_factory=list)
    collapsed: list[frozenset[str]] = field(default_factory=list)

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
    """Nós cujo conjunto de folhas é exatamente o pedido (ignora os não monofiléticos)."""
    out: list[Node] = []
    for leaves in sets:
        node = mrca(tree, leaves)
        if node is not None and _leafset(node) == leaves:
            out.append(node)
    return out


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
    """Cópia da árvore com ladderize e rotações aplicados."""
    out = tree.copy()
    ladderize(out, edits.ladderize)
    for node in resolve_nodes(out, edits.rotations):
        node.children.reverse()
    return out


def collapsed_nodes(tree: Tree, edits: TreeEdits) -> set[Node]:
    """Nós colapsados mais externos (um colapso dentro de outro é ignorado)."""
    nodes = {n for n in resolve_nodes(tree, edits.collapsed) if not n.is_leaf}
    return {n for n in nodes if not any(a in nodes for a in n.ancestors())}
