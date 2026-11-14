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
    """Rótulos das folhas."""

    family: str = ""               # "" = fonte padrão do sistema
    size: float = 10.0
    bold: bool = False
    italic: bool = True            # nomes de espécie em itálico por padrão
    color: str = "#202020"
    show: bool = True


TIP_SHAPES: dict[str, str] = {"none": "Nenhum", "circle": "Círculo", "square": "Quadrado", "diamond": "Losango"}


@dataclass
class SymbolStyle:
    """Símbolos nas pontas das folhas."""

    shape: str = "none"            # chave de TIP_SHAPES
    size: float = 6.0
    color: str = "#202020"
    use_clade_color: bool = True


SUPPORT_MODES: dict[str, str] = {"none": "Não mostrar", "numbers": "Números", "symbols": "Símbolos nos nós"}


@dataclass
class SupportStyle:
    mode: str = "none"             # chave de SUPPORT_MODES
    index: int = -1                # 0/1 quando há "a/b"; -1 = último; 99 = todos
    threshold: float = 0.0         # números: oculta abaixo; símbolos: cheio se >= limiar
    symbol_size: float = 6.0
    size_by_value: bool = False
    color: str = "#555555"

    @property
    def show(self) -> bool:
        return self.mode != "none"


SCALE_POSITIONS: dict[str, str] = {
    "bottom-left": "Embaixo, à esquerda",
    "bottom-right": "Embaixo, à direita",
    "top-left": "Em cima, à esquerda",
    "top-right": "Em cima, à direita",
}


LEGEND_POSITIONS: dict[str, str] = {
    "top-right": "À direita, em cima",
    "bottom-right": "À direita, embaixo",
    "top-left": "À esquerda, em cima",
    "bottom-left": "À esquerda, embaixo",
}


@dataclass
class LegendStyle:
    """Legenda desenhada na própria figura (fora da árvore)."""

    in_figure: bool = False
    position: str = "top-right"    # chave de LEGEND_POSITIONS


@dataclass
class ScaleBarStyle:
    show: bool = True
    position: str = "bottom-left"  # chave de SCALE_POSITIONS
    length: float | None = None    # None = automático ("redondo")


@dataclass
class CladeStyle:
    palette: str = "Tableau 10"
    color_branches: bool = True
    color_labels: bool = True       # "Aplicar a rótulos (texto)"
    label_background: bool = False  # "Aplicar a rótulos (fundo)": marca-texto na cor do clado
    label_background_alpha: float = 0.35
    background: bool = False       # cunha/retângulo translúcido atrás do clado
    background_alpha: float = 0.18
    outer_strip: bool = False      # faixa de cor no anel externo / coluna
    strip_width: float = 12.0
    show_names: bool = False
    name_mode: str = "curved"      # circular: "curved" | "radial"
    neutral_color: str = "#8a8a8a" # folhas/ramos fora de qualquer clado
    cut_distance: float | None = None  # linha de corte (modo distância); None = oculta


@dataclass
class HeatmapStyle:
    """Colunas/anéis de presença e ausência de genes (aba GFF)."""

    present_color: str = "#2b6cb0"
    absent_color: str = "#ffffff"
    missing_color: str = "#d9d9d9"   # folha sem GFF mapeado ("sem dado")
    cell_width: float = 1.0           # em múltiplos do espaço entre folhas
    show_counts: bool = False         # nº de cópias quando > 1
    show_headers: bool = True         # nomes das colunas (retangular)
    borders: bool = True


@dataclass
class ContextStyle:
    """Contexto gênico (setas dos vizinhos) — layout retangular."""

    width: float = 360.0             # px da janela de contexto
    arrow_height: float = 0.7        # fração do espaço entre folhas
    show_labels: bool = True


@dataclass
class MetadataStyle:
    """Cores a partir da tabela de metadados (aba Metadados)."""

    color_by: str | None = None       # coluna usada para colorir rótulos/ramos
    color_labels: bool = True
    color_branches: bool = False
    strips: list[str] = field(default_factory=list)   # colunas desenhadas como faixas
    strip_width: float = 12.0
    missing_color: str = "#d9d9d9"    # folha sem valor na tabela


BAR_COLOR_MODES: dict[str, str] = {"single": "Cor única", "clade": "Por clado", "metadata": "Por metadado"}


@dataclass
class BarSpec:
    """Coluna de barras (aba Figura → Colunas de dados)."""

    id: str = ""                    # chave estável da trilha ("bar1", ...)
    source: str = "metadata"        # fonte de dados: "metadata" ou nome do arquivo carregado
    column: str = ""
    color_mode: str = "single"      # chave de BAR_COLOR_MODES
    color: str = "#4e79a7"
    show_values: bool = False
    refs: list[float] = field(default_factory=list)   # linhas de referência tracejadas
    vmin: float | None = None       # None = automático (0, ou o mínimo se houver negativos)
    vmax: float | None = None       # None = automático (o máximo)
    width: float = 80.0             # px da coluna (ou do anel)


@dataclass
class StackedSpec:
    """Barras empilhadas: várias colunas numéricas, cada série com sua cor."""

    id: str = ""
    source: str = "metadata"
    name: str = ""                  # título (vazio = nomes das séries)
    columns: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    vmax: float | None = None       # None = maior soma
    width: float = 100.0


MATRIX_SELECT: dict[str, str] = {"manual": "Escolher na lista", "top": "As N mais frequentes (soma)"}
HEADER_ROTATIONS = (0, 45, 90)


@dataclass
class MatrixSpec:
    """Matriz genomas × características desenhada como heatmap (ex.: famílias CAZy)."""

    id: str = ""
    source: str = ""
    name: str = ""
    select: str = "top"             # chave de MATRIX_SELECT
    features: list[str] = field(default_factory=list)   # usadas no modo "manual"
    top_n: int = 20
    scale: str = "linear"           # chave de colormaps.SCALES
    colormap: str = "viridis"
    vmin: float | None = None
    vmax: float | None = None
    header_rotation: int = 90       # 0, 45 ou 90
    show_values: bool = False
    cell_width: float = 1.0         # em múltiplos do espaço entre folhas


SCALE_MODES: dict[str, str] = {"gradient": "Colormap contínuo", "bins": "Por faixas"}


@dataclass
class ColumnScale:
    """Escala de cor de uma coluna numérica dos metadados (faixas e "colorir por")."""

    column: str = ""
    mode: str = "gradient"          # chave de SCALE_MODES
    colormap: str = "viridis"
    vmin: float | None = None
    vmax: float | None = None
    cutoffs: list[float] = field(default_factory=list)   # modo "bins": pontos de corte crescentes
    colors: list[str] = field(default_factory=list)      # modo "bins": len(cutoffs) + 1 cores


@dataclass
class FigureConfig:
    """Opções do painel "Figura" (todas desligadas por padrão)."""

    bars: list[BarSpec] = field(default_factory=list)
    stacked: list[StackedSpec] = field(default_factory=list)
    matrices: list[MatrixSpec] = field(default_factory=list)
    scales: list[ColumnScale] = field(default_factory=list)
    track_order: list[str] = field(default_factory=list)    # chaves das trilhas, da árvore para fora
    hidden_tracks: list[str] = field(default_factory=list)
    break_legend: bool = False                               # nota do ramo encurtado na legenda
    break_legend_text: str = "outgroup branch not to scale"


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
    symbols: SymbolStyle = field(default_factory=SymbolStyle)
    scale_bar: ScaleBarStyle = field(default_factory=ScaleBarStyle)
    heatmap: HeatmapStyle = field(default_factory=HeatmapStyle)
    metadata: MetadataStyle = field(default_factory=MetadataStyle)
    context: ContextStyle = field(default_factory=ContextStyle)
    clades: CladeStyle = field(default_factory=CladeStyle)
    legend: LegendStyle = field(default_factory=LegendStyle)
    figure: FigureConfig = field(default_factory=FigureConfig)
    background: str | None = "#ffffff"  # cor de fundo; None = transparente

    @property
    def font_size(self) -> float:
        return self.label.size

    def scale_for(self, column: str | None) -> ColumnScale | None:
        return next((sc for sc in self.figure.scales if sc.column == column), None) if column else None

    def palette_colors(self) -> list[str]:
        return PALETTES.get(self.clades.palette) or next(iter(PALETTES.values()))
