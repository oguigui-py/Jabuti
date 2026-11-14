"""Colormaps como listas de paradas (sem dependência de matplotlib)."""

from __future__ import annotations

import math

from jabuti.models.annotations import gradient_color

COLORMAPS: dict[str, list[str]] = {
    "viridis": ["#440154", "#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58",
                "#b5de2b", "#fde725"],
    "magma": ["#000004", "#180f3d", "#440f76", "#721f81", "#9e2f7f", "#cd4071", "#f1605d", "#fd9668",
              "#feca8d", "#fcfdbf"],
    "cividis": ["#00224e", "#123570", "#3b496c", "#575d6d", "#707173", "#8a8678", "#a59c74", "#c3b369",
                "#e1cc55", "#fee838"],
    "Blues": ["#f7fbff", "#deebf7", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#08519c", "#08306b"],
    "Reds": ["#fff5f0", "#fee0d2", "#fcbba1", "#fc9272", "#fb6a4a", "#ef3b2c", "#cb181d", "#a50f15", "#67000d"],
    "Greens": ["#f7fcf5", "#e5f5e0", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d", "#238b45", "#006d2c", "#00441b"],
    "YlOrRd": ["#ffffcc", "#ffeda0", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#bd0026", "#800026"],
    "cinza": ["#f2f2f2", "#bdbdbd", "#969696", "#636363", "#252525"],
}

SCALES: dict[str, str] = {"linear": "Linear", "log1p": "log(1 + x)", "sqrt": "Raiz quadrada"}


def stops(name: str) -> list[str]:
    return COLORMAPS.get(name) or COLORMAPS["viridis"]


def transform(v: float, scale: str) -> float:
    if scale == "log1p":
        return math.log1p(max(v, 0.0))
    if scale == "sqrt":
        return math.sqrt(max(v, 0.0))
    return v


def inverse(t: float, scale: str) -> float:
    if scale == "log1p":
        return math.expm1(t)
    if scale == "sqrt":
        return t * t
    return t


class ColorScale:
    """Valor -> cor numa escala (linear, log1p ou raiz) entre ``vmin`` e ``vmax``."""

    def __init__(self, colormap: str, vmin: float, vmax: float, scale: str = "linear") -> None:
        self.stops = stops(colormap)
        self.scale = scale if scale in SCALES else "linear"
        self.vmin, self.vmax = vmin, vmax
        self.t0, self.t1 = transform(vmin, self.scale), transform(vmax, self.scale)
        if self.t1 <= self.t0:
            self.t1 = self.t0 + 1.0

    def fraction(self, v: float) -> float:
        return max(0.0, min((transform(v, self.scale) - self.t0) / (self.t1 - self.t0), 1.0))

    def color(self, v: float) -> str:
        return gradient_color(self.fraction(v), self.stops)

    def ticks(self, n: int = 3) -> list[tuple[float, float]]:
        """(fração na barra, valor) igualmente espaçados na escala transformada."""
        out = []
        for i in range(n):
            f = i / (n - 1) if n > 1 else 0.0
            out.append((f, inverse(self.t0 + f * (self.t1 - self.t0), self.scale)))
        return out
