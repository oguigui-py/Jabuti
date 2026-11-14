"""Trilhas de dados desenhadas ao lado da árvore (colunas no retangular, anéis no circular).

Modelo puro, sem Qt. Além das ``LeafColumn`` (células coloridas: faixas de metadados,
heatmap de GFF, matriz), há barras simples e barras empilhadas. O renderer recebe uma
lista ordenada (da árvore para fora) que pode conter também ``CLADE_STRIP``, o marcador
da faixa de cor dos clados.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CLADE_STRIP = "clade-strip"     # chave/marcador da faixa externa de clados
GENE_BLOCK = "gene:*"           # chave do bloco de colunas do heatmap de GFF


def fmt_value(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.3g}" if abs(v) < 1000 else f"{v:.0f}"


def auto_range(values: list[float], vmin: float | None = None, vmax: float | None = None) -> tuple[float, float]:
    """Eixo das barras: começa em 0 (ou no mínimo, se houver negativos) e vai até o máximo."""
    lo = vmin if vmin is not None else min([0.0, *values])
    hi = vmax if vmax is not None else max([lo, *values])
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


@dataclass
class BarTrack:
    key: str
    header: str
    values: dict[str, float]                     # folha -> valor (ausente = sem dado)
    vmin: float = 0.0
    vmax: float = 1.0
    color: str = "#4e79a7"
    color_mode: str = "single"                   # "single" | "clade" | "metadata"
    colors: dict[str, str] = field(default_factory=dict)   # folha -> cor ("metadata")
    refs: list[float] = field(default_factory=list)
    show_values: bool = False
    width: float = 80.0
    missing_color: str = "#d9d9d9"

    def value_for(self, names: list[str]) -> float | None:
        """Valor da folha, ou a média de um clado colapsado (ignora folhas sem dado)."""
        return mean([self.values[n] for n in names if n in self.values])

    def frac(self, v: float) -> float:
        return max(0.0, min((v - self.vmin) / (self.vmax - self.vmin), 1.0))

    @property
    def base(self) -> float:
        """Fração onde a barra começa (o zero, se estiver dentro do eixo)."""
        return self.frac(min(max(0.0, self.vmin), self.vmax))

    def visible_refs(self) -> list[float]:
        return [r for r in self.refs if self.vmin <= r <= self.vmax]


@dataclass
class StackedTrack:
    key: str
    header: str
    series: list[str]
    colors: list[str]
    values: dict[str, list[float | None]]        # folha -> um valor por série (None = sem dado)
    vmax: float = 1.0
    width: float = 100.0
    missing_color: str = "#d9d9d9"

    def stack_for(self, names: list[str]) -> list[float] | None:
        """Valores por série (média num clado colapsado); série sem dado conta como 0.

        ``None`` se nenhuma folha tiver dado em nenhuma série."""
        rows = [self.values[n] for n in names if n in self.values]
        if not rows or all(v is None for r in rows for v in r):
            return None
        out = []
        for i in range(len(self.series)):
            vals = [r[i] for r in rows if r[i] is not None]
            out.append(max(mean(vals) or 0.0, 0.0))
        return out

    def frac(self, v: float) -> float:
        return max(0.0, min(v / self.vmax, 1.0)) if self.vmax > 0 else 0.0


def stacked_track(key: str, header: str, series: list[str], colors: list[str],
                  columns: dict[str, dict[str, float]], vmax: float | None = None,
                  **kw) -> StackedTrack:  # type: ignore[no-untyped-def]
    """``columns``: série -> (folha -> valor). Máximo automático = maior soma."""
    leaves = sorted({leaf for col in columns.values() for leaf in col})
    values = {leaf: [columns[s].get(leaf) for s in series] for leaf in leaves}
    top = max((sum(max(v or 0.0, 0.0) for v in row) for row in values.values()), default=0.0)
    hi = vmax if vmax is not None and vmax > 0 else (top or 1.0)
    return StackedTrack(key, header, list(series), list(colors), values, hi, **kw)


def bar_track(key: str, header: str, values: dict[str, float], *, vmin: float | None = None,
              vmax: float | None = None, **kw) -> BarTrack:  # type: ignore[no-untyped-def]
    lo, hi = auto_range(list(values.values()), vmin, vmax)
    return BarTrack(key, header, values, lo, hi, **kw)


def parse_refs(text: str) -> list[float]:
    """"4; 8", "4 8" ou "4, 8" -> [4.0, 8.0]. Vírgula sem espaço depois é decimal ("2,5").

    Levanta ``ValueError`` com mensagem clara."""
    out: list[float] = []
    for part in re.split(r"[;\s]+|,(?=\s)", text):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part.replace(",", ".")))
        except ValueError:
            raise ValueError(f"Valor de referência inválido: “{part}” (use números separados por vírgula).") from None
    return out


def order_keys(available: list[str], order: list[str], hidden: list[str] | None = None) -> list[str]:
    """Chaves na ordem pedida; as que não estão em ``order`` (novas) vão para o fim.

    ``hidden`` são omitidas."""
    hide = set(hidden or [])
    keys = [k for k in order if k in available] + [k for k in available if k not in order]
    seen: set[str] = set()
    out = []
    for k in keys:
        if k not in seen and k not in hide:
            seen.add(k)
            out.append(k)
    return out


# ------------------------------------------------------------------ matriz
def natural_key(name: str) -> tuple:
    """Ordem natural por prefixo e número: GH2 < GH13 < GT4 < GT10."""
    parts = re.split(r"(\d+(?:\.\d+)?)", name)
    return tuple((0, float(p)) if i % 2 else (1, p.lower()) for i, p in enumerate(parts) if p != "")


def feature_sums(by_leaf: dict[str, dict[str, str]], features: list[str]) -> dict[str, float]:
    """Soma de cada característica nas folhas da árvore (NA conta como 0)."""
    from jabuti.models.datatables import numeric_column

    return {f: sum(numeric_column(by_leaf, f).values()) for f in features}


def select_features(by_leaf: dict[str, dict[str, str]], available: list[str], mode: str,
                    chosen: list[str], top_n: int) -> list[str]:
    """Características a desenhar, em ordem natural: as escolhidas ou as N de maior soma."""
    if mode == "top":
        sums = feature_sums(by_leaf, available)
        ranked = sorted(available, key=lambda f: (-sums[f], natural_key(f)))
        picked = ranked[:max(top_n, 0)]
    else:
        picked = [f for f in chosen if f in available]
    return sorted(picked, key=natural_key)


def matrix_columns(key: str, by_leaf: dict[str, dict[str, str]], features: list[str], colormap: str,
                   scale: str = "linear", vmin: float | None = None, vmax: float | None = None,
                   show_values: bool = False, width: float | None = None, missing: str = "#d9d9d9",
                   header_rotation: int = 90):  # type: ignore[no-untyped-def]
    """Colunas de células (uma por característica) e a escala de cor usada."""
    from jabuti.models.annotations import LeafColumn
    from jabuti.models.colormaps import ColorScale
    from jabuti.models.datatables import numeric_column

    data = {f: numeric_column(by_leaf, f) for f in features}
    values = [v for col in data.values() for v in col.values()]
    lo = vmin if vmin is not None else min(values, default=0.0)
    hi = vmax if vmax is not None else max(values, default=1.0)
    cs = ColorScale(colormap, lo, hi, scale)
    cols = []
    for f in features:
        colors = {leaf: cs.color(v) for leaf, v in data[f].items()}
        texts = {leaf: fmt_value(v) for leaf, v in data[f].items()} if show_values else {}
        cols.append(LeafColumn(f"{key}:{f}", f, colors, missing, texts, "matrix", width, header_rotation))
    return cols, cs
