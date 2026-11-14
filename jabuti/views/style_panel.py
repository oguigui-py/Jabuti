"""Painel fixo "Estilo": seções recolhíveis com clados, cores e metadados."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jabuti.layout.rectangular import node_depths
from jabuti.models.clades import (
    CladeSet,
    ResolvedClade,
    clades_by_distance,
    clades_by_k,
    clades_by_support,
)
from jabuti.models.tree import SUPPORT_ALL, Tree
from jabuti.style import PALETTES, RenderStyle
from jabuti.views.clade_list import CladeList
from jabuti.views.widgets.collapsible import CollapsibleSection
from jabuti.views.widgets.swatches import SwatchRow, SwatchStrip

MODE_K, MODE_SUPPORT, MODE_DISTANCE, MODE_MANUAL = "k", "support", "distance", "manual"
SLIDER_STEPS = 1000


class LegendWidget(QFrame):
    """Legenda: quadrado de cor + rótulo."""

    EMPTY_TEXT = "A legenda mostra os clados visíveis (e, na Fase 2, a coluna de metadados)."

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(2)
        self.entries: list[tuple[str, str]] = []
        self.set_entries([])

    def set_entries(self, entries: list[tuple[str, str]]) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.entries = list(entries)
        if not entries:
            lbl = QLabel(self.EMPTY_TEXT)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #888;")
            self._lay.addWidget(lbl)
            return
        for text, color in entries:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            sw = QLabel()
            sw.setFixedSize(14, 14)
            sw.setStyleSheet(f"background: {color}; border: 1px solid #777;")
            rl.addWidget(sw)
            rl.addWidget(QLabel(text), 1)
            self._lay.addWidget(row)


class StylePanel(QWidget):
    changed = Signal()          # qualquer mudança visual -> redesenhar
    status_message = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.clade_set = CladeSet()
        self.tree: Tree | None = None
        self.use_lengths = True
        self.max_depth = 0.0

        self.sections: dict[str, CollapsibleSection] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self._add_section(lay, "clades", "Clados e paleta", self._build_clades(), True)
        self._add_section(lay, "colors", "Cores da árvore", self._build_colors(), True)
        self._add_section(lay, "meta", "Metadados e legenda", self._build_meta(), True)
        lay.addStretch(1)

    def _add_section(self, lay: QVBoxLayout, key: str, title: str, w: QWidget, expanded: bool) -> None:
        sec = CollapsibleSection(title, w, expanded)
        self.sections[key] = sec
        lay.addWidget(sec)

    # ------------------------------------------------------------ build
    def _build_clades(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 0, 0, 6)

        # paleta
        pal = QGridLayout()
        self.palette_group = QButtonGroup(self)
        self.palette_buttons: dict[str, QRadioButton] = {}
        for row, (name, colors) in enumerate(PALETTES.items()):
            rb = QRadioButton(name)
            self.palette_group.addButton(rb)
            self.palette_buttons[name] = rb
            pal.addWidget(rb, row, 0)
            pal.addWidget(SwatchStrip(colors), row, 1)
        next(iter(self.palette_buttons.values())).setChecked(True)
        self.palette_group.buttonToggled.connect(lambda _b, on: on and self._palette_changed())
        v.addWidget(QLabel("Paleta:"))
        v.addLayout(pal)

        # detecção
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem("Número de clados (k)", MODE_K)
        self.mode.addItem("Suporte mínimo", MODE_SUPPORT)
        self.mode.addItem("Distância da raiz", MODE_DISTANCE)
        self.mode.addItem("Manual (clique direito no nó)", MODE_MANUAL)
        form.addRow("Detectar por:", self.mode)

        self.params = QStackedWidget()
        self.k_spin = QSpinBox()
        self.k_spin.setRange(1, 500)
        self.k_spin.setValue(4)
        self.params.addWidget(self._row("k =", self.k_spin))

        sup_w = QWidget()
        sup_l = QHBoxLayout(sup_w)
        sup_l.setContentsMargins(0, 0, 0, 0)
        self.sup_thr = QDoubleSpinBox()
        self.sup_thr.setRange(0, 100)
        self.sup_thr.setValue(95)
        self.sup_index = QComboBox()
        sup_l.addWidget(QLabel("≥"))
        sup_l.addWidget(self.sup_thr)
        sup_l.addWidget(self.sup_index, 1)
        self.params.addWidget(sup_w)

        dist_w = QWidget()
        dist_l = QVBoxLayout(dist_w)
        dist_l.setContentsMargins(0, 0, 0, 0)
        self.dist_slider = QSlider(Qt.Orientation.Horizontal)
        self.dist_slider.setRange(0, SLIDER_STEPS)
        self.dist_slider.setValue(SLIDER_STEPS // 3)
        self.dist_label = QLabel("")
        self.show_cut = QCheckBox("Mostrar linha de corte")
        self.show_cut.setChecked(True)
        dist_l.addWidget(self.dist_slider)
        dist_l.addWidget(self.dist_label)
        dist_l.addWidget(self.show_cut)
        self.params.addWidget(dist_w)

        manual_lbl = QLabel("Clique com o botão direito num nó da árvore → “Definir como clado”.")
        manual_lbl.setWordWrap(True)
        self.params.addWidget(manual_lbl)
        form.addRow(self.params)
        v.addLayout(form)

        btns = QHBoxLayout()
        self.detect_btn = QPushButton("Detectar")
        self.clear_btn = QPushButton("Limpar auto")
        self.clear_btn.setToolTip("Remove os clados detectados automaticamente (mantém os manuais)")
        btns.addWidget(self.detect_btn)
        btns.addWidget(self.clear_btn)
        v.addLayout(btns)

        # aplicação
        v.addWidget(QLabel("Aplicar cor em:"))
        grid = QGridLayout()
        self.opt_branches = QCheckBox("Ramos")
        self.opt_labels = QCheckBox("Rótulos")
        self.opt_background = QCheckBox("Faixa de fundo")
        self.opt_strip = QCheckBox("Faixa externa")
        self.opt_strip.setToolTip("Faixa de cor no anel externo (circular) ou coluna ao lado dos rótulos (retangular)")
        self.opt_branches.setChecked(True)
        self.opt_labels.setChecked(True)
        for i, cb in enumerate((self.opt_branches, self.opt_labels, self.opt_background, self.opt_strip)):
            grid.addWidget(cb, i // 2, i % 2)
            cb.toggled.connect(lambda _on: self.changed.emit())
        v.addLayout(grid)
        names = QHBoxLayout()
        self.opt_names = QCheckBox("Nome do clado")
        self.name_mode = QComboBox()
        self.name_mode.addItem("curvo", "curved")
        self.name_mode.addItem("radial", "radial")
        self.name_mode.setToolTip("Só no layout circular")
        names.addWidget(self.opt_names)
        names.addWidget(self.name_mode)
        names.addStretch(1)
        v.addLayout(names)
        self.opt_names.toggled.connect(lambda _on: self.changed.emit())
        self.name_mode.currentIndexChanged.connect(lambda _i: self.changed.emit())

        v.addWidget(QLabel("Fora de clados (neutro):"))
        self.neutral = SwatchRow(selected="#8a8a8a")
        self.neutral.color_changed.connect(lambda _c: self.changed.emit())
        v.addWidget(self.neutral)

        self.clade_list = CladeList(self.clade_set)
        self.clade_list.palette = self.palette_colors()
        self.clade_list.changed.connect(self.changed.emit)
        v.addWidget(self.clade_list)

        # sinais
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.detect_btn.clicked.connect(self.detect)
        self.clear_btn.clicked.connect(self.clear_auto)
        self.k_spin.valueChanged.connect(lambda _v: self._param_changed(MODE_K))
        self.sup_thr.valueChanged.connect(lambda _v: self._param_changed(MODE_SUPPORT))
        self.sup_index.currentIndexChanged.connect(lambda _i: self._param_changed(MODE_SUPPORT))
        self.dist_slider.valueChanged.connect(self._slider_moved)
        self.show_cut.toggled.connect(lambda _on: self.changed.emit())
        self.set_support_options(0)
        self._mode_changed()
        return w

    def _row(self, label: str, widget: QWidget) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(label))
        h.addWidget(widget, 1)
        return w

    def _build_colors(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(8, 0, 0, 6)
        self.branch_row = SwatchRow()
        self.label_row = SwatchRow()
        f.addRow("Ramos:", self.branch_row)
        f.addRow("Rótulos:", self.label_row)
        hint = QLabel("Usadas quando não há clados (ou a opção de clado está desligada).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        f.addRow(hint)
        self.branch_row.color_changed.connect(lambda _c: self.changed.emit())
        self.label_row.color_changed.connect(lambda _c: self.changed.emit())
        return w

    def _build_meta(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 0, 0, 6)
        self.color_by = QComboBox()
        self.set_metadata_columns([])
        self.color_by.currentIndexChanged.connect(lambda _i: self.changed.emit())
        v.addWidget(QLabel("Colorir por coluna:"))
        v.addWidget(self.color_by)
        v.addWidget(QLabel("<b>Legenda</b>"))
        self.legend = LegendWidget()
        v.addWidget(self.legend)
        return w

    # ------------------------------------------------------------ árvore
    def set_tree(self, tree: Tree | None, use_lengths: bool = True) -> None:
        self.tree = tree
        self.use_lengths = use_lengths
        if tree is None:
            self.max_depth = 0.0
        else:
            depth, _ = node_depths(tree, use_lengths)
            self.max_depth = max(depth.values(), default=0.0)
            self.set_support_options(tree.max_support_values())
        self._update_dist_label()

    def set_support_options(self, n_values: int) -> None:
        self.sup_index.blockSignals(True)
        self.sup_index.clear()
        if n_values >= 2:
            self.sup_index.addItem("UFBoot (2º valor)", 1)
            self.sup_index.addItem("SH-aLRT (1º valor)", 0)
            self.sup_index.addItem("ambos ≥", SUPPORT_ALL)
        else:
            self.sup_index.addItem("suporte", -1)
        self.sup_index.setEnabled(n_values >= 2)
        self.sup_index.blockSignals(False)

    def cut_distance(self) -> float:
        return self.max_depth * self.dist_slider.value() / SLIDER_STEPS

    def set_cut_distance(self, d: float) -> None:
        if self.max_depth > 0:
            self.dist_slider.setValue(round(SLIDER_STEPS * d / self.max_depth))

    def _update_dist_label(self) -> None:
        unit = "" if self.use_lengths else " níveis"
        self.dist_label.setText(f"Corte em {self.cut_distance():.4g}{unit} (máx. {self.max_depth:.4g})")

    # ---------------------------------------------------------- clados
    def current_mode(self) -> str:
        return self.mode.currentData()

    def _mode_changed(self) -> None:
        self.params.setCurrentIndex(self.mode.currentIndex())
        # QStackedWidget usa a maior página: ignora o tamanho das páginas ocultas
        for i in range(self.params.count()):
            page = self.params.widget(i)
            pol = QSizePolicy.Policy.Preferred if i == self.params.currentIndex() else QSizePolicy.Policy.Ignored
            page.setSizePolicy(pol, pol)
            page.adjustSize()
        self.params.adjustSize()
        self.detect_btn.setEnabled(self.current_mode() != MODE_MANUAL)
        self.changed.emit()  # linha de corte aparece/some

    def _param_changed(self, mode: str) -> None:
        # ao vivo: se os clados automáticos atuais vieram deste modo, refaz
        if self.clade_set.auto_mode == mode and self.current_mode() == mode:
            self.detect()

    def _slider_moved(self, _v: int) -> None:
        self._update_dist_label()
        if self.clade_set.auto_mode == MODE_DISTANCE and self.current_mode() == MODE_DISTANCE:
            self.detect()
        else:
            self.changed.emit()  # move a linha de corte

    def detect(self) -> int:
        if self.tree is None:
            self.status_message.emit("Carregue uma árvore antes de detectar clados.")
            return 0
        mode = self.current_mode()
        if mode == MODE_K:
            groups = clades_by_k(self.tree, self.k_spin.value(), self.use_lengths)
            msg = f"{len(groups)} clados"
            if len(groups) > self.k_spin.value():
                msg += f" (k={self.k_spin.value()} impossível: politomia — menor corte possível)"
        elif mode == MODE_SUPPORT:
            if not self.tree.max_support_values():
                self.status_message.emit("Esta árvore não tem valores de suporte.")
                return 0
            groups = clades_by_support(self.tree, self.sup_thr.value(), self.sup_index.currentData())
            msg = f"{len(groups)} clados com suporte ≥ {self.sup_thr.value():g}"
        elif mode == MODE_DISTANCE:
            groups = clades_by_distance(self.tree, self.cut_distance(), self.use_lengths)
            msg = f"{len(groups)} clados no corte {self.cut_distance():.4g}"
        else:
            return 0
        self.clade_set.replace_auto(groups, mode)
        self.clade_list.refresh()
        self.status_message.emit(msg)
        self.changed.emit()
        return len(groups)

    def clear_auto(self) -> None:
        self.clade_set.clear_auto()
        self.clade_list.refresh()
        self.changed.emit()

    def add_manual_clade(self, leaves: frozenset[str], name: str | None = None) -> None:
        clade = self.clade_set.add_manual(leaves, name)
        self.clade_list.refresh()
        self.status_message.emit(f"“{clade.name}” definido com {len(leaves)} folha(s). Renomeie na lista de clados.")
        self.changed.emit()

    def remove_clade_with(self, leaves: frozenset[str]) -> None:
        clade = self.clade_set.find(leaves)
        if clade is not None:
            self.clade_set.remove(clade)
            self.clade_list.refresh()
            self.changed.emit()

    def update_status(self, resolved: list[ResolvedClade]) -> None:
        """Chamado após cada desenho: cores efetivas, ⚠ e legenda (sem emitir changed)."""
        self.clade_list.palette = self.palette_colors()
        self.clade_list.set_status(resolved)
        self.legend.set_entries(
            [(rc.clade.name, rc.color) for rc in resolved if rc.valid and rc.clade.visible]
        )

    def _palette_changed(self) -> None:
        self.clade_list.palette = self.palette_colors()
        self.changed.emit()

    # ---------------------------------------------------------- metadados
    def set_metadata_columns(self, columns: list[str]) -> None:
        """Fase 2: preenchido quando metadados forem carregados."""
        self.color_by.blockSignals(True)
        self.color_by.clear()
        if columns:
            self.color_by.addItem("— nenhuma —", None)
            for c in columns:
                self.color_by.addItem(c, c)
        else:
            self.color_by.addItem("Carregue metadados (aba Metadados)", None)
        self.color_by.setEnabled(bool(columns))
        self.color_by.blockSignals(False)

    # ------------------------------------------------------------- estilo
    def palette_name(self) -> str:
        return next(n for n, b in self.palette_buttons.items() if b.isChecked())

    def palette_colors(self) -> list[str]:
        return PALETTES[self.palette_name()]

    def apply_to(self, style: RenderStyle) -> RenderStyle:
        cs = style.clades
        cs.palette = self.palette_name()
        cs.color_branches = self.opt_branches.isChecked()
        cs.color_labels = self.opt_labels.isChecked()
        cs.background = self.opt_background.isChecked()
        cs.outer_strip = self.opt_strip.isChecked()
        cs.show_names = self.opt_names.isChecked()
        cs.name_mode = self.name_mode.currentData()
        cs.neutral_color = self.neutral.color()
        show_line = self.current_mode() == MODE_DISTANCE and self.show_cut.isChecked() and self.tree is not None
        cs.cut_distance = self.cut_distance() if show_line else None
        style.branch.color = self.branch_row.color()
        style.label.color = self.label_row.color()
        style.color_by = self.color_by.currentData()
        return style
