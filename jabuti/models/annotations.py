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
    kind: str = "genes"                          # "genes" | "metadata" | "matrix"
    width: float | None = None                   # None = largura padrão da célula
    header_rotation: int = 90                    # nome da coluna: 0°, 45° ou 90° (retangular)
    margin: float = 0.0                          # espaço antes da coluna (px)
    # kind "binary": folha -> (forma, preenchida); formas do iTOL: 1 quadrado, 2 círculo,
    # 3 estrela, 4 triângulo p/ direita, 5 triângulo p/ esquerda, 6 "check"
    shapes: dict[str, tuple[int, bool]] = field(default_factory=dict)
    shape_color: str = "#000000"
    shape_colors: dict[str, str] = field(default_factory=dict)     # cor por folha (símbolos do iTOL)
    shape_sizes: dict[str, float] = field(default_factory=dict)    # tamanho relativo (0–1) por folha
    # kind "text": cor e estilo por folha (bold, italic, fator de tamanho)
    text_colors: dict[str, str] = field(default_factory=dict)
    text_styles: dict[str, tuple[bool, bool, float]] = field(default_factory=dict)

    @property
    def always_header(self) -> bool:
        """Matrizes e presença/ausência mostram sempre o nome de cada coluna."""
        return self.kind in ("matrix", "binary")

    def shape_for_group(self, leaves: list[str]) -> tuple[int, bool] | None:
        """Clado colapsado: forma cheia se alguma folha tem 1; vazada se só há 0."""
        got = [self.shapes[l] for l in leaves if l in self.shapes]
        if not got:
            return None
        return got[0][0], any(f for _s, f in got)

    def color_for(self, leaf: str) -> str:
        return self.colors.get(leaf, self.missing_color)

    def color_for_group(self, leaves: list[str]) -> str:
        """Cor de um clado colapsado: a comum a todas as folhas, ou "misto"."""
        colors = {self.color_for(l) for l in leaves}
        return colors.pop() if len(colors) == 1 else MIXED_COLOR


@dataclass
class LegendGroup:
    """Grupo da legenda: amostras (texto, cor) ou barra de cor (``kind="colorbar"``).

    Uma entrada com cor ``None`` é só texto (ex.: "outgroup branch not to scale")."""

    title: str
    entries: list[tuple[str, str | None]]
    kind: str = "swatches"                       # "swatches" | "colorbar"
    stops: list[str] = field(default_factory=list)
    ticks: list[tuple[float, str]] = field(default_factory=list)   # (fração 0–1, rótulo)

    def is_empty(self) -> bool:
        return not self.entries and not (self.kind == "colorbar" and self.stops)


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


def _num(x: float) -> str:
    return str(int(x)) if x == int(x) else f"{x:g}"


def bin_labels(cutoffs: list[float], integers: bool) -> list[str]:
    """Rótulos das faixas: ≤5, 6–50, 51–200, >200 (inteiros) ou ≤a, a–b, >b."""
    cuts = sorted(cutoffs)
    if not cuts:
        return ["todos"]
    labels = [f"≤{_num(cuts[0])}"]
    for a, b in zip(cuts, cuts[1:]):
        lo = _num(a + 1) if integers else _num(a)
        labels.append(f"{lo}–{_num(b)}")
    labels.append(f">{_num(cuts[-1])}")
    return labels


def bin_index(v: float, cutoffs: list[float]) -> int:
    """Faixa do valor: v ≤ c1 → 0; c1 < v ≤ c2 → 1; …; v > ck → k."""
    return next((i for i, c in enumerate(sorted(cutoffs)) if v <= c), len(cutoffs))


def bin_colors(scale, n: int) -> list[str]:  # type: ignore[no-untyped-def]
    """Cores das faixas: as do usuário, completadas com paradas do colormap."""
    from jabuti.models.colormaps import stops

    out = list(scale.colors[:n])
    cm = stops(scale.colormap)
    for i in range(len(out), n):
        out.append(gradient_color(i / max(n - 1, 1), cm))
    return out


def scaled_colors(nums: dict[str, float], column: str, scale) -> tuple[dict[str, str], LegendGroup]:  # type: ignore[no-untyped-def]
    """Cores por uma escala configurada (colormap contínuo ou faixas)."""
    from jabuti.models.colormaps import ColorScale

    if scale.mode == "bins":
        cuts = sorted(scale.cutoffs)
        integers = all(v == int(v) for v in nums.values()) and all(c == int(c) for c in cuts)
        labels = bin_labels(cuts, integers)
        colors = bin_colors(scale, len(labels))
        counts = [0] * len(labels)
        out = {}
        for leaf, v in nums.items():
            i = bin_index(v, cuts)
            counts[i] += 1
            out[leaf] = colors[i]
        return out, LegendGroup(column, [(f"{lab} ({n})", c) for lab, c, n in zip(labels, colors, counts)])
    lo = scale.vmin if scale.vmin is not None else min(nums.values(), default=0.0)
    hi = scale.vmax if scale.vmax is not None else max(nums.values(), default=1.0)
    cs = ColorScale(scale.colormap, lo, hi)
    out = {leaf: cs.color(v) for leaf, v in nums.items()}
    ticks = [(f, _num(round(v, 2))) for f, v in cs.ticks(3)]
    return out, LegendGroup(column, [], "colorbar", list(cs.stops), ticks)


def metadata_colors(
    by_leaf: dict[str, dict[str, str]], column: str, palette: list[str], numeric: bool | None = None,
    scale=None,  # type: ignore[no-untyped-def]
) -> tuple[dict[str, str], LegendGroup]:
    """Cor de cada folha por uma coluna: categorias com a paleta (mais frequentes primeiro)
    ou gradiente para valores numéricos. Valores ausentes ficam sem cor.

    ``scale`` (``style.ColumnScale``) troca o gradiente padrão por um colormap ou por faixas."""
    from jabuti.parsers.metadata import column_is_numeric, is_missing

    values = {leaf: row.get(column, "") for leaf, row in by_leaf.items()}
    present = {leaf: v.strip() for leaf, v in values.items() if not is_missing(v)}
    if scale is not None:
        nums = {leaf: f for leaf, v in present.items() if (f := _to_float(v)) is not None}
        if nums:
            return scaled_colors(nums, column, scale)
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
    by_leaf: dict[str, dict[str, str]], column: str, palette: list[str], missing: str, width: float | None = None,
    scale=None,  # type: ignore[no-untyped-def]
) -> tuple[LeafColumn, LegendGroup]:
    colors, legend = metadata_colors(by_leaf, column, palette, scale=scale)
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
