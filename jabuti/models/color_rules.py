"""Precedência de cores e espessuras de ramos e rótulos (sem Qt).

Usada pelo renderer e pela exportação para o iTOL: a cor exportada é exatamente a
da tela. Ordem de prioridade:

* ramo: estilo do iTOL > metadado (se "colorir ramos") > clado > padrão;
* rótulo: grupo de rótulo > metadado > clado > padrão (campos vazios do grupo herdam).
"""

from __future__ import annotations

from dataclasses import dataclass

from jabuti.models.clades import ResolvedClade, assign_nodes
from jabuti.models.tree import Node, Tree, support_value


@dataclass
class LabelPaint:
    """Cor, fonte relativa e fundo de um rótulo de folha."""

    color: str
    bold: bool
    italic: bool
    size_scale: float = 1.0
    background: str | None = None
    background_alpha: float = 1.0
    padding: float = 2.0
    radius: float = 3.0


def propagate_meta(tree: Tree, leaf_colors: dict[str, str]) -> dict[Node, str]:
    """Cor de metadado por nó: a da folha, ou a comum a todos os descendentes."""
    out: dict[Node, str] = {}
    if not leaf_colors:
        return out
    for node in tree.root.traverse_postorder():
        if node.is_leaf:
            if node.name in leaf_colors:
                out[node] = leaf_colors[node.name]
        else:
            kids = [out.get(c) for c in node.children]
            if kids and kids[0] is not None and all(k == kids[0] for k in kids):
                out[node] = kids[0]
    return out


class ColorRules:
    def __init__(self, tree: Tree, style, resolved: list[ResolvedClade] | None = None,  # type: ignore[no-untyped-def]
                 meta_colors: dict[str, str] | None = None, branch_looks: tuple[dict, dict] | None = None,
                 groups: dict | None = None) -> None:
        self.style = style
        self.assign = assign_nodes(tree, resolved or [])
        self.has_clades = bool(self.assign)
        self.meta_node = propagate_meta(tree, meta_colors or {})
        self.edge_looks, self.node_looks = branch_looks or ({}, {})
        self.groups = groups or {}
        b = style.branch
        self.width_by_support = b.width_by_support and tree.max_support_values() > 0
        idx = style.support.index
        vals = [support_value(n.supports, idx) for n in tree.root.traverse_preorder() if n.supports]
        self.support_max = max(vals, default=0.0) or 1.0

    # ------------------------------------------------------------ ramos
    def clade_of(self, node: Node | None) -> ResolvedClade | None:
        return self.assign.get(node) if node is not None else None

    def width(self, node: Node | None) -> float:
        """Espessura do ramo que termina em ``node`` (e do conector/arco que sai dele)."""
        b = self.style.branch
        if not self.width_by_support:
            return b.width
        if node is None or not node.supports:
            return b.min_width
        frac = max(0.0, min(support_value(node.supports, self.style.support.index) / self.support_max, 1.0))
        return round(b.min_width + (b.max_width - b.min_width) * frac, 2)

    def branch_color(self, owner: Node | None) -> str:
        """Cor de um segmento pertencente a ``owner`` (o nó pai do ramo, ou o nó do arco)."""
        cs = self.style.clades
        if self.has_clades and cs.color_branches:
            rc = self.clade_of(owner)
            return rc.color if rc else cs.neutral_color
        return self.style.branch.color

    def edge_color(self, node: Node) -> str:
        """Ramo que termina em ``node``: metadado do próprio nó (se ativo) ou regra dos clados."""
        if self.style.metadata.color_branches and node in self.meta_node:
            return self.meta_node[node]
        return self.branch_color(node.parent)

    def node_color(self, node: Node) -> str:
        """Conector/arco que sai de ``node``."""
        if self.style.metadata.color_branches and node in self.meta_node:
            return self.meta_node[node]
        return self.branch_color(node)

    def edge_pen(self, node: Node) -> tuple[str, float, bool]:
        """(cor, espessura, tracejado) do ramo que termina em ``node`` (estilo iTOL vence)."""
        look = self.edge_looks.get(node)
        if look is None:
            return self.edge_color(node), self.width(node), False
        return (look.color or self.edge_color(node), round(self.width(node) * look.width_factor, 3), look.dashed)

    def node_pen(self, node: Node) -> tuple[str, float, bool]:
        """(cor, espessura, tracejado) do conector/arco que sai de ``node``."""
        look = self.node_looks.get(node)
        if look is None:
            return self.node_color(node), self.width(node), False
        return (look.color or self.node_color(node), round(self.width(node) * look.width_factor, 3), look.dashed)

    # ------------------------------------------------------------ rótulos
    def label_color(self, leaf: Node) -> str:
        md = self.style.metadata
        if md.color_labels and leaf in self.meta_node:
            return self.meta_node[leaf]
        cs = self.style.clades
        if self.has_clades and cs.color_labels:
            rc = self.clade_of(leaf)
            return rc.color if rc else cs.neutral_color
        return self.style.label.color

    def label_paint(self, leaf: Node) -> LabelPaint:
        lab = self.style.label
        g = self.groups.get(leaf.name)
        look = g.look if g is not None else None
        paint = LabelPaint(self.label_color(leaf), lab.bold, lab.italic)
        if look is not None:
            if look.text_color:
                paint.color = look.text_color
            if look.bold is not None:
                paint.bold = look.bold
            if look.italic is not None:
                paint.italic = look.italic
            paint.size_scale = look.size_scale
        cs = self.style.clades
        if look is not None and look.background:
            paint.background, paint.background_alpha = look.background, look.background_alpha
        elif cs.label_background and self.has_clades:
            rc = self.clade_of(leaf)
            if rc is not None:
                paint.background, paint.background_alpha = rc.color, cs.label_background_alpha
        if paint.background and look is not None:
            paint.padding, paint.radius = look.padding, look.radius
        return paint
