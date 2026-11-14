"""Opções de renderização e paletas."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

PALETTES: dict[str, list[str]] = {
    "Tableau 10": ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
                   "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"],
    "Set2": ["#66c2a5", "#fc8d62", "#8da0cb", "#e78ac3", "#a6d854",
             "#ffd92f", "#e5c494", "#b3b3b3"],
    "Paired": ["#a6cee3", "#1f78b4", "#b2df8a", "#33a02c", "#fb9a99", "#e31a1c",
               "#fdbf6f", "#ff7f00", "#cab2d6", "#6a3d9a", "#ffff99", "#b15928"],
    "Okabe-Ito (daltônico)": ["#e69f00", "#56b4e9", "#009e73", "#f0e442",
                              "#0072b2", "#d55e00", "#cc79a7", "#000000"],
}


class LayoutKind(str, Enum):
    RECTANGULAR = "rectangular"
    CIRCULAR = "circular"


@dataclass
class RenderStyle:
    layout: LayoutKind = LayoutKind.RECTANGULAR
    font_size: float = 10.0
    branch_scale: float = 1.0          # multiplicador horizontal / radial
    leaf_spacing: float = 1.6          # espaçamento entre folhas em múltiplos da fonte
    use_lengths: bool = True           # False = cladograma
    show_support: bool = False
    support_index: int = -1            # qual valor exibir quando há "a/b" (-1 = último; 99 = todos)
    support_threshold: float = 0.0     # só exibe suporte >= limiar
    show_leaf_labels: bool = True
    branch_width: float = 1.2
    palette: str = "Tableau 10"
    base_width: float = 600.0          # largura (px) da árvore com escala 1.0
