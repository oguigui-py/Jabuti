"""Opções de renderização (agrupadas) e paletas."""

from __future__ import annotations

from dataclasses import dataclass, field
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


GUIDE_KINDS: dict[str, str] = {
    "solid": "Contínua",
    "dash": "Tracejada",
    "dots": "Pontilhada (pontos pequenos)",
    "bigdots": "Pontilhada (pontos maiores)",
    "none": "Nenhuma",
}


@dataclass
class BranchStyle:
    width: float = 1.2
    color: str = "#202020"
    cap: str = "flat"               # "flat" (reta) | "round" (arredondada)
    width_by_support: bool = False  # espessura proporcional ao suporte
    min_width: float = 0.6
    max_width: float = 3.5


@dataclass
class GuideStyle:
    """Linha de ligação ponta da folha → anel externo."""

    kind: str = "dots"              # chave de GUIDE_KINDS
    color: str = "#a0a0a0"
    width: float = 0.6
    opacity: float = 1.0


@dataclass
class LabelStyle:
    size: float = 10.0
    color: str = "#202020"
    show: bool = True


@dataclass
class SupportStyle:
    show: bool = False
    index: int = -1                # 0/1 quando há "a/b"; -1 = último; 99 = todos
    threshold: float = 0.0


@dataclass
class CladeStyle:
    palette: str = "Tableau 10"
    color_branches: bool = True
    color_labels: bool = True
    background: bool = False       # cunha/retângulo translúcido atrás do clado
    background_alpha: float = 0.18
    outer_strip: bool = False      # faixa de cor no anel externo / coluna
    strip_width: float = 12.0
    show_names: bool = False
    name_mode: str = "curved"      # circular: "curved" | "radial"
    neutral_color: str = "#8a8a8a" # folhas/ramos fora de qualquer clado
    cut_distance: float | None = None  # linha de corte (modo distância); None = oculta


@dataclass
class RenderStyle:
    layout: LayoutKind = LayoutKind.RECTANGULAR
    branch_scale: float = 1.0      # multiplicador horizontal / radial
    leaf_spacing: float = 1.6      # espaçamento entre folhas em múltiplos da fonte
    use_lengths: bool = True       # False = cladograma
    align_tips: bool = True        # circular: pontas alinhadas no anel externo
    base_width: float = 600.0      # largura (px) da árvore com escala 1.0
    branch: BranchStyle = field(default_factory=BranchStyle)
    guide: GuideStyle = field(default_factory=GuideStyle)
    label: LabelStyle = field(default_factory=LabelStyle)
    support: SupportStyle = field(default_factory=SupportStyle)
    clades: CladeStyle = field(default_factory=CladeStyle)
    color_by: str | None = None    # coluna de metadados (Fase 2)

    @property
    def font_size(self) -> float:
        return self.label.size

    def palette_colors(self) -> list[str]:
        return PALETTES.get(self.clades.palette) or next(iter(PALETTES.values()))
