"""Painel fixo "Figura" (à esquerda): colunas de dados e demais opções da figura.

Tudo aqui vem desligado: sem tabelas nem colunas, o desenho não muda. As tabelas são
lidas numa thread (``FileLoader``) e mapeadas para as folhas com a mesma tabela editável
da aba GFF.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEventLoop, QSize, Qt, Signal, Slot
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from jabuti.models.datatables import METADATA_SOURCE, DataSource, numeric_column
from jabuti.models.tracks import parse_refs
from jabuti.parsers.metadata import load_metadata
from jabuti.models.colormaps import COLORMAPS, SCALES
from jabuti.models.tracks import feature_sums, natural_key
from jabuti.style import (
    BAR_COLOR_MODES,
    HEADER_ROTATIONS,
    MATRIX_SELECT,
    PALETTES,
    SCALE_MODES,
    BarSpec,
    ColumnScale,
    LayoutKind,
    MatrixSpec,
    RenderStyle,
    StackedSpec,
)
from jabuti.views.widgets.swatches import SwatchStrip
from jabuti.views.errors import show_error
from jabuti.views.widgets.collapsible import CollapsibleSection
from jabuti.views.widgets.leaf_mapping import LeafMappingTable, MappingRow
from jabuti.views.widgets.swatches import ColorButton
from jabuti.workers import FileLoader

TABLE_FILTER = "Tabelas (*.tsv *.tab *.csv *.txt);;Todos (*)"
NOT_FOR_UNROOTED = "Não se aplica à árvore não enraizada (não há um lado “de fora” para as colunas)."


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color: #888;")
    return lbl


def _parse_table(path: Path, _stop) -> object:  # type: ignore[no-untyped-def]
    return load_metadata(path)


class VerticalLabel(QWidget):
    """Texto girado 90° (faixa do painel recolhido)."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.text = text
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self.fontMetrics()
        return QSize(fm.height() + 6, fm.horizontalAdvance(self.text) + 12)

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        p = QPainter(self)
        p.setPen(self.palette().windowText().color())
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.translate(self.width() / 2 + self.fontMetrics().ascent() / 2 - 1, 8)
        p.rotate(90)
        p.drawText(0, 0, self.text)


class FigurePanel(QWidget):
    changed = Signal()
    status_message = Signal(str)
    tables_changed = Signal()
    table_loaded = Signal(bool)     # terminou de ler (ok?)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.leaves: list[str] = []
        self.sources: dict[str, DataSource] = {}
        self.bars: list[BarSpec] = []
        self.stacked: list[StackedSpec] = []
        self.matrices: list[MatrixSpec] = []
        self.scales: list[ColumnScale] = []
        self._custom_colors: dict[tuple[str, str], str] = {}   # cor escolhida para série desmarcada
        self.metadata_by_leaf = lambda: {}          # fornecido pela janela (aba Metadados)
        self.metadata_columns = lambda: []
        self.palette = PALETTES["Tableau 10"]
        self.layout_kind = LayoutKind.RECTANGULAR
        self._loader: FileLoader | None = None
        self._loaders: list[FileLoader] = []
        self._loading = False
        self._filling = False

        self.sections: dict[str, CollapsibleSection] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self._add_section(lay, "columns", "Colunas de dados", self._build_columns(), True)
        lay.addStretch(1)
        for cb in self.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(8)

    def _add_section(self, lay: QVBoxLayout, key: str, title: str, w: QWidget, expanded: bool) -> None:
        sec = CollapsibleSection(title, w, expanded)
        self.sections[key] = sec
        lay.addWidget(sec)

    def _emit(self, *_a) -> None:  # type: ignore[no-untyped-def]
        if not self._filling:
            self.changed.emit()

    # ------------------------------------------------------------ montagem
    def _build_columns(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 0, 0, 6)
        self.columns_box = w

        v.addWidget(QLabel("<b>Tabelas de dados</b>"))
        v.addWidget(_hint("TSV/CSV com uma linha por genoma; a 1ª coluna é o nome. NA ou vazio = sem dado. "
                          "A tabela da aba Metadados também pode ser usada."))
        row = QHBoxLayout()
        self.load_btn = QPushButton("Carregar tabela…")
        self.load_btn.clicked.connect(self._choose_table)
        self.remove_table_btn = QPushButton("Remover")
        self.remove_table_btn.clicked.connect(self.remove_current_table)
        row.addWidget(self.load_btn, 1)
        row.addWidget(self.remove_table_btn)
        v.addLayout(row)
        self.table_combo = QComboBox()
        self.table_combo.currentIndexChanged.connect(self._show_table)
        v.addWidget(self.table_combo)
        self.table_report = QLabel("")
        self.table_report.setWordWrap(True)
        v.addWidget(self.table_report)
        self.mapping_table = LeafMappingTable(["Nome", "Folha", ""], with_info=False)
        self.mapping_table.setMinimumHeight(120)
        self.mapping_table.setMaximumHeight(180)
        self.mapping_table.mapping_edited.connect(self._mapping_edited)
        v.addWidget(self.mapping_table)
        auto = QPushButton("Mapear automaticamente")
        auto.clicked.connect(self._auto_map_current)
        self.auto_btn = auto
        v.addWidget(auto)

        v.addWidget(QLabel("<b>Barras</b>"))
        brow = QHBoxLayout()
        self.add_bar_btn = QPushButton("+ Barras")
        self.add_bar_btn.setToolTip("Coluna de barras com uma coluna numérica")
        self.add_bar_btn.clicked.connect(self.add_bar)
        self.rm_bar_btn = QPushButton("Remover")
        self.rm_bar_btn.clicked.connect(self.remove_bar)
        brow.addWidget(self.add_bar_btn, 1)
        brow.addWidget(self.rm_bar_btn)
        v.addLayout(brow)
        self.bar_list = QListWidget()
        self.bar_list.setMaximumHeight(80)
        self.bar_list.currentRowChanged.connect(self._bar_selected)
        v.addWidget(self.bar_list)

        ed = QWidget()
        f = QFormLayout(ed)
        f.setContentsMargins(0, 0, 0, 0)
        self.bar_source = QComboBox()
        self.bar_source.currentIndexChanged.connect(self._bar_source_changed)
        self.bar_column = QComboBox()
        self.bar_column.currentIndexChanged.connect(self._bar_edited)
        self.bar_color_mode = QComboBox()
        for key, text in BAR_COLOR_MODES.items():
            self.bar_color_mode.addItem(text, key)
        self.bar_color_mode.setToolTip("Por metadado: usa a coluna escolhida em Estilo → Metadados → Colorir por")
        self.bar_color_mode.currentIndexChanged.connect(self._bar_edited)
        self.bar_color = ColorButton("#4e79a7", self.palette)
        self.bar_color.color_changed.connect(self._bar_edited)
        crow = QHBoxLayout()
        crow.addWidget(self.bar_color_mode, 1)
        crow.addWidget(self.bar_color)
        self.bar_values = QCheckBox("Mostrar o valor ao lado")
        self.bar_values.toggled.connect(self._bar_edited)
        self.bar_refs = QLineEdit()
        self.bar_refs.setPlaceholderText("ex.: 4; 8")
        self.bar_refs.setToolTip("Linhas tracejadas nesses valores (separe por ; ou espaço)")
        self.bar_refs.editingFinished.connect(self._bar_edited)
        self.bar_auto_min = QCheckBox("auto")
        self.bar_auto_max = QCheckBox("auto")
        self.bar_min = self._spin(-1e9, 1e9, 0.0)
        self.bar_max = self._spin(-1e9, 1e9, 1.0)
        for cb, sp in ((self.bar_auto_min, self.bar_min), (self.bar_auto_max, self.bar_max)):
            cb.setChecked(True)
            sp.setEnabled(False)
            cb.toggled.connect(lambda on, s=sp: s.setEnabled(not on))
            cb.toggled.connect(self._bar_edited)
            sp.valueChanged.connect(self._bar_edited)
        mrow = QHBoxLayout()
        mrow.addWidget(self.bar_min, 1)
        mrow.addWidget(self.bar_auto_min)
        xrow = QHBoxLayout()
        xrow.addWidget(self.bar_max, 1)
        xrow.addWidget(self.bar_auto_max)
        self.bar_width = self._spin(10, 600, 80, 5, " px")
        self.bar_width.valueChanged.connect(self._bar_edited)
        f.addRow("Tabela:", self.bar_source)
        f.addRow("Coluna:", self.bar_column)
        f.addRow("Cor:", crow)
        f.addRow(self.bar_values)
        f.addRow("Referências:", self.bar_refs)
        f.addRow("Mínimo:", mrow)
        f.addRow("Máximo:", xrow)
        f.addRow("Largura:", self.bar_width)
        self.bar_editor = ed
        v.addWidget(ed)
        self.bar_hint = _hint("")
        v.addWidget(self.bar_hint)
        v.addWidget(self._build_stacked())
        v.addWidget(self._build_matrix())
        v.addWidget(self._build_scales())
        self.layout_hint = _hint("")
        self.layout_hint.setVisible(False)
        v.addWidget(self.layout_hint)
        self.refresh_tables()
        self.refresh_bars()
        self.refresh_stacked()
        self.refresh_matrices()
        self.refresh_scales()
        return w

    def _build_scales(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        v.addWidget(QLabel("<b>Escalas dos metadados numéricos</b>"))
        v.addWidget(_hint("Vale para as faixas e para “Colorir por” (painel Estilo) de colunas numéricas "
                          "da aba Metadados."))
        f = QFormLayout()
        f.setContentsMargins(0, 0, 0, 0)
        self.sc_column = QComboBox()
        self.sc_column.currentIndexChanged.connect(self._scale_column_changed)
        self.sc_mode = QComboBox()
        self.sc_mode.addItem("Padrão (gradiente)", "")
        for key, text in SCALE_MODES.items():
            self.sc_mode.addItem(text, key)
        self.sc_mode.currentIndexChanged.connect(self._scale_edited)
        f.addRow("Coluna:", self.sc_column)
        f.addRow("Modo:", self.sc_mode)
        v.addLayout(f)
        grad = QWidget()
        g = QFormLayout(grad)
        g.setContentsMargins(0, 0, 0, 0)
        self.sc_cmap = QComboBox()
        for name in COLORMAPS:
            self.sc_cmap.addItem(name, name)
        self.sc_cmap.currentIndexChanged.connect(self._scale_edited)
        self.sc_strip = SwatchStrip(COLORMAPS["viridis"])
        self.sc_auto_min = QCheckBox("auto")
        self.sc_auto_max = QCheckBox("auto")
        self.sc_min = self._spin(-1e9, 1e9, 0.0)
        self.sc_max = self._spin(-1e9, 1e9, 1.0)
        for cb, sp in ((self.sc_auto_min, self.sc_min), (self.sc_auto_max, self.sc_max)):
            cb.setChecked(True)
            sp.setEnabled(False)
            cb.toggled.connect(lambda on, s=sp: s.setEnabled(not on))
            cb.toggled.connect(self._scale_edited)
            sp.valueChanged.connect(self._scale_edited)
        mrow = QHBoxLayout()
        mrow.addWidget(self.sc_min, 1)
        mrow.addWidget(self.sc_auto_min)
        xrow = QHBoxLayout()
        xrow.addWidget(self.sc_max, 1)
        xrow.addWidget(self.sc_auto_max)
        g.addRow("Cores:", self.sc_cmap)
        g.addRow(self.sc_strip)
        g.addRow("Mínimo:", mrow)
        g.addRow("Máximo:", xrow)
        self.sc_gradient = grad
        v.addWidget(grad)
        bins = QWidget()
        b = QFormLayout(bins)
        b.setContentsMargins(0, 0, 0, 0)
        self.sc_cutoffs = QLineEdit()
        self.sc_cutoffs.setPlaceholderText("ex.: 5; 50; 200")
        self.sc_cutoffs.setToolTip("Pontos de corte: ≤5, 6–50, 51–200, >200")
        self.sc_cutoffs.editingFinished.connect(self._scale_edited)
        self.sc_bin_colors = QWidget()
        self.sc_bin_layout = QHBoxLayout(self.sc_bin_colors)
        self.sc_bin_layout.setContentsMargins(0, 0, 0, 0)
        self.sc_bin_layout.setSpacing(3)
        self.sc_bin_labels = _hint("")
        b.addRow("Cortes:", self.sc_cutoffs)
        b.addRow("Cores:", self.sc_bin_colors)
        b.addRow(self.sc_bin_labels)
        self.sc_bins = bins
        v.addWidget(bins)
        self.scale_hint = _hint("")
        v.addWidget(self.scale_hint)
        return w

    def _build_matrix(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        v.addWidget(QLabel("<b>Matriz (heatmap externo)</b>"))
        v.addWidget(_hint("TSV genomas × características (ex.: famílias CAZy, peptidases, funções do "
                          "METABOLIC). Carregue-o em Tabelas de dados."))
        row = QHBoxLayout()
        self.add_matrix_btn = QPushButton("+ Matriz")
        self.add_matrix_btn.clicked.connect(self.add_matrix)
        self.rm_matrix_btn = QPushButton("Remover")
        self.rm_matrix_btn.clicked.connect(self.remove_matrix)
        row.addWidget(self.add_matrix_btn, 1)
        row.addWidget(self.rm_matrix_btn)
        v.addLayout(row)
        self.matrix_list = QListWidget()
        self.matrix_list.setMaximumHeight(60)
        self.matrix_list.currentRowChanged.connect(self._matrix_selected)
        v.addWidget(self.matrix_list)
        ed = QWidget()
        f = QFormLayout(ed)
        f.setContentsMargins(0, 0, 0, 0)
        self.mx_source = QComboBox()
        self.mx_source.currentIndexChanged.connect(self._matrix_source_changed)
        self.mx_name = QLineEdit()
        self.mx_name.setPlaceholderText("título da legenda")
        self.mx_name.editingFinished.connect(self._matrix_edited)
        self.mx_select = QComboBox()
        for key, text in MATRIX_SELECT.items():
            self.mx_select.addItem(text, key)
        self.mx_select.currentIndexChanged.connect(self._matrix_edited)
        self.mx_top = QSpinBox()
        self.mx_top.setRange(1, 500)
        self.mx_top.setValue(20)
        self.mx_top.valueChanged.connect(self._matrix_edited)
        self.mx_features = QListWidget()
        self.mx_features.setMaximumHeight(140)
        self.mx_features.setToolTip("Ordem natural (GH2, GH13, GT4…); entre parênteses, a soma nas folhas")
        self.mx_features.itemChanged.connect(self._matrix_edited)
        self.mx_scale = QComboBox()
        for key, text in SCALES.items():
            self.mx_scale.addItem(text, key)
        self.mx_scale.currentIndexChanged.connect(self._matrix_edited)
        self.mx_cmap = QComboBox()
        for name in COLORMAPS:
            self.mx_cmap.addItem(name, name)
        self.mx_cmap.currentIndexChanged.connect(self._matrix_edited)
        self.mx_strip = SwatchStrip(COLORMAPS["viridis"])
        self.mx_auto_min = QCheckBox("auto")
        self.mx_auto_max = QCheckBox("auto")
        self.mx_min = self._spin(-1e9, 1e9, 0.0)
        self.mx_max = self._spin(-1e9, 1e9, 1.0)
        for cb, sp in ((self.mx_auto_min, self.mx_min), (self.mx_auto_max, self.mx_max)):
            cb.setChecked(True)
            sp.setEnabled(False)
            cb.toggled.connect(lambda on, s=sp: s.setEnabled(not on))
            cb.toggled.connect(self._matrix_edited)
            sp.valueChanged.connect(self._matrix_edited)
        mrow = QHBoxLayout()
        mrow.addWidget(self.mx_min, 1)
        mrow.addWidget(self.mx_auto_min)
        xrow = QHBoxLayout()
        xrow.addWidget(self.mx_max, 1)
        xrow.addWidget(self.mx_auto_max)
        self.mx_rotation = QComboBox()
        for deg in HEADER_ROTATIONS:
            self.mx_rotation.addItem(f"{deg}°", deg)
        self.mx_rotation.setToolTip("Rotação dos nomes das colunas (layout retangular)")
        self.mx_rotation.currentIndexChanged.connect(self._matrix_edited)
        self.mx_values = QCheckBox("Mostrar o valor na célula")
        self.mx_values.toggled.connect(self._matrix_edited)
        self.mx_width = self._spin(0.3, 5.0, 1.0, 0.1, " ×")
        self.mx_width.setToolTip("Largura da célula em múltiplos do espaço entre folhas")
        self.mx_width.valueChanged.connect(self._matrix_edited)
        f.addRow("Tabela:", self.mx_source)
        f.addRow("Título:", self.mx_name)
        f.addRow("Colunas:", self.mx_select)
        f.addRow("N:", self.mx_top)
        f.addRow(self.mx_features)
        f.addRow("Escala:", self.mx_scale)
        f.addRow("Cores:", self.mx_cmap)
        f.addRow(self.mx_strip)
        f.addRow("Mínimo:", mrow)
        f.addRow("Máximo:", xrow)
        f.addRow("Nomes:", self.mx_rotation)
        f.addRow(self.mx_values)
        f.addRow("Célula:", self.mx_width)
        self.matrix_editor = ed
        v.addWidget(ed)
        self.matrix_hint = _hint("")
        v.addWidget(self.matrix_hint)
        return w

    def _build_stacked(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        v.addWidget(QLabel("<b>Barras empilhadas</b>"))
        row = QHBoxLayout()
        self.add_stacked_btn = QPushButton("+ Empilhadas")
        self.add_stacked_btn.setToolTip("Várias colunas numéricas (ex.: GH, GT, CE…) empilhadas numa barra")
        self.add_stacked_btn.clicked.connect(self.add_stacked)
        self.rm_stacked_btn = QPushButton("Remover")
        self.rm_stacked_btn.clicked.connect(self.remove_stacked)
        row.addWidget(self.add_stacked_btn, 1)
        row.addWidget(self.rm_stacked_btn)
        v.addLayout(row)
        self.stacked_list = QListWidget()
        self.stacked_list.setMaximumHeight(60)
        self.stacked_list.currentRowChanged.connect(self._stacked_selected)
        v.addWidget(self.stacked_list)
        ed = QWidget()
        f = QFormLayout(ed)
        f.setContentsMargins(0, 0, 0, 0)
        self.st_source = QComboBox()
        self.st_source.currentIndexChanged.connect(self._stacked_source_changed)
        self.st_name = QLineEdit()
        self.st_name.setPlaceholderText("título (vazio = séries)")
        self.st_name.editingFinished.connect(self._stacked_edited)
        self.st_series = QListWidget()
        self.st_series.setMaximumHeight(120)
        self.st_series.setToolTip("Marque as séries; a ordem é a da tabela (de dentro para fora)")
        self.st_series.itemChanged.connect(self._stacked_edited)
        self.st_series.currentRowChanged.connect(self._series_selected)
        self.st_color = ColorButton("#4e79a7", self.palette)
        self.st_color.color_changed.connect(self._series_color_changed)
        crow = QHBoxLayout()
        crow.addWidget(QLabel("Cor da série selecionada:"), 1)
        crow.addWidget(self.st_color)
        self.st_auto_max = QCheckBox("auto")
        self.st_auto_max.setChecked(True)
        self.st_max = self._spin(0, 1e9, 1.0)
        self.st_max.setEnabled(False)
        self.st_auto_max.toggled.connect(lambda on: self.st_max.setEnabled(not on))
        self.st_auto_max.toggled.connect(self._stacked_edited)
        self.st_max.valueChanged.connect(self._stacked_edited)
        mrow = QHBoxLayout()
        mrow.addWidget(self.st_max, 1)
        mrow.addWidget(self.st_auto_max)
        self.st_width = self._spin(10, 600, 100, 5, " px")
        self.st_width.valueChanged.connect(self._stacked_edited)
        f.addRow("Tabela:", self.st_source)
        f.addRow("Título:", self.st_name)
        f.addRow(self.st_series)
        f.addRow(crow)
        f.addRow("Máximo:", mrow)
        f.addRow("Largura:", self.st_width)
        self.stacked_editor = ed
        v.addWidget(ed)
        self.stacked_hint = _hint("")
        v.addWidget(self.stacked_hint)
        return w

    def _spin(self, lo: float, hi: float, val: float, step: float = 1.0, suffix: str = "") -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(2 if step < 1 else 1)
        sb.setSingleStep(step)
        sb.setValue(val)
        sb.setSuffix(suffix)
        sb.setMinimumWidth(60)
        sb.setMaximumWidth(120)
        return sb

    # ------------------------------------------------------------- árvore
    def set_leaves(self, leaves: list[str]) -> None:
        self.leaves = list(leaves)
        for src in self.sources.values():
            src.mapping.set_leaves(self.leaves)
        self._show_table()

    def set_palette(self, colors: list[str]) -> None:
        self.palette = list(colors)
        self.bar_color.palette_colors = self.palette
        self.st_color.palette_colors = self.palette

    def set_layout(self, kind: LayoutKind) -> None:
        """Desativa (com dica) o que não se aplica ao layout."""
        self.layout_kind = LayoutKind(kind)
        ok = self.layout_kind.value != "unrooted"
        for wdg in (self.add_bar_btn, self.bar_editor, self.bar_list,
                    self.add_stacked_btn, self.stacked_editor, self.stacked_list,
                    self.add_matrix_btn, self.matrix_editor, self.matrix_list):
            wdg.setEnabled(ok)
            wdg.setToolTip("" if ok else NOT_FOR_UNROOTED)
        self.layout_hint.setText("" if ok else NOT_FOR_UNROOTED)
        self.layout_hint.setVisible(not ok)

    # ------------------------------------------------------------ tabelas
    def _choose_table(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Carregar tabela de dados", "", TABLE_FILTER)
        if path:
            self.load_table(path, wait=False)

    def is_loading(self) -> bool:
        return self._loading

    def load_table(self, path: str | Path, wait: bool = True) -> bool:
        """Lê a tabela numa thread; com ``wait=True`` espera (processando eventos)."""
        if self._loading:
            self.status_message.emit("Aguarde a leitura em andamento.")
            return False
        p = Path(path)
        loader = FileLoader([p], _parse_table)
        q = Qt.ConnectionType.QueuedConnection
        loader.items.connect(self._on_table_items, q)
        loader.finished.connect(self._on_table_finished, q)
        self._loader = loader
        self._loaders = [w for w in self._loaders if w.is_running()] + [loader]
        self._loading = True
        self._last_ok = False
        self.load_btn.setEnabled(False)
        self.table_report.setText(f"Lendo {p.name}…")
        self.status_message.emit(f"Lendo {p.name}…")
        loader.start()
        if wait:
            loop = QEventLoop()
            self.table_loaded.connect(loop.quit)
            if self._loading:
                loop.exec()
            self.table_loaded.disconnect(loop.quit)
        return self._last_ok

    @Slot(list)
    def _on_table_items(self, items: list) -> None:
        for ok, path, result in items:
            if not ok:
                show_error(self, Exception(result), "Erro ao ler tabela")
                continue
            p = Path(path)
            src = DataSource(p.name, result, p)
            src.mapping.leaves = list(self.leaves)
            src.mapping.auto_map()
            self.sources[src.name] = src
            self._last_ok = True
            warn = (" ⚠ " + " ".join(result.warnings[:3])) if result.warnings else ""
            self.status_message.emit(f"Tabela {p.name}: {len(result.rows)} linhas, "
                                     f"{len(src.mapping.mapped())}/{len(self.leaves)} folhas com dados.{warn}")

    @Slot(bool)
    def _on_table_finished(self, _cancelled: bool) -> None:
        self._loading = False
        self._loader = None
        self.load_btn.setEnabled(True)
        if self._last_ok:
            self.refresh_tables(select=list(self.sources)[-1])
            self.tables_changed.emit()
            self._emit()
        else:
            self._show_table()
        self.table_loaded.emit(self._last_ok)

    def shutdown(self, timeout_ms: int = 5000) -> None:
        for loader in self._loaders:
            loader.cancel()
            loader.join(timeout_ms / 1000)
        self._loaders = [w for w in self._loaders if w.is_running()]

    def remove_current_table(self) -> None:
        name = self.table_combo.currentData()
        if name and name != METADATA_SOURCE and name in self.sources:
            del self.sources[name]
            self.refresh_tables()
            self.tables_changed.emit()
            self._emit()

    def source_names(self) -> list[str]:
        return [METADATA_SOURCE, *self.sources]

    def source_label(self, name: str) -> str:
        return "Metadados (aba)" if name == METADATA_SOURCE else name

    def by_leaf(self, source: str) -> dict[str, dict[str, str]]:
        if source == METADATA_SOURCE:
            return self.metadata_by_leaf()
        src = self.sources.get(source)
        return src.by_leaf() if src else {}

    def columns_of(self, source: str, numeric: bool = True) -> list[str]:
        if source == METADATA_SOURCE:
            cols = list(self.metadata_columns())
            if not numeric:
                return cols
            rows = self.metadata_by_leaf()
            return [c for c in cols if numeric_column(rows, c)]
        src = self.sources.get(source)
        if src is None:
            return []
        return src.numeric_columns() if numeric else src.value_columns

    def refresh_tables(self, select: str | None = None) -> None:
        current = select or self.table_combo.currentData()
        self.table_combo.blockSignals(True)
        self.table_combo.clear()
        for name in self.source_names():
            self.table_combo.addItem(self.source_label(name), name)
        idx = self.table_combo.findData(current)
        self.table_combo.setCurrentIndex(max(idx, 0))
        self.table_combo.blockSignals(False)
        self._show_table()
        self._refresh_bar_sources()

    def _show_table(self) -> None:
        name = self.table_combo.currentData()
        src = self.sources.get(name) if name else None
        meta = name == METADATA_SOURCE or src is None
        self.mapping_table.setVisible(not meta)
        self.auto_btn.setVisible(not meta)
        self.remove_table_btn.setEnabled(not meta)
        if meta:
            n = len(self.metadata_by_leaf())
            self.table_report.setText(
                f"Metadados da aba Metadados: {n}/{len(self.leaves)} folhas com linha "
                "(o mapeamento fica naquela aba)." if n else "Sem metadados carregados (aba Metadados).")
            return
        m = src.mapping
        rows = [MappingRow(k, m.mapping.get(k), k in m.manual) for k in m.keys]
        self.mapping_table.fill(rows, self.leaves)
        parts = [f"<b>{src.name}</b>: {len(src.table.rows)} linhas, {len(src.value_columns)} colunas · "
                 f"{len(m.mapped())}/{len(self.leaves)} folhas com dados."]
        missing = m.leaves_without()
        if missing and self.leaves:
            more = "…" if len(missing) > 6 else ""
            parts.append(f"⚠ Sem dados ({len(missing)}): {', '.join(missing[:6])}{more}")
        if m.unused_keys():
            parts.append(f"Linhas sem folha: {len(m.unused_keys())}")
        self.table_report.setText("<br>".join(parts))
        self.table_report.setToolTip("\n".join(missing))

    def _mapping_edited(self, key: str, leaf) -> None:  # type: ignore[no-untyped-def]
        src = self.sources.get(self.table_combo.currentData())
        if src is None:
            return
        src.mapping.set(key, leaf)
        self._show_table()
        self._emit()

    def _auto_map_current(self) -> None:
        src = self.sources.get(self.table_combo.currentData())
        if src is not None:
            src.mapping.auto_map(reset=True)
            self._show_table()
            self._emit()

    def metadata_changed(self) -> None:
        """A aba Metadados mudou (arquivo, chave ou colunas)."""
        self._show_table()
        self._refresh_bar_sources()

    # -------------------------------------------------------------- barras
    def _next_id(self, prefix: str, used: list[str]) -> str:
        n = 1
        while f"{prefix}{n}" in used:
            n += 1
        return f"{prefix}{n}"

    def add_bar(self) -> BarSpec | None:
        source = next((s for s in reversed(self.source_names()) if self.columns_of(s)), None)
        if source is None:
            self.bar_hint.setText("Carregue uma tabela com colunas numéricas (aqui ou na aba Metadados).")
            return None
        spec = BarSpec(id=self._next_id("bar", [b.id for b in self.bars]), source=source,
                       column=self.columns_of(source)[0],
                       color=self.palette[len(self.bars) % len(self.palette)])
        self.bars.append(spec)
        self.refresh_bars(select=len(self.bars) - 1)
        self._emit()
        return spec

    def remove_bar(self) -> None:
        row = self.bar_list.currentRow()
        if 0 <= row < len(self.bars):
            del self.bars[row]
            self.refresh_bars(select=min(row, len(self.bars) - 1))
            self._emit()

    def current_bar(self) -> BarSpec | None:
        row = self.bar_list.currentRow()
        return self.bars[row] if 0 <= row < len(self.bars) else None

    def refresh_bars(self, select: int | None = None) -> None:
        row = self.bar_list.currentRow() if select is None else select
        self.bar_list.blockSignals(True)
        self.bar_list.clear()
        for b in self.bars:
            item = QListWidgetItem(f"{b.column}  ({self.source_label(b.source)})")
            if b.source != METADATA_SOURCE and b.source not in self.sources or \
                    b.column not in self.columns_of(b.source):
                item.setText(f"⚠ {b.column}  ({self.source_label(b.source)}: sem dados)")
            self.bar_list.addItem(item)
        self.bar_list.blockSignals(False)
        self.bar_list.setVisible(bool(self.bars))
        if self.bars:
            self.bar_list.setCurrentRow(max(0, min(row, len(self.bars) - 1)))
        self._bar_selected(self.bar_list.currentRow())

    def _refresh_bar_sources(self) -> None:
        if hasattr(self, "bar_list"):
            self.refresh_bars()
        if hasattr(self, "stacked_list"):
            self.refresh_stacked()
        if hasattr(self, "matrix_list"):
            self.refresh_matrices()
        if hasattr(self, "sc_column"):
            self.refresh_scales()

    def _bar_selected(self, row: int) -> None:
        spec = self.bars[row] if 0 <= row < len(self.bars) else None
        self.bar_editor.setVisible(spec is not None)
        self.rm_bar_btn.setEnabled(spec is not None)
        if spec is None:
            return
        self._filling = True
        try:
            self.bar_source.clear()
            for name in self.source_names():
                self.bar_source.addItem(self.source_label(name), name)
            if self.bar_source.findData(spec.source) < 0:
                self.bar_source.addItem(f"⚠ {spec.source}", spec.source)
            self.bar_source.setCurrentIndex(self.bar_source.findData(spec.source))
            self._fill_bar_columns(spec)
            self.bar_color_mode.setCurrentIndex(max(self.bar_color_mode.findData(spec.color_mode), 0))
            self.bar_color.set_color(spec.color)
            self.bar_values.setChecked(spec.show_values)
            self.bar_refs.setText("; ".join(f"{r:g}" for r in spec.refs))
            self.bar_auto_min.setChecked(spec.vmin is None)
            self.bar_auto_max.setChecked(spec.vmax is None)
            if spec.vmin is not None:
                self.bar_min.setValue(spec.vmin)
            if spec.vmax is not None:
                self.bar_max.setValue(spec.vmax)
            self.bar_width.setValue(spec.width)
        finally:
            self._filling = False

    def _fill_bar_columns(self, spec: BarSpec) -> None:
        self.bar_column.clear()
        cols = self.columns_of(spec.source)
        for c in cols:
            self.bar_column.addItem(c, c)
        if spec.column and spec.column not in cols:
            self.bar_column.addItem(f"⚠ {spec.column} (ausente)", spec.column)
        self.bar_column.setCurrentIndex(max(self.bar_column.findData(spec.column), 0))

    def _bar_source_changed(self) -> None:
        spec = self.current_bar()
        if spec is None or self._filling:
            return
        spec.source = self.bar_source.currentData()
        cols = self.columns_of(spec.source)
        if spec.column not in cols:
            spec.column = cols[0] if cols else spec.column
        self._filling = True
        try:
            self._fill_bar_columns(spec)
        finally:
            self._filling = False
        self._bar_edited()

    def _bar_edited(self, *_a) -> None:  # type: ignore[no-untyped-def]
        spec = self.current_bar()
        if spec is None or self._filling:
            return
        spec.column = self.bar_column.currentData() or spec.column
        spec.color_mode = self.bar_color_mode.currentData()
        spec.color = self.bar_color.color()
        spec.show_values = self.bar_values.isChecked()
        try:
            spec.refs = parse_refs(self.bar_refs.text())
            self.bar_hint.setText("")
        except ValueError as exc:
            self.bar_hint.setText(f"⚠ {exc}")
        spec.vmin = None if self.bar_auto_min.isChecked() else self.bar_min.value()
        spec.vmax = None if self.bar_auto_max.isChecked() else self.bar_max.value()
        spec.width = self.bar_width.value()
        row = self.bar_list.currentRow()
        item = self.bar_list.item(row)
        if item is not None:
            item.setText(f"{spec.column}  ({self.source_label(spec.source)})")
        self._emit()

    # --------------------------------------------------------- empilhadas
    def add_stacked(self) -> StackedSpec | None:
        source = next((s for s in reversed(self.source_names()) if len(self.columns_of(s)) >= 2), None)
        if source is None:
            self.stacked_hint.setText("Carregue uma tabela com pelo menos duas colunas numéricas.")
            return None
        cols = self.columns_of(source)
        spec = StackedSpec(id=self._next_id("stk", [x.id for x in self.stacked]), source=source,
                           columns=list(cols), colors=[self.palette[i % len(self.palette)] for i in range(len(cols))])
        self.stacked.append(spec)
        self.stacked_hint.setText("")
        self.refresh_stacked(select=len(self.stacked) - 1)
        self._emit()
        return spec

    def remove_stacked(self) -> None:
        row = self.stacked_list.currentRow()
        if 0 <= row < len(self.stacked):
            del self.stacked[row]
            self.refresh_stacked(select=min(row, len(self.stacked) - 1))
            self._emit()

    def current_stacked(self) -> StackedSpec | None:
        row = self.stacked_list.currentRow()
        return self.stacked[row] if 0 <= row < len(self.stacked) else None

    def _stacked_title(self, spec: StackedSpec) -> str:
        title = spec.name or "/".join(spec.columns) or "(nenhuma série)"
        ok = (spec.source == METADATA_SOURCE or spec.source in self.sources) and \
            any(c in self.columns_of(spec.source) for c in spec.columns)
        return f"{title}  ({self.source_label(spec.source)})" if ok else f"⚠ {title}  ({spec.source}: sem dados)"

    def refresh_stacked(self, select: int | None = None) -> None:
        row = self.stacked_list.currentRow() if select is None else select
        self.stacked_list.blockSignals(True)
        self.stacked_list.clear()
        for spec in self.stacked:
            self.stacked_list.addItem(self._stacked_title(spec))
        self.stacked_list.blockSignals(False)
        self.stacked_list.setVisible(bool(self.stacked))
        if self.stacked:
            self.stacked_list.setCurrentRow(max(0, min(row, len(self.stacked) - 1)))
        self._stacked_selected(self.stacked_list.currentRow())

    def _stacked_selected(self, row: int) -> None:
        spec = self.stacked[row] if 0 <= row < len(self.stacked) else None
        self.stacked_editor.setVisible(spec is not None)
        self.rm_stacked_btn.setEnabled(spec is not None)
        if spec is None:
            return
        self._filling = True
        try:
            self.st_source.clear()
            for name in self.source_names():
                self.st_source.addItem(self.source_label(name), name)
            if self.st_source.findData(spec.source) < 0:
                self.st_source.addItem(f"⚠ {spec.source}", spec.source)
            self.st_source.setCurrentIndex(self.st_source.findData(spec.source))
            self.st_name.setText(spec.name)
            self._fill_series(spec)
            self.st_auto_max.setChecked(spec.vmax is None)
            if spec.vmax is not None:
                self.st_max.setValue(spec.vmax)
            self.st_width.setValue(spec.width)
        finally:
            self._filling = False

    def _series_color(self, spec: StackedSpec, column: str, index: int) -> str:
        if column in spec.columns and spec.columns.index(column) < len(spec.colors):
            return spec.colors[spec.columns.index(column)]
        return self.palette[index % len(self.palette)]

    def _fill_series(self, spec: StackedSpec) -> None:
        from PySide6.QtGui import QColor, QIcon, QPixmap

        was = self.st_series.blockSignals(True)
        self.st_series.clear()
        available = self.columns_of(spec.source)
        names = available + [c for c in spec.columns if c not in available]
        for i, c in enumerate(names):
            item = QListWidgetItem(c if c in available else f"⚠ {c} (ausente)")
            item.setData(Qt.ItemDataRole.UserRole, c)
            pm = QPixmap(12, 12)
            pm.fill(QColor(self._series_color(spec, c, i)))
            item.setIcon(QIcon(pm))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if c in spec.columns else Qt.CheckState.Unchecked)
            self.st_series.addItem(item)
        self.st_series.blockSignals(was)
        if self.st_series.count():
            self.st_series.setCurrentRow(0)

    def _series_selected(self, row: int) -> None:
        spec = self.current_stacked()
        item = self.st_series.item(row)
        if spec is None or item is None:
            return
        self.st_color.set_color(self._series_color(spec, item.data(Qt.ItemDataRole.UserRole), row))

    def _series_color_changed(self, color: str) -> None:
        spec = self.current_stacked()
        item = self.st_series.currentItem()
        if spec is None or item is None:
            return
        col = item.data(Qt.ItemDataRole.UserRole)
        self._sync_series(spec)
        if col in spec.columns:
            spec.colors[spec.columns.index(col)] = color
        self._custom_colors[(spec.id, col)] = color
        from PySide6.QtGui import QColor, QIcon, QPixmap

        pm = QPixmap(12, 12)
        pm.fill(QColor(color))
        item.setIcon(QIcon(pm))
        self._emit()

    def _sync_series(self, spec: StackedSpec) -> None:
        """Séries marcadas, na ordem da lista, mantendo as cores já escolhidas."""
        old = dict(zip(spec.columns, spec.colors))
        custom = self._custom_colors
        cols, colors = [], []
        for i in range(self.st_series.count()):
            item = self.st_series.item(i)
            c = item.data(Qt.ItemDataRole.UserRole)
            if item.checkState() == Qt.CheckState.Checked:
                cols.append(c)
                colors.append(old.get(c) or custom.get((spec.id, c)) or self.palette[i % len(self.palette)])
        spec.columns, spec.colors = cols, colors

    def _stacked_source_changed(self) -> None:
        spec = self.current_stacked()
        if spec is None or self._filling:
            return
        spec.source = self.st_source.currentData()
        cols = self.columns_of(spec.source)
        spec.columns = [c for c in spec.columns if c in cols] or list(cols)
        spec.colors = [self.palette[i % len(self.palette)] for i in range(len(spec.columns))]
        self._filling = True
        try:
            self._fill_series(spec)
        finally:
            self._filling = False
        self._stacked_edited()

    def _stacked_edited(self, *_a) -> None:  # type: ignore[no-untyped-def]
        spec = self.current_stacked()
        if spec is None or self._filling:
            return
        self._sync_series(spec)
        spec.name = self.st_name.text().strip()
        spec.vmax = None if self.st_auto_max.isChecked() else self.st_max.value()
        spec.width = self.st_width.value()
        item = self.stacked_list.item(self.stacked_list.currentRow())
        if item is not None:
            item.setText(self._stacked_title(spec))
        self.stacked_hint.setText("" if spec.columns else "Marque pelo menos uma série.")
        self._emit()

    # -------------------------------------------------------------- matriz
    def add_matrix(self) -> MatrixSpec | None:
        source = next((s for s in reversed(list(self.sources)) if self.columns_of(s)), None)
        if source is None:
            self.matrix_hint.setText("Carregue a matriz (TSV genomas × características) em Tabelas de dados.")
            return None
        spec = MatrixSpec(id=self._next_id("mtx", [m.id for m in self.matrices]), source=source,
                          name=Path(source).stem)
        self.matrices.append(spec)
        self.matrix_hint.setText("")
        self.refresh_matrices(select=len(self.matrices) - 1)
        self._emit()
        return spec

    def remove_matrix(self) -> None:
        row = self.matrix_list.currentRow()
        if 0 <= row < len(self.matrices):
            del self.matrices[row]
            self.refresh_matrices(select=min(row, len(self.matrices) - 1))
            self._emit()

    def current_matrix(self) -> MatrixSpec | None:
        row = self.matrix_list.currentRow()
        return self.matrices[row] if 0 <= row < len(self.matrices) else None

    def _matrix_title(self, spec: MatrixSpec) -> str:
        ok = spec.source in self.sources or spec.source == METADATA_SOURCE
        mode = f"top {spec.top_n}" if spec.select == "top" else f"{len(spec.features)} escolhidas"
        title = spec.name or spec.source
        return f"{title}  ({mode})" if ok else f"⚠ {title}  ({spec.source}: sem dados)"

    def refresh_matrices(self, select: int | None = None) -> None:
        row = self.matrix_list.currentRow() if select is None else select
        self.matrix_list.blockSignals(True)
        self.matrix_list.clear()
        for spec in self.matrices:
            self.matrix_list.addItem(self._matrix_title(spec))
        self.matrix_list.blockSignals(False)
        self.matrix_list.setVisible(bool(self.matrices))
        if self.matrices:
            self.matrix_list.setCurrentRow(max(0, min(row, len(self.matrices) - 1)))
        self._matrix_selected(self.matrix_list.currentRow())

    def _matrix_selected(self, row: int) -> None:
        spec = self.matrices[row] if 0 <= row < len(self.matrices) else None
        self.matrix_editor.setVisible(spec is not None)
        self.rm_matrix_btn.setEnabled(spec is not None)
        if spec is None:
            return
        self._filling = True
        try:
            self.mx_source.clear()
            for name in self.source_names():
                self.mx_source.addItem(self.source_label(name), name)
            if self.mx_source.findData(spec.source) < 0:
                self.mx_source.addItem(f"⚠ {spec.source}", spec.source)
            self.mx_source.setCurrentIndex(self.mx_source.findData(spec.source))
            self.mx_name.setText(spec.name)
            self.mx_select.setCurrentIndex(max(self.mx_select.findData(spec.select), 0))
            self.mx_top.setValue(spec.top_n)
            self._fill_features(spec)
            self.mx_scale.setCurrentIndex(max(self.mx_scale.findData(spec.scale), 0))
            self.mx_cmap.setCurrentIndex(max(self.mx_cmap.findData(spec.colormap), 0))
            self.mx_strip.colors = COLORMAPS.get(spec.colormap, COLORMAPS["viridis"])
            self.mx_strip.update()
            self.mx_auto_min.setChecked(spec.vmin is None)
            self.mx_auto_max.setChecked(spec.vmax is None)
            if spec.vmin is not None:
                self.mx_min.setValue(spec.vmin)
            if spec.vmax is not None:
                self.mx_max.setValue(spec.vmax)
            self.mx_rotation.setCurrentIndex(max(self.mx_rotation.findData(spec.header_rotation), 0))
            self.mx_values.setChecked(spec.show_values)
            self.mx_width.setValue(spec.cell_width)
            self._sync_matrix_mode(spec)
        finally:
            self._filling = False

    def _fill_features(self, spec: MatrixSpec) -> None:
        was = self.mx_features.blockSignals(True)
        self.mx_features.clear()
        available = self.columns_of(spec.source)
        sums = feature_sums(self.by_leaf(spec.source), available)
        for c in sorted(available, key=natural_key):
            item = QListWidgetItem(f"{c}  ({sums[c]:g})")
            item.setData(Qt.ItemDataRole.UserRole, c)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if c in spec.features else Qt.CheckState.Unchecked)
            self.mx_features.addItem(item)
        self.mx_features.blockSignals(was)

    def _sync_matrix_mode(self, spec: MatrixSpec) -> None:
        manual = spec.select == "manual"
        self.mx_features.setEnabled(manual)
        self.mx_top.setEnabled(not manual)

    def _matrix_source_changed(self) -> None:
        spec = self.current_matrix()
        if spec is None or self._filling:
            return
        spec.source = self.mx_source.currentData()
        spec.features = [c for c in spec.features if c in self.columns_of(spec.source)]
        self._filling = True
        try:
            self._fill_features(spec)
        finally:
            self._filling = False
        self._matrix_edited()

    def _matrix_edited(self, *_a) -> None:  # type: ignore[no-untyped-def]
        spec = self.current_matrix()
        if spec is None or self._filling:
            return
        spec.name = self.mx_name.text().strip()
        spec.select = self.mx_select.currentData()
        spec.top_n = self.mx_top.value()
        spec.features = [self.mx_features.item(i).data(Qt.ItemDataRole.UserRole)
                         for i in range(self.mx_features.count())
                         if self.mx_features.item(i).checkState() == Qt.CheckState.Checked]
        spec.scale = self.mx_scale.currentData()
        spec.colormap = self.mx_cmap.currentData()
        self.mx_strip.colors = COLORMAPS[spec.colormap]
        self.mx_strip.update()
        spec.vmin = None if self.mx_auto_min.isChecked() else self.mx_min.value()
        spec.vmax = None if self.mx_auto_max.isChecked() else self.mx_max.value()
        spec.header_rotation = self.mx_rotation.currentData()
        spec.show_values = self.mx_values.isChecked()
        spec.cell_width = self.mx_width.value()
        self._sync_matrix_mode(spec)
        item = self.matrix_list.item(self.matrix_list.currentRow())
        if item is not None:
            item.setText(self._matrix_title(spec))
        self._emit()

    # ------------------------------------------------------------- escalas
    def scale_for(self, column: str | None) -> ColumnScale | None:
        return next((sc for sc in self.scales if sc.column == column), None)

    def refresh_scales(self) -> None:
        current = self.sc_column.currentData()
        cols = self.columns_of(METADATA_SOURCE)
        names = cols + [sc.column for sc in self.scales if sc.column not in cols]
        self.sc_column.blockSignals(True)
        self.sc_column.clear()
        for c in names:
            label = c if c in cols else f"⚠ {c} (ausente)"
            if self.scale_for(c) is not None:
                label += "  ✎"
            self.sc_column.addItem(label, c)
        idx = self.sc_column.findData(current)
        self.sc_column.setCurrentIndex(max(idx, 0))
        self.sc_column.setEnabled(bool(names))
        self.sc_column.blockSignals(False)
        if not names:
            self.scale_hint.setText("Carregue metadados com colunas numéricas (aba Metadados).")
        else:
            self.scale_hint.setText("")
        self._scale_column_changed()

    def _scale_column_changed(self) -> None:
        col = self.sc_column.currentData()
        sc = self.scale_for(col)
        self._filling = True
        try:
            self.sc_mode.setEnabled(col is not None)
            self.sc_mode.setCurrentIndex(max(self.sc_mode.findData(sc.mode if sc else ""), 0))
            if sc is not None:
                self.sc_cmap.setCurrentIndex(max(self.sc_cmap.findData(sc.colormap), 0))
                self.sc_auto_min.setChecked(sc.vmin is None)
                self.sc_auto_max.setChecked(sc.vmax is None)
                if sc.vmin is not None:
                    self.sc_min.setValue(sc.vmin)
                if sc.vmax is not None:
                    self.sc_max.setValue(sc.vmax)
                self.sc_cutoffs.setText("; ".join(f"{c:g}" for c in sc.cutoffs))
            else:
                self.sc_cutoffs.setText("")
            self._sync_scale_widgets(sc)
        finally:
            self._filling = False

    def _sync_scale_widgets(self, sc: ColumnScale | None) -> None:
        from jabuti.models.annotations import bin_colors, bin_labels

        self.sc_gradient.setVisible(sc is not None and sc.mode == "gradient")
        self.sc_bins.setVisible(sc is not None and sc.mode == "bins")
        if sc is None:
            return
        self.sc_strip.colors = COLORMAPS.get(sc.colormap, COLORMAPS["viridis"])
        self.sc_strip.update()
        if sc.mode != "bins":
            return
        while self.sc_bin_layout.count():
            wdg = self.sc_bin_layout.takeAt(0).widget()
            if wdg is not None:
                wdg.hide()
                wdg.setParent(None)
                wdg.deleteLater()
        integers = all(c == int(c) for c in sc.cutoffs)
        labels = bin_labels(sc.cutoffs, integers)
        colors = bin_colors(sc, len(labels))
        sc.colors = colors
        for i, (lab, color) in enumerate(zip(labels, colors)):
            btn = ColorButton(color, self.palette)
            btn.setToolTip(lab)
            btn.color_changed.connect(lambda c, k=i: self._bin_color_changed(k, c))
            self.sc_bin_layout.addWidget(btn)
        self.sc_bin_layout.addStretch(1)
        self.sc_bin_labels.setText("  ".join(labels))

    def _bin_color_changed(self, index: int, color: str) -> None:
        sc = self.scale_for(self.sc_column.currentData())
        if sc is not None and index < len(sc.colors):
            sc.colors[index] = color
            self._emit()

    def _scale_edited(self, *_a) -> None:  # type: ignore[no-untyped-def]
        if self._filling:
            return
        col = self.sc_column.currentData()
        if col is None:
            return
        mode = self.sc_mode.currentData()
        sc = self.scale_for(col)
        if not mode:
            if sc is not None:
                self.scales.remove(sc)
            self._sync_scale_widgets(None)
            self._mark_scale_column(col, False)
            self._emit()
            return
        if sc is None:
            sc = ColumnScale(column=col)
            self.scales.append(sc)
            self._mark_scale_column(col, True)
        sc.mode = mode
        sc.colormap = self.sc_cmap.currentData()
        sc.vmin = None if self.sc_auto_min.isChecked() else self.sc_min.value()
        sc.vmax = None if self.sc_auto_max.isChecked() else self.sc_max.value()
        try:
            cuts = sorted(set(parse_refs(self.sc_cutoffs.text())))
            if cuts != sc.cutoffs:
                sc.cutoffs = cuts
                sc.colors = []          # recalcula as cores das faixas
            self.scale_hint.setText("" if cuts or mode != "bins" else "Defina os pontos de corte (ex.: 5; 50; 200).")
        except ValueError as exc:
            self.scale_hint.setText(f"⚠ {exc}")
        self._sync_scale_widgets(sc)
        self._emit()

    def _mark_scale_column(self, col: str, on: bool) -> None:
        idx = self.sc_column.findData(col)
        if idx >= 0:
            text = self.sc_column.itemText(idx).replace("  ✎", "")
            self.sc_column.setItemText(idx, text + ("  ✎" if on else ""))

    # ------------------------------------------------------------- estilo
    def apply_to(self, style: RenderStyle) -> RenderStyle:
        fig = style.figure
        fig.bars = [BarSpec(**vars(b)) for b in self.bars]
        for b in fig.bars:
            b.refs = list(b.refs)
        fig.stacked = [StackedSpec(**{**vars(x), "columns": list(x.columns), "colors": list(x.colors)})
                       for x in self.stacked]
        fig.matrices = [MatrixSpec(**{**vars(m), "features": list(m.features)}) for m in self.matrices]
        fig.scales = [ColumnScale(**{**vars(x), "cutoffs": list(x.cutoffs), "colors": list(x.colors)})
                      for x in self.scales if x.mode != "bins" or x.cutoffs]
        return style

    def load_style(self, style: RenderStyle) -> list[str]:
        warnings: list[str] = []
        fig = style.figure
        self.bars = [BarSpec(**vars(b)) for b in fig.bars]
        used: list[str] = []
        for b in self.bars:
            if not b.id or b.id in used:
                b.id = self._next_id("bar", used)
            used.append(b.id)
            if b.source != METADATA_SOURCE and b.source not in self.sources:
                warnings.append(f"Barras “{b.column}”: a tabela {b.source} não está carregada "
                                "(carregue-a no painel Figura).")
        self.refresh_bars(select=0)
        self.stacked = [StackedSpec(**{**vars(x), "columns": list(x.columns), "colors": list(x.colors)})
                        for x in fig.stacked]
        used = []
        for x in self.stacked:
            if not x.id or x.id in used:
                x.id = self._next_id("stk", used)
            used.append(x.id)
            if x.source != METADATA_SOURCE and x.source not in self.sources:
                warnings.append(f"Barras empilhadas “{x.name or '/'.join(x.columns)}”: a tabela {x.source} "
                                "não está carregada (carregue-a no painel Figura).")
        self.refresh_stacked(select=0)
        self.matrices = [MatrixSpec(**{**vars(m), "features": list(m.features)}) for m in fig.matrices]
        used = []
        for m in self.matrices:
            if not m.id or m.id in used:
                m.id = self._next_id("mtx", used)
            used.append(m.id)
            if m.source != METADATA_SOURCE and m.source not in self.sources:
                warnings.append(f"Matriz “{m.name or m.source}”: a tabela {m.source or '(nenhuma)'} "
                                "não está carregada (carregue-a no painel Figura).")
        self.refresh_matrices(select=0)
        self.scales = []
        for x in fig.scales:
            if x.column and self.scale_for(x.column) is None:
                self.scales.append(ColumnScale(**{**vars(x), "cutoffs": sorted(x.cutoffs), "colors": list(x.colors)}))
        self.refresh_scales()
        return warnings


class FigureDock(QWidget):
    """Painel + faixa para recolher/expandir (fica fixo na borda esquerda)."""

    collapsed_changed = Signal(bool)

    EXPANDED_WIDTH = 330

    def __init__(self, panel: FigurePanel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.panel = panel
        self.scroll = QScrollArea()
        self.scroll.setWidget(panel)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.toggle = QToolButton()
        self.toggle.setAutoRaise(True)
        self.toggle.clicked.connect(lambda: self.set_collapsed(not self.collapsed))
        self.title = QLabel("<b>Figura</b>")
        self.vlabel = VerticalLabel("Figura")
        head = QHBoxLayout()
        head.setContentsMargins(6, 2, 2, 0)
        head.addWidget(self.title, 1)
        head.addWidget(self.toggle)
        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.addLayout(head)
        side.addWidget(self.vlabel, 0, Qt.AlignmentFlag.AlignHCenter)
        side.addWidget(self.scroll, 1)
        self.setLayout(side)
        self.collapsed = False
        self.set_collapsed(False)

    def set_collapsed(self, on: bool) -> None:
        self.collapsed = on
        self.scroll.setVisible(not on)
        self.title.setVisible(not on)
        self.vlabel.setVisible(on)
        self.toggle.setText("»" if on else "«")
        self.toggle.setToolTip("Expandir o painel Figura" if on else "Recolher o painel Figura")
        if on:
            self.setFixedWidth(30)
        else:
            self.setMinimumWidth(self.EXPANDED_WIDTH)
            self.setMaximumWidth(16777215)
        self.collapsed_changed.emit(on)
