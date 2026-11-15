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

from jabuti.views.theme import muted_css
from jabuti.settings import open_file
from jabuti.models.datatables import METADATA_SOURCE, DataSource, numeric_column
from jabuti.models.document import TreeEdits
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
    SupportLevels,
    RenderStyle,
    StackedSpec,
)
from jabuti.views.widgets.swatches import SwatchStrip
from jabuti.views.errors import show_error
from jabuti.views.itol_panel import ItolPanel
from jabuti.views.widgets.collapsible import CollapsibleSection
from jabuti.views.widgets.leaf_mapping import LeafMappingTable, MappingRow
from jabuti.views.widgets.swatches import ColorButton
from jabuti.workers import FileLoader

TABLE_FILTER = "Tabelas (*.tsv *.tab *.csv *.txt);;Todos (*)"
NOT_FOR_UNROOTED = "Não se aplica à árvore não enraizada (não há um lado “de fora” para as colunas)."


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(muted_css())
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
    root_group_requested = Signal()
    hidden_changed = Signal()
    clade_from_list_requested = Signal(list, str, str)   # nomes, nome do clado, cor

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.leaves: list[str] = []
        self.sources: dict[str, DataSource] = {}
        self.bars: list[BarSpec] = []
        self.stacked: list[StackedSpec] = []
        self.matrices: list[MatrixSpec] = []
        self.scales: list[ColumnScale] = []
        self.track_order: list[str] = []
        self.hidden_tracks: list[str] = []
        self.edits = TreeEdits()                    # compartilhado com o painel Estilo
        self.selection: list[str] = []
        self.break_legend_text = "outgroup branch not to scale"
        self.name_map: dict[str, str] = {}          # tabela de nomes (dados: fora do preset)
        self.name_map_file = ""
        self._load_kind = "data"
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
        self.itol = ItolPanel()
        self.itol.changed.connect(self._emit)
        self.itol.status_message.connect(self.status_message)
        self._add_section(lay, "itol", "Anotações iTOL", self.itol, False)
        self._add_section(lay, "pruning", "Enraizamento e poda", self._build_pruning(), False)
        self._add_section(lay, "names", "Nomes e destaques", self._build_names(), False)
        self._add_section(lay, "support", "Suporte e resumo", self._build_support(), False)
        lay.addStretch(1)
        for cb in self.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(8)
        self.set_selection([])

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
        self.bar_log = QCheckBox("Escala logarítmica")
        self.bar_log.setToolTip("Eixo em log10, útil quando os valores variam em ordens de grandeza. "
                                "Valores ≤ 0 não têm logaritmo: ficam sem barra (marcados como sem dado).")
        self.bar_log.toggled.connect(self._bar_edited)
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
        f.addRow(self.bar_log)
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
        v.addWidget(self._build_order())
        self.layout_hint = _hint("")
        self.layout_hint.setVisible(False)
        v.addWidget(self.layout_hint)
        self.refresh_tables()
        self.refresh_bars()
        self.refresh_stacked()
        self.refresh_matrices()
        self.refresh_scales()
        return w

    # ------------------------------------------------------ enraizar e podar
    def _build_pruning(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 0, 0, 6)
        self.sel_label = QLabel("Nenhuma folha selecionada (Cmd/Shift+clique nos nomes ou busca).")
        self.sel_label.setWordWrap(True)
        v.addWidget(self.sel_label)
        self.root_group_btn = QPushButton("Enraizar no grupo selecionado")
        self.root_group_btn.setToolTip("Raiz no ancestral comum das folhas selecionadas; avisa se entrarem "
                                       "folhas extras (grupo não monofilético)")
        self.root_group_btn.clicked.connect(self.root_group_requested.emit)
        v.addWidget(self.root_group_btn)

        v.addWidget(QLabel("<b>Folhas ocultas</b>"))
        v.addWidget(_hint("Some do desenho e das colunas; os ramos são juntados. O arquivo não muda."))
        self.hide_btn = QPushButton("Ocultar folhas selecionadas")
        self.hide_btn.clicked.connect(self.hide_selected)
        v.addWidget(self.hide_btn)
        self.hidden_list = QListWidget()
        self.hidden_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.hidden_list.setMaximumHeight(110)
        v.addWidget(self.hidden_list)
        row = QHBoxLayout()
        self.restore_btn = QPushButton("Restaurar selecionadas")
        self.restore_btn.clicked.connect(self.restore_selected)
        self.restore_all_btn = QPushButton("Restaurar todas")
        self.restore_all_btn.clicked.connect(self.restore_all)
        row.addWidget(self.restore_btn)
        row.addWidget(self.restore_all_btn)
        v.addLayout(row)

        v.addWidget(QLabel("<b>Ramos encurtados</b>"))
        v.addWidget(_hint("Clique direito numa folha ou nó → “Encurtar este ramo”. O ramo ganha a marca “//”."))
        self.short_list = QListWidget()
        self.short_list.setMaximumHeight(80)
        self.short_list.currentRowChanged.connect(self._short_selected)
        v.addWidget(self.short_list)
        srow = QHBoxLayout()
        self.short_len = self._spin(0.0, 1e6, 0.1, 0.01)
        self.short_len.setDecimals(4)
        self.short_len.setToolTip("Comprimento exibido (unidades da árvore)")
        self.short_len.valueChanged.connect(self._short_edited)
        self.short_rm = QPushButton("Remover")
        self.short_rm.clicked.connect(self._short_removed)
        srow.addWidget(QLabel("Comprimento:"))
        srow.addWidget(self.short_len, 1)
        srow.addWidget(self.short_rm)
        self.short_row = QWidget()
        self.short_row.setLayout(srow)
        v.addWidget(self.short_row)
        self.break_legend = QCheckBox("Nota na legenda:")
        self.break_legend.toggled.connect(self._emit)
        self.break_text = QLineEdit(self.break_legend_text)
        self.break_text.editingFinished.connect(self._emit)
        brow = QHBoxLayout()
        brow.addWidget(self.break_legend)
        brow.addWidget(self.break_text, 1)
        v.addLayout(brow)
        self.prune_hint = _hint("")
        v.addWidget(self.prune_hint)
        self.set_selection([])
        self.refresh_pruning()
        return w

    def set_selection(self, names: list[str]) -> None:
        self.selection = list(names)
        n = len(names)
        self.sel_label.setText(f"{n} folha(s) selecionada(s)." if n else
                               "Nenhuma folha selecionada (Cmd/Shift+clique nos nomes ou busca).")
        self.root_group_btn.setEnabled(n > 0)
        self.hide_btn.setEnabled(n > 0)
        if hasattr(self, "hl_add_btn"):
            for b in (self.hl_add_btn, self.mark_btn, self.unmark_btn):
                b.setEnabled(n > 0)

    def hide_leaves(self, names) -> bool:  # type: ignore[no-untyped-def]
        names = set(names) & set(self.leaves)
        visible = set(self.leaves) - self.edits.hidden
        if len(visible - names) < 2:
            self.prune_hint.setText("⚠ Pelo menos 2 folhas precisam continuar visíveis.")
            self.status_message.emit("Pelo menos 2 folhas precisam continuar visíveis.")
            return False
        self.edits.hide(names)
        self.prune_hint.setText("")
        self.refresh_pruning()
        self.hidden_changed.emit()
        self.changed.emit()
        self.status_message.emit(f"{len(names)} folha(s) oculta(s). Restaure no painel Figura → Enraizamento e poda.")
        return True

    def hide_selected(self) -> None:
        self.hide_leaves(self.selection)

    def restore_selected(self) -> None:
        names = [i.text() for i in self.hidden_list.selectedItems()]
        if names:
            self.edits.restore(names)
            self.refresh_pruning()
            self.hidden_changed.emit()
            self.changed.emit()

    def restore_all(self) -> None:
        if self.edits.hidden:
            self.edits.restore()
            self.refresh_pruning()
            self.hidden_changed.emit()
            self.changed.emit()

    def refresh_pruning(self) -> None:
        self.hidden_list.clear()
        for name in sorted(self.edits.hidden, key=str.lower):
            item = QListWidgetItem(name)
            if self.leaves and name not in self.leaves:
                item.setToolTip("Não existe na árvore aberta")
            self.hidden_list.addItem(item)
        has = bool(self.edits.hidden)
        self.hidden_list.setVisible(has)
        self.restore_btn.setEnabled(has)
        self.restore_all_btn.setEnabled(has)
        row = self.short_list.currentRow()
        self.short_list.blockSignals(True)
        self.short_list.clear()
        for b in self.edits.shortened:
            names = sorted(b.leaves)
            label = names[0] if len(names) == 1 else f"{names[0]} + {len(names) - 1}"
            self.short_list.addItem(f"{label}  (≤ {b.max_length:g})")
        self.short_list.blockSignals(False)
        self.short_list.setVisible(bool(self.edits.shortened))
        if self.edits.shortened:
            self.short_list.setCurrentRow(max(0, min(row, len(self.edits.shortened) - 1)))
        self._short_selected(self.short_list.currentRow())

    def _short_selected(self, row: int) -> None:
        ok = 0 <= row < len(self.edits.shortened)
        self.short_row.setVisible(ok)
        if ok:
            was = self.short_len.blockSignals(True)
            self.short_len.setValue(self.edits.shortened[row].max_length)
            self.short_len.blockSignals(was)

    def _short_edited(self, value: float) -> None:
        row = self.short_list.currentRow()
        if 0 <= row < len(self.edits.shortened):
            self.edits.shortened[row].max_length = value
            item = self.short_list.item(row)
            item.setText(item.text().split("  (≤")[0] + f"  (≤ {value:g})")
            self.changed.emit()

    def _short_removed(self) -> None:
        row = self.short_list.currentRow()
        if 0 <= row < len(self.edits.shortened):
            del self.edits.shortened[row]
            self.refresh_pruning()
            self.changed.emit()

    # ----------------------------------------------------- nomes e destaques
    def _build_names(self) -> QWidget:
        from PySide6.QtWidgets import QPlainTextEdit, QTableWidget

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 0, 0, 6)
        v.addWidget(QLabel("<b>Nomes de exibição</b>"))
        v.addWidget(_hint("Só mudam o texto desenhado: buscas, mapeamentos e presets usam o nome original."))
        row = QHBoxLayout()
        self.names_load_btn = QPushButton("Tabela de nomes…")
        self.names_load_btn.setToolTip("CSV/TSV com cabeçalho e 2 colunas: nome original, nome exibido")
        self.names_load_btn.clicked.connect(self._choose_name_table)
        self.names_clear_btn = QPushButton("Remover")
        self.names_clear_btn.clicked.connect(self.clear_name_table)
        row.addWidget(self.names_load_btn, 1)
        row.addWidget(self.names_clear_btn)
        v.addLayout(row)
        self.names_report = QLabel("")
        self.names_report.setWordWrap(True)
        v.addWidget(self.names_report)
        self.opt_underscores = QCheckBox("Trocar “_” por espaço")
        self.opt_abbrev = QCheckBox("Abreviar gênero (Cupriavidus → C.)")
        for cb in (self.opt_underscores, self.opt_abbrev):
            cb.toggled.connect(self._emit)
            v.addWidget(cb)
        v.addWidget(QLabel("Substituições (regex, aplicadas em ordem):"))
        self.rules_table = QTableWidget(0, 2)
        self.rules_table.setHorizontalHeaderLabels(["Procurar", "Trocar por"])
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        self.rules_table.verticalHeader().setVisible(False)
        self.rules_table.setMaximumHeight(100)
        self.rules_table.itemChanged.connect(self._rules_edited)
        v.addWidget(self.rules_table)
        rrow = QHBoxLayout()
        add_rule = QPushButton("+ regra")
        add_rule.clicked.connect(self.add_rule)
        rm_rule = QPushButton("− regra")
        rm_rule.clicked.connect(self.remove_rule)
        rrow.addWidget(add_rule)
        rrow.addWidget(rm_rule)
        rrow.addStretch(1)
        v.addLayout(rrow)
        self.rules_hint = _hint("Ex.: procurar “_LMG(\\d+)” e trocar por “ LMG \\1”. Roda depois do “_” → espaço.")
        v.addWidget(self.rules_hint)
        mrow = QHBoxLayout()
        self.mark_btn = QPushButton("Marcar seleção")
        self.mark_btn.setToolTip("Acrescenta o prefixo/símbolo ao nome das folhas selecionadas")
        self.mark_btn.clicked.connect(lambda: self.mark_selected(True))
        self.unmark_btn = QPushButton("Desmarcar")
        self.unmark_btn.clicked.connect(lambda: self.mark_selected(False))
        self.mark_prefix = QLineEdit("★ ")
        self.mark_prefix.setMaximumWidth(50)
        self.mark_prefix.setToolTip("Prefixo ou símbolo das folhas marcadas")
        self.mark_prefix.editingFinished.connect(self._emit)
        mrow.addWidget(self.mark_btn, 1)
        mrow.addWidget(self.unmark_btn)
        mrow.addWidget(self.mark_prefix)
        v.addLayout(mrow)
        self.mark_label = _hint("")
        v.addWidget(self.mark_label)

        v.addWidget(QLabel("<b>Destaque de linha inteira</b>"))
        v.addWidget(_hint("Faixa translúcida atrás do rótulo e de todas as colunas/anéis das folhas selecionadas."))
        self.hl_add_btn = QPushButton("Destacar linhas da seleção")
        self.hl_add_btn.clicked.connect(self.highlight_selected)
        v.addWidget(self.hl_add_btn)
        self.hl_list = QListWidget()
        self.hl_list.setMaximumHeight(70)
        self.hl_list.currentRowChanged.connect(self._hl_selected)
        v.addWidget(self.hl_list)
        ed = QWidget()
        f = QFormLayout(ed)
        f.setContentsMargins(0, 0, 0, 0)
        self.hl_color = ColorButton("#ffe066", ["#ffe066", "#a5d8ff", "#b7e4a3", "#ffc9c9", "#e5dbff"])
        self.hl_color.color_changed.connect(self._hl_edited)
        self.hl_alpha = self._spin(5, 100, 35, 5, " %")
        self.hl_alpha.valueChanged.connect(self._hl_edited)
        crow = QHBoxLayout()
        crow.addWidget(self.hl_color)
        crow.addWidget(QLabel("opacidade"))
        crow.addWidget(self.hl_alpha, 1)
        self.hl_outline_on = QCheckBox("contorno")
        self.hl_outline_on.setChecked(True)
        self.hl_outline_on.toggled.connect(self._hl_edited)
        self.hl_outline = ColorButton("#e0a800", ["#e0a800", "#1971c2", "#2f9e44", "#c92a2a", "#202020"])
        self.hl_outline.color_changed.connect(self._hl_edited)
        self.hl_outline_w = self._spin(0.2, 6, 1.0, 0.2, " px")
        self.hl_outline_w.valueChanged.connect(self._hl_edited)
        orow = QHBoxLayout()
        orow.addWidget(self.hl_outline_on)
        orow.addWidget(self.hl_outline)
        orow.addWidget(self.hl_outline_w, 1)
        self.hl_thick = self._spin(20, 100, 100, 5, " %")
        self.hl_thick.setToolTip("Espessura da faixa em relação à altura da linha")
        self.hl_thick.valueChanged.connect(self._hl_edited)
        self.hl_rm = QPushButton("Remover destaque")
        self.hl_rm.clicked.connect(self.remove_highlight)
        f.addRow("Cor:", crow)
        f.addRow(orow)
        f.addRow("Espessura:", self.hl_thick)
        f.addRow(self.hl_rm)
        self.hl_editor = ed
        v.addWidget(ed)

        v.addWidget(QLabel("<b>Clado a partir de lista</b>"))
        self.list_edit = QPlainTextEdit()
        self.list_edit.setPlaceholderText("Um nome por linha (nome da folha ou do genoma)")
        self.list_edit.setMaximumHeight(90)
        v.addWidget(self.list_edit)
        lrow = QHBoxLayout()
        self.list_file_btn = QPushButton("Carregar arquivo…")
        self.list_file_btn.clicked.connect(self._choose_list_file)
        self.list_name = QLineEdit()
        self.list_name.setPlaceholderText("nome do clado")
        self.list_color = ColorButton("#e15759", self.palette)
        lrow.addWidget(self.list_file_btn)
        lrow.addWidget(self.list_name, 1)
        lrow.addWidget(self.list_color)
        v.addLayout(lrow)
        self.list_create = QPushButton("Criar clado")
        self.list_create.clicked.connect(self._create_clade_from_list)
        v.addWidget(self.list_create)
        self.list_report = _hint("")
        v.addWidget(self.list_report)
        self.refresh_names()
        return w

    # nomes
    def _choose_name_table(self) -> None:
        path = open_file(self, "Tabela de nomes", "table", TABLE_FILTER)
        if path:
            self.load_name_table(path, wait=False)

    def _names_loaded(self, path: Path, table) -> None:  # type: ignore[no-untyped-def]
        from jabuti.models.display_names import parse_name_table

        mapping, warns = parse_name_table(table)
        self.name_map = mapping
        self.name_map_file = path.name
        self._last_ok = True
        self.refresh_names()
        if warns:
            self.names_report.setText(self.names_report.text() + "<br>⚠ " + "<br>⚠ ".join(warns[:3]))
        self._emit()

    def clear_name_table(self) -> None:
        if self.name_map:
            self.name_map, self.name_map_file = {}, ""
            self.refresh_names()
            self._emit()

    def refresh_names(self) -> None:
        if self.name_map:
            unknown = [k for k in self.name_map if self.leaves and k not in self.leaves]
            used = len(self.name_map) - len(unknown)
            text = f"<b>{self.name_map_file}</b>: {len(self.name_map)} nomes · {used} folhas renomeadas."
            if unknown:
                more = "…" if len(unknown) > 5 else ""
                text += f"<br>⚠ Não estão na árvore ({len(unknown)}): {', '.join(unknown[:5])}{more}"
            self.names_report.setText(text)
            self.names_report.setToolTip("\n".join(unknown))
        else:
            self.names_report.setText("Sem tabela de nomes.")
        self.names_clear_btn.setEnabled(bool(self.name_map))
        n = len(self.edits.marked & set(self.leaves)) if self.leaves else len(self.edits.marked)
        self.mark_label.setText(f"{n} folha(s) marcada(s)." if n else "")
        self._refresh_highlights()

    def add_rule(self, pattern: str = "", replacement: str = "") -> None:
        from PySide6.QtWidgets import QTableWidgetItem

        r = self.rules_table.rowCount()
        self.rules_table.blockSignals(True)
        self.rules_table.insertRow(r)
        self.rules_table.setItem(r, 0, QTableWidgetItem(pattern or ""))
        self.rules_table.setItem(r, 1, QTableWidgetItem(replacement or ""))
        self.rules_table.blockSignals(False)
        if pattern:
            self._rules_edited()

    def remove_rule(self) -> None:
        r = self.rules_table.currentRow()
        if r < 0:
            r = self.rules_table.rowCount() - 1
        if r >= 0:
            self.rules_table.removeRow(r)
            self._rules_edited()

    def rules(self) -> tuple[list[str], list[str]]:
        pats, reps = [], []
        for r in range(self.rules_table.rowCount()):
            a, b = self.rules_table.item(r, 0), self.rules_table.item(r, 1)
            pat = a.text() if a else ""
            if pat:
                pats.append(pat)
                reps.append(b.text() if b else "")
        return pats, reps

    def _rules_edited(self, *_a) -> None:  # type: ignore[no-untyped-def]
        from jabuti.models.display_names import compile_rules

        pats, reps = self.rules()
        _ok, errors = compile_rules(pats, reps)
        self.rules_hint.setText("⚠ " + "<br>⚠ ".join(errors) if errors else
                                "Ex.: procurar “_LMG(\\d+)” e trocar por “ LMG \\1”. Roda depois do “_” → espaço.")
        self._emit()

    def mark_selected(self, on: bool) -> None:
        if not self.selection:
            self.status_message.emit("Selecione folhas (Cmd/Shift+clique ou busca) para marcar.")
            return
        if on:
            self.edits.marked |= set(self.selection)
        else:
            self.edits.marked -= set(self.selection)
        self.refresh_names()
        self.changed.emit()

    # destaques
    def highlight_selected(self) -> None:
        from jabuti.models.document import RowHighlight

        if not self.selection:
            self.status_message.emit("Selecione folhas (Cmd/Shift+clique ou busca) para destacar as linhas.")
            return
        self.edits.highlights.append(RowHighlight(frozenset(self.selection)))
        self._refresh_highlights(select=len(self.edits.highlights) - 1)
        self.changed.emit()

    def remove_highlight(self) -> None:
        row = self.hl_list.currentRow()
        if 0 <= row < len(self.edits.highlights):
            del self.edits.highlights[row]
            self._refresh_highlights(select=row - 1)
            self.changed.emit()

    def _refresh_highlights(self, select: int | None = None) -> None:
        row = self.hl_list.currentRow() if select is None else select
        self.hl_list.blockSignals(True)
        self.hl_list.clear()
        for hl in self.edits.highlights:
            names = sorted(hl.leaves)
            self.hl_list.addItem(names[0] if len(names) == 1 else f"{names[0]} + {len(names) - 1}")
        self.hl_list.blockSignals(False)
        has = bool(self.edits.highlights)
        self.hl_list.setVisible(has)
        if has:
            self.hl_list.setCurrentRow(max(0, min(row, len(self.edits.highlights) - 1)))
        self._hl_selected(self.hl_list.currentRow())

    def _hl_selected(self, row: int) -> None:
        ok = 0 <= row < len(self.edits.highlights)
        self.hl_editor.setVisible(ok)
        if not ok:
            return
        hl = self.edits.highlights[row]
        self._filling = True
        try:
            self.hl_color.set_color(hl.color)
            self.hl_alpha.setValue(round(hl.alpha * 100))
            self.hl_outline_on.setChecked(hl.outline is not None)
            if hl.outline:
                self.hl_outline.set_color(hl.outline)
            self.hl_outline_w.setValue(hl.outline_width)
            self.hl_thick.setValue(round(hl.thickness * 100))
        finally:
            self._filling = False

    def _hl_edited(self, *_a) -> None:  # type: ignore[no-untyped-def]
        row = self.hl_list.currentRow()
        if self._filling or not 0 <= row < len(self.edits.highlights):
            return
        hl = self.edits.highlights[row]
        hl.color = self.hl_color.color()
        hl.alpha = self.hl_alpha.value() / 100
        hl.outline = self.hl_outline.color() if self.hl_outline_on.isChecked() else None
        hl.outline_width = self.hl_outline_w.value()
        hl.thickness = self.hl_thick.value() / 100
        self.changed.emit()

    # clado por lista
    def _choose_list_file(self) -> None:
        from jabuti.parsers.errors import JabutiParseError, read_text

        path = open_file(self, "Lista de nomes", "table", "Texto (*.txt *.tsv *.csv *.list);;Todos (*)")
        if not path:
            return
        try:
            text = read_text(Path(path), JabutiParseError)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Erro ao ler a lista")
            return
        self.list_edit.setPlainText(text)
        if not self.list_name.text():
            self.list_name.setText(Path(path).stem)

    def list_names(self) -> list[str]:
        """Um nome por linha (só a 1ª coluna, se o arquivo tiver TAB, vírgula ou ponto e vírgula)."""
        import re as _re

        out = []
        for line in self.list_edit.toPlainText().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            out.append(_re.split(r"[\t,;]", line)[0].strip())
        return [n for n in out if n]

    def _create_clade_from_list(self) -> None:
        names = self.list_names()
        if not names:
            self.list_report.setText("Cole os nomes (um por linha) ou carregue um arquivo.")
            return
        self.clade_from_list_requested.emit(names, self.list_name.text().strip(), self.list_color.color())

    # ------------------------------------------------------- suporte e resumo
    def _build_support(self) -> QWidget:
        from PySide6.QtWidgets import QPlainTextEdit

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 0, 0, 6)
        self.lv_enabled = QCheckBox("Suporte em níveis (círculos nos nós)")
        self.lv_enabled.toggled.connect(self._levels_edited)
        v.addWidget(self.lv_enabled)
        f = QFormLayout()
        f.setContentsMargins(0, 0, 0, 0)
        self.lv_index = QComboBox()
        for text, idx in (("Último valor (UFBoot no IQ-TREE)", -1), ("1º valor (SH-aLRT)", 0), ("2º valor (UFBoot)", 1)):
            self.lv_index.addItem(text, idx)
        self.lv_index.currentIndexChanged.connect(self._levels_edited)
        self.lv_cutoffs = QLineEdit("95; 70")
        self.lv_cutoffs.setToolTip("Pontos de corte decrescentes: ≥95, 70–94, <70")
        self.lv_cutoffs.editingFinished.connect(self._levels_edited)
        self.lv_colors_box = QWidget()
        self.lv_colors_layout = QHBoxLayout(self.lv_colors_box)
        self.lv_colors_layout.setContentsMargins(0, 0, 0, 0)
        self.lv_colors_layout.setSpacing(3)
        self.lv_size = self._spin(2, 30, 6, 0.5, " px")
        self.lv_size.valueChanged.connect(self._levels_edited)
        self.lv_legend = QCheckBox("Níveis na legenda")
        self.lv_legend.setChecked(True)
        self.lv_legend.toggled.connect(self._levels_edited)
        f.addRow("Valor:", self.lv_index)
        f.addRow("Cortes:", self.lv_cutoffs)
        f.addRow("Cores:", self.lv_colors_box)
        f.addRow("Tamanho:", self.lv_size)
        f.addRow(self.lv_legend)
        self.lv_box = QWidget()
        self.lv_box.setLayout(f)
        v.addWidget(self.lv_box)
        self.lv_hint = _hint("")
        v.addWidget(self.lv_hint)
        self.levels = SupportLevels()
        self._levels_colors()

        v.addWidget(QLabel("<b>Resumo da árvore</b>"))
        self.summary_text = QPlainTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMaximumHeight(130)
        self.summary_text.setPlaceholderText("Abra uma árvore.")
        v.addWidget(self.summary_text)
        copy = QPushButton("Copiar resumo")
        copy.clicked.connect(self.copy_summary)
        v.addWidget(copy)
        v.addWidget(_hint("Contado na árvore desenhada (sem as folhas ocultas). Com dois valores "
                          "(SH-aLRT/UFBoot), segue a convenção do IQ-TREE."))
        return w

    def _levels_colors(self) -> None:
        from jabuti.models.support import level_labels

        while self.lv_colors_layout.count():
            wdg = self.lv_colors_layout.takeAt(0).widget()
            if wdg is not None:
                wdg.hide()
                wdg.setParent(None)
                wdg.deleteLater()
        labels = level_labels(self.levels.cutoffs)
        defaults = ["#2f9e44", "#f2c94c", "#e03131", "#868e96", "#1971c2"]
        while len(self.levels.colors) < len(labels):
            self.levels.colors.append(defaults[len(self.levels.colors) % len(defaults)])
        self.levels.colors = self.levels.colors[:len(labels)]
        for i, (lab, color) in enumerate(zip(labels, self.levels.colors)):
            btn = ColorButton(color, ["#2f9e44", "#f2c94c", "#e03131", "#1971c2", "#868e96", "#202020"])
            btn.setToolTip(lab)
            btn.color_changed.connect(lambda c, k=i: self._level_color(k, c))
            self.lv_colors_layout.addWidget(btn)
        self.lv_colors_layout.addStretch(1)
        self.lv_box.setEnabled(self.levels.enabled)

    def _level_color(self, k: int, color: str) -> None:
        self.levels.colors[k] = color
        self._emit()

    def _levels_edited(self, *_a) -> None:  # type: ignore[no-untyped-def]
        if self._filling:
            return
        lv = self.levels
        lv.enabled = self.lv_enabled.isChecked()
        lv.index = self.lv_index.currentData()
        lv.size = self.lv_size.value()
        lv.legend = self.lv_legend.isChecked()
        try:
            cuts = sorted(set(parse_refs(self.lv_cutoffs.text())), reverse=True)
            if not cuts:
                raise ValueError("Defina pelo menos um ponto de corte (ex.: 95; 70).")
            if cuts != lv.cutoffs:
                lv.cutoffs = cuts
                self._levels_colors()
            self.lv_hint.setText("")
        except ValueError as exc:
            self.lv_hint.setText(f"⚠ {exc}")
        self.lv_box.setEnabled(lv.enabled)
        self._emit()

    def set_summary(self, text: str) -> None:
        self.summary_text.setPlainText(text)

    def copy_summary(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.summary_text.toPlainText())
        self.status_message.emit("Resumo da árvore copiado.")

    def _build_order(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        v.addWidget(QLabel("<b>Ordem das colunas</b>"))
        v.addWidget(_hint("Da árvore para fora (anéis: de dentro para fora). Arraste para reordenar; "
                          "desmarque para ocultar. Colunas novas entram no fim."))
        self.order_list = QListWidget()
        self.order_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.order_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.order_list.setMaximumHeight(150)
        self.order_list.itemChanged.connect(self._order_changed)
        self.order_list.model().rowsMoved.connect(self._order_changed)
        v.addWidget(self.order_list)
        row = QHBoxLayout()
        up = QPushButton("↑")
        dn = QPushButton("↓")
        up.setToolTip("Mover para perto da árvore")
        dn.setToolTip("Mover para fora")
        up.clicked.connect(lambda: self.move_track(-1))
        dn.clicked.connect(lambda: self.move_track(1))
        row.addWidget(up)
        row.addWidget(dn)
        row.addStretch(1)
        v.addLayout(row)
        self.order_hint = _hint("Nenhuma coluna ativa.")
        v.addWidget(self.order_hint)
        self.order_list.setVisible(False)
        return w

    def set_available_tracks(self, items: list[tuple[str, str]]) -> None:
        """Trilhas existentes (na ordem atual) — chamado pela janela a cada desenho."""
        current = [(self.order_list.item(i).data(Qt.ItemDataRole.UserRole), self.order_list.item(i).text())
                   for i in range(self.order_list.count())]
        if current == list(items) and all(
                (self.order_list.item(i).checkState() == Qt.CheckState.Unchecked) == (k in self.hidden_tracks)
                for i, (k, _t) in enumerate(items)):
            return
        was = self._filling
        self._filling = True
        self.order_list.blockSignals(True)
        try:
            self.order_list.clear()
            for key, label in items:
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, key)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
                item.setCheckState(Qt.CheckState.Unchecked if key in self.hidden_tracks else Qt.CheckState.Checked)
                self.order_list.addItem(item)
        finally:
            self.order_list.blockSignals(False)
            self._filling = was
        self.order_list.setVisible(bool(items))
        self.order_hint.setVisible(not items)

    def track_keys(self) -> list[str]:
        return [self.order_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.order_list.count())]

    def move_track(self, delta: int) -> None:
        row = self.order_list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.order_list.count():
            return
        self.order_list.blockSignals(True)
        item = self.order_list.takeItem(row)
        self.order_list.insertItem(new, item)
        self.order_list.setCurrentRow(new)
        self.order_list.blockSignals(False)
        self._order_changed()

    def _order_changed(self, *_a) -> None:  # type: ignore[no-untyped-def]
        if self._filling:
            return
        keys = self.track_keys()
        # chaves de trilhas que não existem agora (ex.: tabela ainda não carregada) mantêm a posição relativa
        self.track_order = keys + [k for k in self.track_order if k not in keys]
        visible_hidden = {self.order_list.item(i).data(Qt.ItemDataRole.UserRole)
                          for i in range(self.order_list.count())
                          if self.order_list.item(i).checkState() == Qt.CheckState.Unchecked}
        self.hidden_tracks = sorted(visible_hidden | {k for k in self.hidden_tracks if k not in keys})
        self._emit()

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
        self.refresh_pruning()
        self.refresh_names()
        for src in self.sources.values():
            src.mapping.set_leaves(self.leaves)
        self._show_table()

    def set_palette(self, colors: list[str]) -> None:
        self.palette = list(colors)
        self.bar_color.palette_colors = self.palette
        self.list_color.palette_colors = self.palette
        self.st_color.palette_colors = self.palette
        self.itol.palette = self.palette

    def set_layout(self, kind: LayoutKind) -> None:
        """Desativa (com dica) o que não se aplica ao layout."""
        self.layout_kind = LayoutKind(kind)
        ok = self.layout_kind.value != "unrooted"
        for wdg in (self.add_bar_btn, self.bar_editor, self.bar_list,
                    self.add_stacked_btn, self.stacked_editor, self.stacked_list,
                    self.add_matrix_btn, self.matrix_editor, self.matrix_list, self.order_list):
            wdg.setEnabled(ok)
            wdg.setToolTip("" if ok else NOT_FOR_UNROOTED)
        self.layout_hint.setText("" if ok else NOT_FOR_UNROOTED)
        self.layout_hint.setVisible(not ok)

    # ------------------------------------------------------------ tabelas
    def _choose_table(self) -> None:
        path = open_file(self, "Carregar tabela de dados", "table", TABLE_FILTER)
        if path:
            self.load_table(path, wait=False)

    def is_loading(self) -> bool:
        return self._loading

    def load_name_table(self, path: str | Path, wait: bool = True) -> bool:
        """Tabela de nomes (original, exibido), lida numa thread como as outras tabelas."""
        return self.load_table(path, wait, kind="names")

    def load_table(self, path: str | Path, wait: bool = True, kind: str = "data") -> bool:
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
        self._load_kind = kind
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
            if self._load_kind == "names":
                self._names_loaded(p, result)
                continue
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
        if self._load_kind == "names":
            self.table_loaded.emit(self._last_ok)
            return
        if self._last_ok:
            self.refresh_tables(select=list(self.sources)[-1])
            self.tables_changed.emit()
            self._emit()
        else:
            self._show_table()
        self.table_loaded.emit(self._last_ok)

    def shutdown(self, timeout_ms: int = 5000) -> None:
        self.itol.shutdown(timeout_ms)
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
            self.bar_log.setChecked(spec.log)
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
        spec.log = self.bar_log.isChecked()
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
        if len(cols) > 8:
            cols = cols[:6]                         # tabela larga: começa com as 6 primeiras séries
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
        fig.track_order = list(self.track_order)
        fig.hidden_tracks = list(self.hidden_tracks)
        nr = fig.names
        nr.underscores = self.opt_underscores.isChecked()
        nr.abbreviate_genus = self.opt_abbrev.isChecked()
        nr.patterns, nr.replacements = self.rules()
        nr.mark_prefix = self.mark_prefix.text()
        lv = self.levels
        fig.support_levels = SupportLevels(lv.enabled, lv.index, list(lv.cutoffs), list(lv.colors), lv.size, lv.legend)
        fig.break_legend = self.break_legend.isChecked()
        fig.break_legend_text = self.break_text.text().strip() or "outgroup branch not to scale"
        fig.itol = self.itol.to_prefs()
        fig.branch_text = self.itol.branch_text()
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
        self.track_order = list(fig.track_order)
        self.hidden_tracks = list(fig.hidden_tracks)
        self.itol.load_prefs(list(fig.itol))
        self.itol.set_branch_text(fig.branch_text)
        nr = fig.names
        was = self._filling
        self._filling = True
        try:
            self.opt_underscores.setChecked(nr.underscores)
            self.opt_abbrev.setChecked(nr.abbreviate_genus)
            self.mark_prefix.setText(nr.mark_prefix)
            self.rules_table.setRowCount(0)
            for i, pat in enumerate(nr.patterns):
                self.add_rule(pat, nr.replacements[i] if i < len(nr.replacements) else "")
        finally:
            self._filling = was
        self.refresh_names()
        lv = fig.support_levels
        self.levels = SupportLevels(lv.enabled, lv.index, sorted(lv.cutoffs, reverse=True) or [95.0, 70.0],
                                    list(lv.colors), lv.size, lv.legend)
        was = self._filling
        self._filling = True
        try:
            self.lv_enabled.setChecked(lv.enabled)
            self.lv_index.setCurrentIndex(max(self.lv_index.findData(lv.index), 0))
            self.lv_cutoffs.setText("; ".join(f"{c:g}" for c in self.levels.cutoffs))
            self.lv_size.setValue(lv.size)
            self.lv_legend.setChecked(lv.legend)
        finally:
            self._filling = was
        self._levels_colors()
        self.break_legend.setChecked(fig.break_legend)
        self.break_text.setText(fig.break_legend_text)
        self.refresh_pruning()
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
