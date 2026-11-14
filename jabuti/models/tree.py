"""Modelo de árvore independente de biblioteca de parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator


@dataclass(eq=False)
class Node:
    """Nó da árvore. Atributos de ramo (length, supports) referem-se ao ramo nó→pai."""

    name: str = ""
    length: float | None = None
    supports: list[float] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)
    parent: Node | None = field(default=None, repr=False)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def add_child(self, child: Node) -> None:
        child.parent = self
        self.children.append(child)

    def traverse_preorder(self) -> Iterator[Node]:
        stack = [self]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def traverse_postorder(self) -> Iterator[Node]:
        stack: list[tuple[Node, bool]] = [(self, False)]
        while stack:
            node, visited = stack.pop()
            if visited:
                yield node
            else:
                stack.append((node, True))
                stack.extend((c, False) for c in reversed(node.children))

    def leaves(self) -> list[Node]:
        return [n for n in self.traverse_preorder() if n.is_leaf]

    def ancestors(self) -> list[Node]:
        out: list[Node] = []
        node = self.parent
        while node is not None:
            out.append(node)
            node = node.parent
        return out


def _len(node: Node) -> float:
    return node.length if node.length is not None else 0.0


SUPPORT_ALL = 99  # índice especial: todos os valores (o menor precisa passar no limiar)


def support_value(values: list[float], index: int) -> float:
    """Valor de suporte escolhido: índice 0/1 (ex.: SH-aLRT/UFBoot), -1 = último, 99 = mínimo."""
    if index == SUPPORT_ALL:
        return min(values)
    i = index if -len(values) <= index < len(values) else -1
    return values[i]


@dataclass
class TreeSummary:
    n_leaves: int
    n_internal: int
    has_lengths: bool
    has_support: bool
    support_values_per_node: int  # 0, 1 (ex.: UFBoot) ou 2 (ex.: SH-aLRT/UFBoot)
    duplicate_leaf_names: list[str]

    def describe(self) -> str:
        lines = [
            f"Folhas: {self.n_leaves}",
            f"Nós internos: {self.n_internal}",
            f"Comprimentos de ramo: {'sim' if self.has_lengths else 'não'}",
        ]
        if not self.has_support:
            lines.append("Suporte: ausente")
        elif self.support_values_per_node >= 2:
            lines.append("Suporte: presente (2 valores, ex.: SH-aLRT/UFBoot)")
        else:
            lines.append("Suporte: presente (1 valor, ex.: bootstrap/UFBoot)")
        if self.duplicate_leaf_names:
            dup = ", ".join(self.duplicate_leaf_names[:5])
            lines.append(f"⚠ Nomes de folha duplicados: {dup}")
        return "\n".join(lines)


class Tree:
    def __init__(self, root: Node) -> None:
        self.root = root
        self.root.parent = None
        self.root.length = None

    def copy(self) -> Tree:
        """Cópia profunda iterativa (deepcopy recursivo estoura em árvores grandes)."""
        new_root = Node(self.root.name, self.root.length, list(self.root.supports))
        stack = [(self.root, new_root)]
        while stack:
            src, dst = stack.pop()
            for child in src.children:
                c = Node(child.name, child.length, list(child.supports))
                dst.add_child(c)
                stack.append((child, c))
        return Tree(new_root)

    def leaves(self) -> list[Node]:
        return self.root.leaves()

    def leaf_names(self) -> list[str]:
        return [n.name for n in self.leaves()]

    def find_leaf(self, name: str) -> Node | None:
        for leaf in self.leaves():
            if leaf.name == name:
                return leaf
        return None

    def max_support_values(self) -> int:
        return max((len(n.supports) for n in self.root.traverse_preorder()), default=0)

    def summary(self) -> TreeSummary:
        nodes = list(self.root.traverse_preorder())
        leaves = [n for n in nodes if n.is_leaf]
        names = [n.name for n in leaves]
        seen: set[str] = set()
        dups: list[str] = []
        for nm in names:
            if nm in seen and nm not in dups:
                dups.append(nm)
            seen.add(nm)
        nsup = self.max_support_values()
        return TreeSummary(
            n_leaves=len(leaves),
            n_internal=len(nodes) - len(leaves),
            has_lengths=any(n.length is not None for n in nodes if n is not self.root),
            has_support=nsup > 0,
            support_values_per_node=nsup,
            duplicate_leaf_names=dups,
        )

    # ------------------------------------------------------------------ reroot
    def reroot_at_edge(self, node: Node, dist_from_node: float | None = None) -> None:
        """Coloca a raiz sobre o ramo node→pai, a ``dist_from_node`` de ``node``.

        Sem ``dist_from_node`` a raiz fica no meio do ramo.
        """
        parent = node.parent
        if parent is None:
            raise ValueError("Não é possível enraizar no ramo da raiz atual.")
        old_root = self.root
        edge_len = _len(node)
        if dist_from_node is None:
            dist_from_node = edge_len / 2
        dist_from_node = min(max(dist_from_node, 0.0), edge_len)

        # caminho node -> ... -> raiz antiga, com atributos de ramo guardados
        path = [node, parent, *parent.ancestors()]
        lengths = [n.length for n in path]
        supports = [n.supports for n in path]

        # inverte as arestas acima de parent
        for i in range(1, len(path) - 1):
            child_new, parent_new = path[i + 1], path[i]
            child_new.children.remove(parent_new)
            parent_new.children.append(child_new)
            child_new.parent = parent_new
            child_new.length = lengths[i]
            child_new.supports = supports[i]

        parent.children.remove(node)
        new_root = Node()
        new_root.children = [node, parent]
        node.parent = new_root
        parent.parent = new_root
        has_len = lengths[0] is not None
        node.length = dist_from_node if has_len else None
        parent.length = (edge_len - dist_from_node) if has_len else None
        parent.supports = []

        # remove a raiz antiga se ficou com um único filho
        if old_root is not new_root and len(old_root.children) == 1 and old_root.parent is not None:
            only = old_root.children[0]
            up = old_root.parent
            idx = up.children.index(old_root)
            up.children[idx] = only
            only.parent = up
            if only.length is not None or old_root.length is not None:
                only.length = _len(only) + _len(old_root)
            if not only.supports:
                only.supports = old_root.supports

        self.root = new_root
        new_root.parent = None
        new_root.length = None

    def reroot_outgroup(self, leaf_name: str) -> None:
        leaf = self.find_leaf(leaf_name)
        if leaf is None:
            raise ValueError(f"Folha '{leaf_name}' não encontrada na árvore.")
        self.reroot_at_edge(leaf)

    def reroot_midpoint(self) -> None:
        leaves = self.leaves()
        if len(leaves) < 3:
            return
        a = self._farthest_leaf(leaves[0])
        b = self._farthest_leaf(a)
        anc_a = [a, *a.ancestors()]
        anc_b = [b, *b.ancestors()]
        set_b = set(map(id, anc_b))
        lca = next(n for n in anc_a if id(n) in set_b)
        da = sum(_len(n) for n in anc_a[: anc_a.index(lca)])
        db = sum(_len(n) for n in anc_b[: anc_b.index(lca)])
        half = (da + db) / 2
        start = a if da >= db else b
        node, cum = start, 0.0
        while node is not lca and cum + _len(node) < half:
            cum += _len(node)
            node = node.parent  # type: ignore[assignment]
        if node is lca:  # caso degenerado (ramos zero)
            return
        self.reroot_at_edge(node, half - cum)

    def _farthest_leaf(self, start: Node) -> Node:
        """Folha mais distante de ``start`` (busca no grafo não-direcionado)."""
        best, best_d = start, 0.0
        stack: list[tuple[Node, Node | None, float]] = [(start, None, 0.0)]
        while stack:
            node, came_from, d = stack.pop()
            if node.is_leaf and d > best_d:
                best, best_d = node, d
            for child in node.children:
                if child is not came_from:
                    stack.append((child, node, d + _len(child)))
            if node.parent is not None and node.parent is not came_from:
                stack.append((node.parent, node, d + _len(node)))
        return best
