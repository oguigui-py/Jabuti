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
    width: float | None = None                   # None = largura padrão da célula

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


def presence_matrix(genomes: dict[str, Genome], queries: list[GeneQuery], find=find_genes) -> dict[str, dict[str, int]]:  # type: ignore[no-untyped-def]
    """``{título da consulta: {folha: nº de genes encontrados}}`` (só folhas com GFF).

    ``find(genome, query)`` pode ser uma versão com cache.
    """
    out: dict[str, dict[str, int]] = {}
    for q in queries:
        out[q.title] = {leaf: len(find(g, q)) for leaf, g in genomes.items()}
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


# ------------------------------------------------------------- metadados
# gradiente sequencial (estilo viridis), legível também em escala de cinza
GRADIENT = ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"]


def _lerp(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def gradient_color(t: float, stops: list[str] = GRADIENT) -> str:
    t = max(0.0, min(t, 1.0))
    pos = t * (len(stops) - 1)
    i = min(int(pos), len(stops) - 2)
    return _lerp(stops[i], stops[i + 1], pos - i)


def _to_float(v: str) -> float | None:
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return None


def metadata_colors(
    by_leaf: dict[str, dict[str, str]], column: str, palette: list[str], numeric: bool | None = None
) -> tuple[dict[str, str], LegendGroup]:
    """Cor de cada folha por uma coluna: categorias com a paleta (mais frequentes primeiro)
    ou gradiente para valores numéricos. Valores ausentes ficam sem cor."""
    from jabuti.parsers.metadata import column_is_numeric, is_missing

    values = {leaf: row.get(column, "") for leaf, row in by_leaf.items()}
    present = {leaf: v.strip() for leaf, v in values.items() if not is_missing(v)}
    if numeric is None:
        numeric = column_is_numeric(list(present.values()))
    if numeric:
        nums = {leaf: f for leaf, v in present.items() if (f := _to_float(v)) is not None}
        if nums:
            lo, hi = min(nums.values()), max(nums.values())
            span = (hi - lo) or 1.0
            colors = {leaf: gradient_color((f - lo) / span) for leaf, f in nums.items()}
            mid = (lo + hi) / 2
            legend = [(f"{lo:g}", gradient_color(0)), (f"{mid:g}", gradient_color(0.5)), (f"{hi:g}", gradient_color(1))]
            return colors, LegendGroup(column, legend)
    counts: dict[str, int] = {}
    for v in present.values():
        counts[v] = counts.get(v, 0) + 1
    cats = sorted(counts, key=lambda c: (-counts[c], c.lower()))
    cmap = {c: palette[i % len(palette)] for i, c in enumerate(cats)}
    entries = [(f"{c} ({counts[c]})", cmap[c]) for c in cats]
    if len(cats) > len(palette):
        entries.append((f"⚠ {len(cats)} categorias > {len(palette)} cores: cores repetidas", "#ffffff"))
    return {leaf: cmap[v] for leaf, v in present.items()}, LegendGroup(column, entries)


def metadata_column(
    by_leaf: dict[str, dict[str, str]], column: str, palette: list[str], missing: str, width: float | None = None
) -> tuple[LeafColumn, LegendGroup]:
    colors, legend = metadata_colors(by_leaf, column, palette)
    return LeafColumn(f"meta:{column}", column, colors, missing, kind="metadata", width=width), legend


# --------------------------------------------------------- contexto gênico
OTHER_GENE_COLOR = "#cfcfcf"


@dataclass
class ContextGene:
    label: str
    start: int          # bp relativo ao centro do gene âncora (âncora sempre "para a direita")
    end: int
    forward: bool       # mesma orientação que o âncora
    is_anchor: bool
    color: str
    locus_tag: str = ""


def gene_context(
    genomes: dict[str, Genome],
    anchor_query: GeneQuery,
    n: int,
    color_queries: list[tuple[GeneQuery, str]],
) -> dict[str, list[ContextGene]]:
    """Vizinhança (±n genes) do primeiro gene que casa com ``anchor_query`` em cada genoma.

    Coordenadas relativas ao centro do âncora; se o âncora estiver na fita "-", a janela é
    espelhada para que ele aponte sempre para a direita (alinha os genomas). Genes que casam
    com alguma consulta recebem a cor dela; os demais ficam cinza.
    """
    from jabuti.parsers.gff import neighbors

    matchers = [(q.matcher(), color) for q, color in color_queries]
    out: dict[str, list[ContextGene]] = {}
    for leaf, genome in genomes.items():
        hits = find_genes(genome, anchor_query)
        if not hits:
            continue
        anchor = hits[0]
        center = (anchor.start + anchor.end) / 2
        flip = anchor.strand == "-"
        track: list[ContextGene] = []
        for f in neighbors(genome, anchor, n):
            s, e = f.start - center, f.end - center
            if flip:
                s, e = -e, -s
            same = (f.strand == anchor.strand) or f.strand == "." or anchor.strand == "."
            color = next((c for m, c in matchers if m(f)), OTHER_GENE_COLOR)
            track.append(ContextGene(f.label or f.locus_tag, round(s), round(e),
                                     same if f.strand != "." else True, f is anchor, color, f.locus_tag))
        track.sort(key=lambda g: g.start)
        out[leaf] = track
    return out


def context_extent(tracks: dict[str, list[ContextGene]]) -> float:
    """Maior distância (bp) do centro do âncora até a borda de qualquer vizinho."""
    return max((max(abs(g.start), abs(g.end)) for t in tracks.values() for g in t), default=0.0)
