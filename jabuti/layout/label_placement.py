"""Rótulos sem sobreposição na árvore não enraizada (sem Qt, determinístico).

Cada rótulo é um texto radial: começa a ``offset`` da folha, na direção ``angle`` do ramo,
com largura ``width`` (ao longo da direção) e altura ``height``. Só a posição do texto muda
— a folha e a árvore ficam onde estão.

Algoritmo: os rótulos são colocados um a um, em ordem de ângulo. Para cada um, tenta-se a
posição original e depois pequenos ajustes (afastar radialmente e girar alguns graus para
cada lado, alternando), aceitando o primeiro que não encosta em nenhum rótulo já colocado
(colisão entre caixas rotacionadas pelo teorema do eixo separador, com uma grade espacial
para só comparar vizinhos). Se nenhum ajuste pequeno liberar, o rótulo é empurrado para
fora em passos maiores e ganha uma linha-guia até a folha. Há limite de tentativas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

RADIAL_STEPS = 6            # ajustes pequenos: até 6 passos de meia altura para fora
ROTATION_STEPS = (4.0, -4.0, 8.0, -8.0, 12.0, -12.0)     # graus, alternando os lados
FAR_STEPS = 60              # depois: até 60 passos de uma altura, com linha-guia
GAP = 0.5                   # folga mínima entre caixas (pt)


@dataclass
class LabelBox:
    key: str
    x: float                # folha
    y: float
    angle: float            # radianos (direção do ramo)
    offset: float           # distância da folha até o começo do texto
    width: float
    height: float


@dataclass
class Placement:
    key: str
    angle: float            # radianos (já com o giro)
    offset: float           # distância da folha até o começo do texto (já afastado)
    guide: bool = False     # desenhar linha-guia até a folha
    resolved: bool = True   # False = não achou lugar livre (fica no último tentado)


@dataclass
class _Rect:
    cx: float
    cy: float
    ux: float
    uy: float
    hw: float
    hh: float
    corners: list = field(default_factory=list)

    def __post_init__(self) -> None:
        vx, vy = -self.uy, self.ux
        self.corners = [(self.cx + sx * self.hw * self.ux + sy * self.hh * vx,
                         self.cy + sx * self.hw * self.uy + sy * self.hh * vy)
                        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]

    def aabb(self) -> tuple[float, float, float, float]:
        xs = [c[0] for c in self.corners]
        ys = [c[1] for c in self.corners]
        return min(xs), min(ys), max(xs), max(ys)


def oriented_rect(box: LabelBox, angle: float, offset: float, gap: float = 0.0) -> _Rect:
    ux, uy = math.cos(angle), math.sin(angle)
    d = offset + box.width / 2
    return _Rect(box.x + ux * d, box.y + uy * d, ux, uy, box.width / 2 + gap / 2, box.height / 2 + gap / 2)


def rects_overlap(a: _Rect, b: _Rect) -> bool:
    """Teorema do eixo separador para dois retângulos rotacionados."""
    for r in (a, b):
        for ax, ay in ((r.ux, r.uy), (-r.uy, r.ux)):
            pa = [x * ax + y * ay for x, y in a.corners]
            pb = [x * ax + y * ay for x, y in b.corners]
            if max(pa) <= min(pb) or max(pb) <= min(pa):
                return False
    return True


class _Grid:
    def __init__(self, cell: float) -> None:
        self.cell = max(cell, 1.0)
        self.cells: dict[tuple[int, int], list[_Rect]] = {}

    def _keys(self, r: _Rect):  # type: ignore[no-untyped-def]
        x0, y0, x1, y1 = r.aabb()
        c = self.cell
        for i in range(math.floor(x0 / c), math.floor(x1 / c) + 1):
            for j in range(math.floor(y0 / c), math.floor(y1 / c) + 1):
                yield i, j

    def hits(self, r: _Rect) -> bool:
        seen: set[int] = set()
        for k in self._keys(r):
            for other in self.cells.get(k, ()):
                if id(other) in seen:
                    continue
                seen.add(id(other))
                if rects_overlap(r, other):
                    return True
        return False

    def add(self, r: _Rect) -> None:
        for k in self._keys(r):
            self.cells.setdefault(k, []).append(r)


def count_overlaps(boxes: list[LabelBox], placements: list[Placement] | None = None) -> int:
    """Pares de rótulos que se sobrepõem (com as posições dadas, ou as originais)."""
    by_key = {p.key: p for p in placements or []}
    rects = []
    for b in boxes:
        p = by_key.get(b.key)
        rects.append(oriented_rect(b, p.angle if p else b.angle, p.offset if p else b.offset))
    n = 0
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if rects_overlap(rects[i], rects[j]):
                n += 1
    return n


def place_labels(boxes: list[LabelBox]) -> list[Placement]:
    """Posições sem sobreposição (mesma entrada → mesma saída). Devolve na ordem de ``boxes``."""
    if not boxes:
        return []
    h = max(b.height for b in boxes)
    grid = _Grid(max(max(b.width for b in boxes), h) / 2)
    order = sorted(boxes, key=lambda b: (math.atan2(b.y, b.x), math.atan2(math.sin(b.angle), math.cos(b.angle)), b.key))
    out: dict[str, Placement] = {}
    for b in order:
        found = None
        # 1) ajustes pequenos: afastar (meia altura por passo) × girar (alternando os lados)
        for k in range(RADIAL_STEPS + 1):
            for rot in (0.0, *ROTATION_STEPS):
                ang = b.angle + math.radians(rot)
                off = b.offset + k * b.height / 2
                r = oriented_rect(b, ang, off, GAP)
                if not grid.hits(r):
                    found = (Placement(b.key, ang, off), r)
                    break
            if found:
                break
        # 2) empurra para fora com linha-guia
        if found is None:
            last = None
            for k in range(1, FAR_STEPS + 1):
                off = b.offset + (RADIAL_STEPS / 2 + k) * b.height
                r = oriented_rect(b, b.angle, off, GAP)
                last = (Placement(b.key, b.angle, off, guide=True), r)
                if not grid.hits(r):
                    found = last
                    break
            if found is None and last is not None:
                last[0].resolved = False
                found = last
        assert found is not None
        p, r = found
        if not p.guide and p.offset - b.offset > 1.5 * b.height:
            p.guide = True                       # longe da folha: liga com uma linha fina
        grid.add(r)
        out[b.key] = p
    return [out[b.key] for b in boxes]
