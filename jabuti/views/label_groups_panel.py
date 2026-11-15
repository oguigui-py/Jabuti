"""Grupos de rótulos no painel Estilo: padrão de texto, lista e editor do grupo."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from jabuti.views.theme import error_color, muted_css
from jabuti.models.label_groups import (
    HIGHLIGHT_COLORS,
    SOURCES,
    GroupSource,
    LabelGroup,
    LabelGroupSet,
    LabelLook,
    match_pattern,
)
from jabuti.views.clade_list import drop_cell_widgets
from jabuti.views.widgets.swatches import color_menu, swatch_css

COL_SRC, COL_NAME, COL_N, COL_TEXT, COL_BG, COL_VIS, COL_DEL = range(7)
TRI = [("Padrão", None), ("Sim", True), ("Não", False)]
NONE_CSS = ("QToolButton { background: qlineargradient(x1:0, y1:1, x2:1, y2:0, stop:0 #fff, stop:0.45 #fff,"
            " stop:0.5 #d33, stop:0.55 #fff, stop:1 #fff); border: 1px solid #999; border-radius: 3px; }")


def _swatch(color: str | None, tip: str, size: int = 18) -> QToolButton:
    b = QToolButton()
    b.setFixedSize(size, size)
    b.setToolTip(tip)
    b.setStyleSheet(swatch_css(color, False) if color else NONE_CSS)
    return b



class LabelGroupsPanel(QWidget):
    changed = Signal()
    select_leaves = Signal(list)       # "Selecionar" do padrão de texto
    status_message = Signal(str)

    def __init__(self, groups: LabelGroupSet, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.groups = groups
        self.leaf_names: list[str] = []
        self.selection: list[str] = []
        self._filling = False
        self._current: LabelGroup | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 0)

        # ---- padrão de texto
        pat = QGroupBox("Destacar por padrão de texto")
        pl = QVBoxLayout(pat)
        row = QHBoxLayout()
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText("ex.: xenovorans  ou  ^LB400")
        self.pattern.setClearButtonEnabled(True)
        self.regex = QCheckBox("regex")
        row.addWidget(self.pattern, 1)
        row.addWidget(self.regex)
        pl.addLayout(row)
        row2 = QHBoxLayout()
        self.pattern_count = QLabel("")
        self.pattern_count.setStyleSheet(muted_css())
        self.pattern_select = QPushButton("Selecionar")
        self.pattern_group = QPushButton("Criar grupo")
        row2.addWidget(self.pattern_count, 1)
        row2.addWidget(self.pattern_select)
        row2.addWidget(self.pattern_group)
        pl.addLayout(row2)
        v.addWidget(pat)
        self.pattern.textChanged.connect(self._update_pattern_count)
        self.regex.toggled.connect(self._update_pattern_count)
        self.pattern_select.clicked.connect(self._select_pattern)
        self.pattern_group.clicked.connect(self._group_from_pattern)
        self.pattern.returnPressed.connect(self._select_pattern)

        # ---- seleção
        sel = QHBoxLayout()
        self.selection_label = QLabel("Seleção: nenhuma folha")
        self.selection_label.setToolTip("Cmd/Ctrl+clique nos nomes, Shift+clique para intervalo, "
                                        "ou busque (Cmd+F)")
        self.selection_btn = QPushButton("Criar grupo da seleção")
        sel.addWidget(self.selection_label, 1)
        sel.addWidget(self.selection_btn)
        v.addLayout(sel)
        self.selection_btn.clicked.connect(lambda: self.create_group(self.selection, "selection"))

        # ---- lista
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Origem", "Nome", "Folhas", "Aa", "Fundo", "Ver", ""])
        self.table.horizontalHeaderItem(COL_N).setToolTip("Folhas do grupo; “valendo/total” quando um grupo "
                                                          "criado depois tomou algumas delas")
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for c in (COL_SRC, COL_N):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        for c, w in ((COL_TEXT, 26), (COL_BG, 40), (COL_VIS, 28), (COL_DEL, 22)):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(c, w)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setMinimumHeight(110)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        v.addWidget(self.table)

        bottom = QHBoxLayout()
        self.legend_cb = QCheckBox("Mostrar grupos na legenda")
        self.legend_cb.setChecked(groups.show_in_legend)
        self.legend_cb.toggled.connect(self._legend_toggled)
        self.clear_btn = QPushButton("Limpar tudo")
        self.clear_btn.clicked.connect(self.clear_all)
        bottom.addWidget(self.legend_cb, 1)
        bottom.addWidget(self.clear_btn)
        v.addLayout(bottom)

        # ---- editor do grupo selecionado
        self.editor = QGroupBox("Estilo do grupo")
        f = QFormLayout(self.editor)
        self.editor_name = QLabel("")
        self.editor_name.setStyleSheet("font-weight: bold;")
        f.addRow(self.editor_name)
        colors = QHBoxLayout()
        self.text_btn = _swatch(None, "Cor do texto")
        self.bg_btn = _swatch(None, "Cor do fundo (destaque)")
        self.text_btn.clicked.connect(lambda: self._pick("text_color", self.text_btn))
        self.bg_btn.clicked.connect(lambda: self._pick("background", self.bg_btn))
        colors.addWidget(QLabel("Texto"))
        colors.addWidget(self.text_btn)
        colors.addSpacing(10)
        colors.addWidget(QLabel("Fundo"))
        colors.addWidget(self.bg_btn)
        colors.addStretch(1)
        f.addRow(colors)
        self.alpha = QSpinBox()
        self.alpha.setRange(5, 100)
        self.alpha.setSingleStep(5)
        self.alpha.setSuffix(" %")
        f.addRow("Opacidade do fundo:", self.alpha)
        self.bold = QComboBox()
        self.italic = QComboBox()
        for cb in (self.bold, self.italic):
            for text, val in TRI:
                cb.addItem(text, val)
        f.addRow("Negrito:", self.bold)
        f.addRow("Itálico:", self.italic)
        self.size = QSpinBox()
        self.size.setRange(50, 200)
        self.size.setSingleStep(10)
        self.size.setSuffix(" %")
        f.addRow("Tamanho relativo:", self.size)
        self.padding = QDoubleSpinBox()
        self.padding.setRange(0, 12)
        self.padding.setSingleStep(0.5)
        self.radius = QDoubleSpinBox()
        self.radius.setRange(0, 12)
        self.radius.setSingleStep(0.5)
        f.addRow("Margem interna:", self.padding)
        f.addRow("Cantos:", self.radius)
        v.addWidget(self.editor)
        for w in (self.alpha, self.size):
            w.valueChanged.connect(self._editor_changed)
        for w in (self.padding, self.radius):
            w.valueChanged.connect(self._editor_changed)
        for w in (self.bold, self.italic):
            w.currentIndexChanged.connect(self._editor_changed)

        self.refresh()
        self.set_selection([])

    # ---------------------------------------------------------------- API
    def set_leaf_names(self, names: list[str]) -> None:
        self.leaf_names = list(names)
        self._update_pattern_count()
        self.refresh()

    def set_selection(self, names: list[str]) -> None:
        self.selection = list(names)
        n = len(self.selection)
        self.selection_label.setText("Seleção: nenhuma folha" if n == 0 else
                                     f"Seleção: {self.selection[0]}" if n == 1 else f"Seleção: {n} folhas")
        self.selection_btn.setEnabled(n > 0)

    def create_group(self, leaves, source: GroupSource, name: str | None = None,  # type: ignore[no-untyped-def]
                     look: LabelLook | None = None) -> LabelGroup | None:
        leaves = list(leaves)
        if not leaves:
            self.status_message.emit("Nenhuma folha para o grupo.")
            return None
        g = self.groups.add(leaves, source, name, look)
        self.refresh()
        self.select_group(g)
        self.status_message.emit(f"Grupo de rótulos “{g.name}” criado com {len(g.leaves)} folha(s). "
                                 "Ajuste o estilo na seção Rótulos.")
        self.changed.emit()
        return g

    def style_leaves(self, leaves, **look_changes) -> LabelGroup | None:  # type: ignore[no-untyped-def]
        """Estilo rápido (menu de contexto): atualiza o grupo com exatamente essas
        folhas, se existir; senão cria um grupo de seleção."""
        leaves = frozenset(leaves)
        g = next((x for x in reversed(self.groups.groups) if x.leaves == leaves), None)
        if g is None:
            look = LabelLook(**look_changes)
            return self.create_group(leaves, "selection", look=look)
        for k, val in look_changes.items():
            setattr(g.look, k, val)
        self.refresh()
        self.select_group(g)
        self.changed.emit()
        return g

    def select_group(self, group: LabelGroup) -> None:
        for row, g in enumerate(self.groups.groups):
            if g is group:
                self.table.selectRow(row)
                return

    def clear_all(self) -> None:
        if not self.groups.groups:
            return
        self.groups.clear()
        self.refresh()
        self.changed.emit()

    def refresh(self) -> None:
        self._filling = True
        current = self._current
        names = self.leaf_names or None
        counts = self.groups.effective_counts(names)
        drop_cell_widgets(self.table, (COL_TEXT, COL_BG, COL_VIS, COL_DEL))
        self.table.setRowCount(len(self.groups.groups))
        for row, g in enumerate(self.groups.groups):
            src = QTableWidgetItem(SOURCES[g.source])
            src.setFlags(src.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, COL_SRC, src)
            self.table.setItem(row, COL_NAME, QTableWidgetItem(g.name))
            eff = counts.get(id(g), 0)
            total = len(g.leaves)
            n = QTableWidgetItem(str(total) if eff == total else f"{eff}/{total}")
            n.setFlags(n.flags() & ~Qt.ItemFlag.ItemIsEditable)
            n.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if eff < total:
                n.setToolTip(f"Valendo em {eff} de {total} folhas: {total - eff} estão sob um grupo criado "
                             "depois (vale o mais recente) ou não existem na árvore.")
                n.setForeground(Qt.GlobalColor.darkYellow)
            self.table.setItem(row, COL_N, n)
            tb = _swatch(g.look.text_color, "Cor do texto (vazio = herda)")
            tb.clicked.connect(lambda _=False, gg=g, b=tb: self._pick("text_color", b, gg))
            self.table.setCellWidget(row, COL_TEXT, tb)
            bb = _swatch(g.look.background, "Cor do fundo (vazio = sem fundo)")
            bb.clicked.connect(lambda _=False, gg=g, b=bb: self._pick("background", b, gg))
            self.table.setCellWidget(row, COL_BG, bb)
            vis = QCheckBox()
            vis.setChecked(g.visible)
            vis.toggled.connect(lambda on, gg=g: self._set_visible(gg, on))
            self.table.setCellWidget(row, COL_VIS, vis)
            rm = QToolButton()
            rm.setText("✕")
            rm.setToolTip("Remover grupo")
            rm.setAutoRaise(True)
            rm.clicked.connect(lambda _=False, gg=g: self._remove(gg))
            self.table.setCellWidget(row, COL_DEL, rm)
        self._filling = False
        if current is not None and current in self.groups.groups:
            self.select_group(current)
        else:
            self._current = None
        self._load_editor()
        self.clear_btn.setEnabled(bool(self.groups.groups))

    def load_groups(self, groups: LabelGroupSet) -> None:
        self.groups.groups = groups.groups
        self.groups.show_in_legend = groups.show_in_legend
        was = self.legend_cb.blockSignals(True)
        self.legend_cb.setChecked(groups.show_in_legend)
        self.legend_cb.blockSignals(was)
        self._current = None
        self.refresh()

    def describe_leaf(self, leaf: str) -> str:
        """Texto de status: qual grupo vale para a folha (e quais perderam)."""
        having = [g for g in self.groups.groups if g.visible and leaf in g.leaves]
        if not having:
            return f"{leaf}: sem grupo de rótulo (estilo padrão)."
        msg = f"{leaf}: vale o grupo “{having[-1].name}”"
        if len(having) > 1:
            msg += " (também em " + ", ".join(f"“{g.name}”" for g in having[:-1]) + ")"
        return msg + "."

    # ------------------------------------------------------------ padrão
    def pattern_matches(self) -> list[str]:
        return match_pattern(self.leaf_names, self.pattern.text(), self.regex.isChecked())

    def _update_pattern_count(self) -> None:
        if not self.pattern.text().strip():
            self.pattern_count.setText("")
            self.pattern_count.setStyleSheet(muted_css())
            ok = False
        else:
            try:
                n = len(self.pattern_matches())
                self.pattern_count.setText(f"{n} folha(s) casam")
                self.pattern_count.setStyleSheet(muted_css())
                ok = n > 0
            except ValueError as exc:
                self.pattern_count.setText(str(exc))
                self.pattern_count.setStyleSheet(f"color: {error_color()};")
                ok = False
        self.pattern_select.setEnabled(ok)
        self.pattern_group.setEnabled(ok)

    def _select_pattern(self) -> None:
        try:
            self.select_leaves.emit(self.pattern_matches())
        except ValueError as exc:
            self.status_message.emit(str(exc))

    def _group_from_pattern(self) -> None:
        try:
            matches = self.pattern_matches()
        except ValueError as exc:
            self.status_message.emit(str(exc))
            return
        self.create_group(matches, "pattern", name=self.pattern.text().strip())

    # ------------------------------------------------------------ ações
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != COL_NAME:
            return
        row = item.row()
        if 0 <= row < len(self.groups.groups) and item.text().strip():
            self.groups.groups[row].name = item.text().strip()
            self.changed.emit()

    def _on_row_selected(self) -> None:
        if self._filling:
            return
        rows = {i.row() for i in self.table.selectedIndexes()}
        row = next(iter(rows), -1)
        self._current = self.groups.groups[row] if 0 <= row < len(self.groups.groups) else None
        self._load_editor()

    def _pick(self, attr: str, anchor: QToolButton, group: LabelGroup | None = None) -> None:
        g = group or self._current
        if g is None:
            return

        def pick(color: str | None) -> None:
            setattr(g.look, attr, color)
            self.refresh()
            self.changed.emit()

        palette = HIGHLIGHT_COLORS if attr == "background" else []
        menu = color_menu(self, palette, pick, allow_auto=False)
        menu.addAction("Sem fundo" if attr == "background" else "Herdar (cor padrão/clado)", lambda: pick(None))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _set_visible(self, g: LabelGroup, on: bool) -> None:
        g.visible = on
        self.refresh()
        self.changed.emit()

    def _remove(self, g: LabelGroup) -> None:
        self.groups.remove(g)
        self.refresh()
        self.changed.emit()

    def _legend_toggled(self, on: bool) -> None:
        self.groups.show_in_legend = on
        self.changed.emit()

    # ------------------------------------------------------------ editor
    def _load_editor(self) -> None:
        g = self._current
        self.editor.setEnabled(g is not None)
        self.editor.setTitle("Estilo do grupo" if g else "Estilo do grupo (selecione)")
        name = g.name if g else "Selecione um grupo na lista."
        self.editor_name.setText(self.editor_name.fontMetrics().elidedText(
            name, Qt.TextElideMode.ElideRight, 260))
        self.editor_name.setToolTip(name)
        look = g.look if g else LabelLook()
        widgets = (self.alpha, self.size, self.padding, self.radius, self.bold, self.italic)
        for w in widgets:
            w.blockSignals(True)
        self.text_btn.setStyleSheet(swatch_css(look.text_color, False) if look.text_color else NONE_CSS)
        self.bg_btn.setStyleSheet(swatch_css(look.background, False) if look.background else NONE_CSS)
        self.alpha.setValue(round(look.background_alpha * 100))
        self.size.setValue(round(look.size_scale * 100))
        self.padding.setValue(look.padding)
        self.radius.setValue(look.radius)
        self.bold.setCurrentIndex(next(i for i, (_t, v) in enumerate(TRI) if v is look.bold))
        self.italic.setCurrentIndex(next(i for i, (_t, v) in enumerate(TRI) if v is look.italic))
        for w in widgets:
            w.blockSignals(False)

    def _editor_changed(self, *_args) -> None:  # type: ignore[no-untyped-def]
        g = self._current
        if g is None:
            return
        g.look.background_alpha = self.alpha.value() / 100
        g.look.size_scale = self.size.value() / 100
        g.look.padding = self.padding.value()
        g.look.radius = self.radius.value()
        g.look.bold = self.bold.currentData()
        g.look.italic = self.italic.currentData()
        self.changed.emit()
