"""Suporte em níveis (faixas com cores) e resumo copiável da árvore."""

from __future__ import annotations

from jabuti.models.tree import Tree, support_value


def _num(x: float) -> str:
    return str(int(x)) if x == int(x) else f"{x:g}"


def level_labels(cutoffs: list[float]) -> list[str]:
    """[95, 70] → ["≥95", "70–94", "<70"] (inteiros) ou ["≥0.95", "0.7–0.95", "<0.7"]."""
    cuts = sorted(cutoffs, reverse=True)
    if not cuts:
        return ["todos"]
    integers = all(c == int(c) for c in cuts)
    labels = [f"≥{_num(cuts[0])}"]
    for hi, lo in zip(cuts, cuts[1:]):
        top = _num(hi - 1) if integers else _num(hi)
        labels.append(f"{_num(lo)}–{top}")
    labels.append(f"<{_num(cuts[-1])}")
    return labels


def level_of(value: float, cutoffs: list[float]) -> int:
    """Faixa do valor: ≥ maior corte → 0; …; abaixo do menor → len(cutoffs)."""
    for i, c in enumerate(sorted(cutoffs, reverse=True)):
        if value >= c:
            return i
    return len(cutoffs)


def value_name(index: int, n_values: int) -> str:
    """Nome do valor de suporte usado (convenção do IQ-TREE: "SH-aLRT/UFBoot")."""
    if n_values >= 2:
        return {0: "SH-aLRT", 1: "UFBoot"}.get(index if index >= 0 else n_values - 1, f"valor {index + 1}")
    return "bootstrap/UFBoot" if n_values == 1 else "suporte"


def supported_nodes(tree: Tree) -> list:
    return [n for n in tree.root.traverse_preorder() if not n.is_leaf and n is not tree.root and n.supports]


def band_counts(values: list[float], cutoffs: list[float]) -> list[int]:
    counts = [0] * (len(cutoffs) + 1)
    for v in values:
        counts[level_of(v, cutoffs)] += 1
    return counts


def tree_summary(tree: Tree, hidden: int = 0, ufboot_cuts: tuple[float, ...] = (95, 70),
                 sh_cuts: tuple[float, ...] = (80,)) -> str:
    """Resumo copiável: folhas, nós internos e nós por faixa de suporte (UFBoot e SH-aLRT)."""
    leaves = tree.leaves()
    internal = [n for n in tree.root.traverse_preorder() if not n.is_leaf and n is not tree.root]
    nodes = supported_nodes(tree)
    n_values = max((len(n.supports) for n in nodes), default=0)
    lines = [f"Folhas: {len(leaves)}" + (f" (+{hidden} oculta(s), fora do resumo)" if hidden else ""),
             f"Nós internos (sem a raiz): {len(internal)} · com suporte: {len(nodes)}"]

    def bands(index: int, name: str, cuts: tuple[float, ...]) -> str:
        vals = [support_value(n.supports, index) for n in nodes if len(n.supports) > max(index, 0) or index < 0]
        counts = band_counts(vals, list(cuts))
        parts = " · ".join(f"{lab}: {c}" for lab, c in zip(level_labels(list(cuts)), counts))
        return f"{name} ({len(vals)} nós): {parts}"

    if n_values >= 2:
        lines.append(bands(1, "UFBoot", ufboot_cuts))
        lines.append(bands(0, "SH-aLRT", sh_cuts))
        both = sum(1 for n in nodes if len(n.supports) >= 2 and n.supports[0] >= sh_cuts[0]
                   and n.supports[1] >= ufboot_cuts[0])
        lines.append(f"SH-aLRT ≥{_num(sh_cuts[0])} e UFBoot ≥{_num(ufboot_cuts[0])}: {both} nós")
    elif n_values == 1:
        lines.append(bands(-1, "Suporte (bootstrap/UFBoot)", ufboot_cuts))
    else:
        lines.append("Sem valores de suporte.")
    lines.append(f"Sem suporte: {len(internal) - len(nodes)} nó(s) interno(s)")
    return "\n".join(lines)
