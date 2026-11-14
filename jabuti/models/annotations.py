"""Colunas de anotação por folha (heatmap de genes, faixas de metadados) e legenda.

Modelo puro: o renderer só recebe ``LeafColumn`` (folha -> cor) e desenha em
colunas (retangular) ou anéis concêntricos (circular).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jabuti.parsers.gff import GeneQuery, Genome, find_genes

MIXED_COLOR = "#b0b0b0"   # clado colapsado com valores diferentes


@dataclass
class LeafColumn:
    key: str
    header: str
    colors: dict[str, str]                       # folha -> cor; folha ausente = sem dado
    missing_color: str = "#d9d9d9"
    texts: dict[str, str] = field(default_factory=dict)
    kind: str = "genes"                          # "genes" | "metadata"

    def color_for(self, leaf: str) -> str:
        return self.colors.get(leaf, self.missing_color)

    def color_for_group(self, leaves: list[str]) -> str:
        """Cor de um clado colapsado: a comum a todas as folhas, ou "misto"."""
        colors = {self.color_for(l) for l in leaves}
        return colors.pop() if len(colors) == 1 else MIXED_COLOR


@dataclass
class LegendGroup:
    title: str
    entries: list[tuple[str, str]]


def presence_matrix(genomes: dict[str, Genome], queries: list[GeneQuery]) -> dict[str, dict[str, int]]:
    """``{título da consulta: {folha: nº de genes encontrados}}`` (só folhas com GFF)."""
    out: dict[str, dict[str, int]] = {}
    for q in queries:
        out[q.title] = {leaf: len(find_genes(g, q)) for leaf, g in genomes.items()}
    return out


def presence_columns(
    matrix: dict[str, dict[str, int]],
    present: str,
    absent: str,
    missing: str,
    show_counts: bool = False,
) -> list[LeafColumn]:
    cols: list[LeafColumn] = []
    for title, counts in matrix.items():
        colors = {leaf: (present if n > 0 else absent) for leaf, n in counts.items()}
        texts = {leaf: str(n) for leaf, n in counts.items() if show_counts and n > 1}
        cols.append(LeafColumn(f"gene:{title}", title, colors, missing, texts, "genes"))
    return cols


def presence_legend(present: str, absent: str, missing: str) -> LegendGroup:
    return LegendGroup("Heatmap de genes", [("presente", present), ("ausente", absent),
                                             ("sem GFF", missing)])
