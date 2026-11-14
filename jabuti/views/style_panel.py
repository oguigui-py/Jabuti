"""Painel fixo "Estilo": seções recolhíveis com clados, cores e metadados."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
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
    QListWidget,
    QListWidgetItem,
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
from jabuti.models.document import LADDERIZE, TreeEdits
from jabuti.models.tree import SUPPORT_ALL, Tree
from jabuti.style import (
    GUIDE_KINDS,
    LEGEND_POSITIONS,
    PALETTES,
    SCALE_POSITIONS,
    SUPPORT_MODES,
    TIP_SHAPES,
    RenderStyle,
)
from jabuti.views.clade_list import CladeList
from jabuti.views.widgets.collapsible import CollapsibleSection
from jabuti.views.label_groups_panel import LabelGroupsPanel
from jabuti.models.label_groups import LabelGroupSet, LabelLook
from jabuti.views.widgets.swatches import BASE_COLORS, SwatchRow, SwatchStrip

GUIDE_COLORS = {"Cinza claro": "#a0a0a0", "Cinza": "#6b6b6b", "Preto": "#202020",
                **{k: v for k, v in BASE_COLORS.items() if k in ("Azul", "Vermelho", "Verde")}}
HEAT_PRESENT = {"Azul": "#2b6cb0", "Verde": "#2e7d32", "Vermelho": "#b22222", "Roxo": "#5e3c99",
                "Preto": "#202020"}
HEAT_ABSENT = {"Branco": "#ffffff", "Cinza muito claro": "#f2f2f2", "Amarelo claro": "#fff7d6"}
HEAT_MISSING = {"Cinza": "#d9d9d9", "Cinza médio": "#a6a6a6", "Branco": "#ffffff"}
BACKGROUNDS = {"Branco": "#ffffff", "Cinza muito claro": "#f4f4f4", "Creme": "#fbf7ee",
               "Azul muito claro": "#eef3f9", "Cinza escuro": "#2b2b2b"}

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

    def set_entries(self, entries: list[tuple[str, str]], groups: list | None = None) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.entries = list(entries)
        self.groups = list(groups or [])
        sections = ([("Clados", self.entries, None)] if self.entries else []) + \
            [(g.title, g.entries, g) for g in self.groups]
        if not sections:
            lbl = QLabel(self.EMPTY_TEXT)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #888;")
            self._lay.addWidget(lbl)
            return
        for title, items, group in sections:
            if len(sections) > 1 or self.groups:
                self._lay.addWidget(QLabel(f"<i>{title}</i>"))
            if group is not None and getattr(group, "kind", "") == "colorbar" and group.stops:
                self._add_colorbar(group)
            for text, color in items:
                self._add_row(text, color)

    def _add_colorbar(self, group) -> None:  # type: ignore[no-untyped-def]
        n = max(len(group.stops) - 1, 1)
        stops = ", ".join(f"stop:{i / n:.3f} {c}" for i, c in enumerate(group.stops))
        bar = QLabel()
        bar.setFixedHeight(12)
        bar.setStyleSheet(f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, {stops}); border: 1px solid #777;")
        self._lay.addWidget(bar)
        ticks = QWidget()
        tl = QHBoxLayout(ticks)
        tl.setContentsMargins(0, 0, 0, 0)
        for i, (_f, text) in enumerate(group.ticks):
            if i:
                tl.addStretch(1)
            tl.addWidget(QLabel(f"<small>{text}</small>"))
        self._lay.addWidget(ticks)

    def _add_row(self, text: str, color: str | None) -> None:
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        if color is not None:
            sw = QLabel()
            sw.setFixedSize(14, 14)
            sw.setStyleSheet(f"background: {color}; border: 1px solid #777;")
            rl.addWidget(sw)
        rl.addWidget(QLabel(text), 1)
        self._lay.addWidget(row)


class StylePanel(QWidget):
    changed = Signal()          # qualquer mudança visual -> redesenhar
    status_message = Signal(str)
    preset_action = Signal(str)  # "save" | "load" | "save_default" | "restore" | "forget_default"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.clade_set = CladeSet()
        self.label_groups = LabelGroupSet()
        self.edits = TreeEdits()
        self._pending_meta = None   # escolhas de metadados de um preset, à espera das colunas
        self.tree: Tree | None = None
        self.use_lengths = True
        self.max_depth = 0.0

        self.sections: dict[str, CollapsibleSection] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self._add_section(lay, "clades", "Clados e paleta", self._build_clades(), True)
        self._add_section(lay, "branches", "Ramos", self._build_branches(), False)
        self._add_section(lay, "guides", "Ligações folha → anel", self._build_guides(), False)
        self._add_section(lay, "labels", "Rótulos", self._build_labels(), False)
        self._add_section(lay, "symbols", "Símbolos e suporte", self._build_symbols(), False)
        self._add_section(lay, "scale", "Barra de escala", self._build_scale_bar(), False)
        self._add_section(lay, "heatmap", "Heatmap de genes", self._build_heatmap(), False)
        self._add_section(lay, "tree", "Árvore e fundo", self._build_tree_bg(), False)
        self._add_section(lay, "presets", "Presets", self._build_presets(), False)
        self._add_section(lay, "meta", "Metadados e legenda", self._build_meta(), True)
        lay.addStretch(1)
        # combos não podem alargar o painel fixo (o texto longo aparece na lista aberta)
        for cb in self.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(10)
        for sb in self.findChildren(QDoubleSpinBox):
            sb.setMinimumWidth(60)
            sb.setMaximumWidth(110)

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
        self.opt_labels = QCheckBox("Rótulos (texto)")
        self.opt_label_bg = QCheckBox("Rótulos (fundo)")
        self.opt_label_bg.setToolTip("Marca-texto atrás dos nomes, na cor do clado (não muda os ramos)")
        self.opt_background = QCheckBox("Faixa de fundo")
        self.opt_strip = QCheckBox("Faixa externa")
        self.opt_strip.setToolTip("Faixa de cor no anel externo (circular) ou coluna ao lado dos rótulos (retangular)")
        self.opt_branches.setChecked(True)
        self.opt_labels.setChecked(True)
        for i, cb in enumerate((self.opt_branches, self.opt_labels, self.opt_label_bg, self.opt_background,
                                self.opt_strip)):
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
        extra = QHBoxLayout()
        self.strip_width = self._spin(2, 80, 12, 1)
        self.strip_width.setToolTip("Largura da faixa externa (px)")
        self.bg_alpha = QSpinBox()
        self.bg_alpha.setRange(5, 100)
        self.bg_alpha.setSingleStep(5)
        self.bg_alpha.setValue(18)
        self.bg_alpha.setSuffix(" %")
        self.bg_alpha.setToolTip("Opacidade da faixa de fundo")
        self.bg_alpha.valueChanged.connect(self._emit)
        extra.addWidget(QLabel("Faixa:"))
        extra.addWidget(self.strip_width)
        extra.addWidget(QLabel("Fundo:"))
        extra.addWidget(self.bg_alpha)
        self.label_bg_alpha = QSpinBox()
        self.label_bg_alpha.setRange(5, 100)
        self.label_bg_alpha.setSingleStep(5)
        self.label_bg_alpha.setValue(35)
        self.label_bg_alpha.setSuffix(" %")
        self.label_bg_alpha.setToolTip("Opacidade do fundo dos rótulos (cor do clado)")
        self.label_bg_alpha.valueChanged.connect(self._emit)
        extra.addStretch(1)
        v.addLayout(extra)
        lbg = QHBoxLayout()
        lbg.addWidget(QLabel("Opacidade do fundo dos rótulos:"))
        lbg.addWidget(self.label_bg_alpha)
        lbg.addStretch(1)
        v.addLayout(lbg)

        v.addWidget(QLabel("Fora de clados (neutro):"))
        self.neutral = SwatchRow(selected="#8a8a8a")
        self.neutral.color_changed.connect(lambda _c: self.changed.emit())
        v.addWidget(self.neutral)

        self.clade_list = CladeList(self.clade_set)
        self.clade_list.palette = self.palette_colors()
        self.clade_list.changed.connect(self.changed.emit)
        self.clade_list.style_labels_requested.connect(self.style_clade_labels)
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

    def _emit(self, *_args) -> None:  # type: ignore[no-untyped-def]
        """Adaptador: sinais Qt com argumentos -> ``changed`` sem argumentos."""
        self.changed.emit()

    def _spin(self, lo: float, hi: float, val: float, step: float = 0.1, suffix: str = "") -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setSingleStep(step)
        sb.setDecimals(2 if step < 0.1 else 1)
        sb.setValue(val)
        if suffix:
            sb.setSuffix(suffix)
        sb.valueChanged.connect(self._emit)
        return sb

    def _build_branches(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(8, 0, 0, 6)
        self.branch_row = SwatchRow()
        self.branch_row.color_changed.connect(self._emit)
        f.addRow("Cor padrão:", self.branch_row)
        self.branch_width = self._spin(0.2, 10, 1.2, 0.2)
        f.addRow("Espessura:", self.branch_width)
        self.branch_cap = QComboBox()
        self.branch_cap.addItem("Reta", "flat")
        self.branch_cap.addItem("Arredondada", "round")
        self.branch_cap.currentIndexChanged.connect(self._emit)
        f.addRow("Ponta:", self.branch_cap)
        self.width_by_support = QCheckBox("Espessura proporcional ao suporte")
        self.width_by_support.toggled.connect(self._emit)
        f.addRow(self.width_by_support)
        mm = QHBoxLayout()
        self.min_width = self._spin(0.1, 10, 0.6, 0.1)
        self.max_width = self._spin(0.2, 20, 3.5, 0.5)
        mm.addWidget(QLabel("mín"))
        mm.addWidget(self.min_width)
        mm.addWidget(QLabel("máx"))
        mm.addWidget(self.max_width)
        f.addRow(mm)
        hint = QLabel("Usa o valor escolhido em “Símbolos e suporte → Valor”; nós sem suporte ficam com a mínima. "
                      "A cor padrão vale quando não há clados (ou a opção de clado está desligada).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        f.addRow(hint)
        return w

    def _build_guides(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(8, 0, 0, 6)
        self.guide_kind = QComboBox()
        for key, label in GUIDE_KINDS.items():
            self.guide_kind.addItem(label, key)
        self.guide_kind.setCurrentIndex(self.guide_kind.findData("dots"))
        self.guide_kind.currentIndexChanged.connect(self._emit)
        f.addRow("Estilo:", self.guide_kind)
        self.guide_row = SwatchRow(GUIDE_COLORS, selected="#a0a0a0")
        self.guide_row.color_changed.connect(self._emit)
        f.addRow("Cor:", self.guide_row)
        self.guide_width = self._spin(0.1, 6, 0.6, 0.1)
        f.addRow("Espessura:", self.guide_width)
        self.guide_opacity = QSpinBox()
        self.guide_opacity.setRange(5, 100)
        self.guide_opacity.setSingleStep(5)
        self.guide_opacity.setValue(100)
        self.guide_opacity.setSuffix(" %")
        self.guide_opacity.valueChanged.connect(self._emit)
        f.addRow("Opacidade:", self.guide_opacity)
        hint = QLabel("Ligação da ponta do ramo ao anel externo (layout circular com pontas alinhadas).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        f.addRow(hint)
        return w

    def _build_labels(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(8, 0, 0, 6)
        self.show_labels = QCheckBox("Mostrar nomes das folhas")
        self.show_labels.setChecked(True)
        self.show_labels.toggled.connect(self._emit)
        f.addRow(self.show_labels)
        self.font_family = QComboBox()
        self.font_family.addItem("Padrão do sistema", "")
        for fam in QFontDatabase.families():
            if not fam.startswith("."):
                self.font_family.addItem(fam, fam)
        self.font_family.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.font_family.setMinimumContentsLength(14)
        self.font_family.currentIndexChanged.connect(self._emit)
        f.addRow("Fonte:", self.font_family)
        self.font_size = self._spin(2, 48, 10, 0.5)
        f.addRow("Tamanho:", self.font_size)
        bi = QHBoxLayout()
        self.font_bold = QCheckBox("Negrito")
        self.font_italic = QCheckBox("Itálico")
        self.font_italic.setChecked(True)
        self.font_italic.setToolTip("Padrão para nomes de espécie")
        for cb in (self.font_bold, self.font_italic):
            cb.toggled.connect(self._emit)
            bi.addWidget(cb)
        bi.addStretch(1)
        f.addRow(bi)
        self.label_row = SwatchRow()
        self.label_row.color_changed.connect(self._emit)
        f.addRow("Cor padrão:", self.label_row)
        hint = QLabel("<b>Grupos de destaque</b> — estilo próprio para alguns nomes (texto, fundo "
                      "marca-texto, negrito…), sem mexer nos ramos. Em conflito vale o grupo mais recente.")
        hint.setWordWrap(True)
        f.addRow(hint)
        self.label_panel = LabelGroupsPanel(self.label_groups)
        self.label_panel.changed.connect(self.changed.emit)
        self.label_panel.status_message.connect(self.status_message.emit)
        f.addRow(self.label_panel)
        return w

    def style_clade_labels(self, clade) -> None:  # type: ignore[no-untyped-def]
        """Grupo de rótulos com as folhas do clado; fundo inicial na cor do clado."""
        idx = next((i for i, c in enumerate(self.clade_set.clades) if c is clade), 0)
        color = self.clade_list.color_of(idx, clade)
        g = self.label_panel.create_group(clade.leaves, "clade", name=clade.name,
                                          look=LabelLook(background=color, background_alpha=0.35))
        if g is not None:
            self.sections["labels"].set_expanded(True)

    def _build_symbols(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(8, 0, 0, 6)
        f.addRow(QLabel("<b>Pontas das folhas</b>"))
        self.tip_shape = QComboBox()
        for key, label in TIP_SHAPES.items():
            self.tip_shape.addItem(label, key)
        self.tip_shape.currentIndexChanged.connect(self._emit)
        f.addRow("Símbolo:", self.tip_shape)
        self.tip_size = self._spin(1, 30, 6, 0.5)
        f.addRow("Tamanho:", self.tip_size)
        self.tip_row = SwatchRow()
        self.tip_row.color_changed.connect(self._emit)
        f.addRow("Cor:", self.tip_row)
        self.tip_clade_color = QCheckBox("Usar a cor do clado")
        self.tip_clade_color.setChecked(True)
        self.tip_clade_color.toggled.connect(self._emit)
        f.addRow(self.tip_clade_color)

        f.addRow(QLabel("<b>Suporte dos nós</b>"))
        self.support_mode = QComboBox()
        for key, label in SUPPORT_MODES.items():
            self.support_mode.addItem(label, key)
        self.support_mode.currentIndexChanged.connect(self._emit)
        f.addRow("Mostrar como:", self.support_mode)
        self.support_which = QComboBox()
        self.support_which.currentIndexChanged.connect(self._emit)
        f.addRow("Valor:", self.support_which)
        self.support_threshold = self._spin(0, 100, 0, 1)
        self.support_threshold.setToolTip("Números: oculta valores abaixo do limiar.\n"
                                          "Símbolos: círculo cheio se ≥ limiar, vazado abaixo.")
        f.addRow("Limiar:", self.support_threshold)
        self.support_symbol_size = self._spin(1, 30, 6, 0.5)
        f.addRow("Tamanho do símbolo:", self.support_symbol_size)
        self.support_size_by_value = QCheckBox("Tamanho proporcional ao valor")
        self.support_size_by_value.toggled.connect(self._emit)
        f.addRow(self.support_size_by_value)
        self.support_row = SwatchRow(selected="#6b6b6b")
        self.support_row.color_changed.connect(self._emit)
        f.addRow("Cor:", self.support_row)
        self.set_display_support_options(0)
        return w

    def _build_scale_bar(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(8, 0, 0, 6)
        self.scale_show = QCheckBox("Mostrar barra de escala")
        self.scale_show.setChecked(True)
        self.scale_show.toggled.connect(self._emit)
        f.addRow(self.scale_show)
        self.scale_pos = QComboBox()
        for key, label in SCALE_POSITIONS.items():
            self.scale_pos.addItem(label, key)
        self.scale_pos.currentIndexChanged.connect(self._emit)
        f.addRow("Posição:", self.scale_pos)
        row = QHBoxLayout()
        self.scale_auto = QCheckBox("Automático")
        self.scale_auto.setChecked(True)
        self.scale_len = QDoubleSpinBox()
        self.scale_len.setDecimals(4)
        self.scale_len.setRange(0.0001, 1e6)
        self.scale_len.setValue(0.05)
        self.scale_len.setEnabled(False)
        self.scale_auto.toggled.connect(lambda on: (self.scale_len.setEnabled(not on), self._emit()))
        self.scale_len.valueChanged.connect(self._emit)
        row.addWidget(self.scale_auto)
        row.addWidget(self.scale_len, 1)
        f.addRow("Comprimento:", row)
        return w

    def set_display_support_options(self, n_values: int) -> None:
        self.support_which.blockSignals(True)
        self.support_which.clear()
        if n_values >= 2:
            self.support_which.addItem("UFBoot (2º valor)", 1)
            self.support_which.addItem("SH-aLRT (1º valor)", 0)
            self.support_which.addItem("Ambos (a/b; símbolo usa o menor)", SUPPORT_ALL)
        else:
            self.support_which.addItem("Único", -1)
        self.support_which.setEnabled(n_values >= 2)
        self.support_mode.setEnabled(n_values > 0)
        if n_values == 0:
            self.support_mode.setCurrentIndex(0)
        self.support_which.blockSignals(False)

    def _build_heatmap(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(8, 0, 0, 6)
        self.hm_present = SwatchRow(HEAT_PRESENT, selected="#2b6cb0")
        self.hm_absent = SwatchRow(HEAT_ABSENT, selected="#ffffff")
        self.hm_missing = SwatchRow(HEAT_MISSING, selected="#d9d9d9")
        for row in (self.hm_present, self.hm_absent, self.hm_missing):
            row.color_changed.connect(self._emit)
        f.addRow("Presente:", self.hm_present)
        f.addRow("Ausente:", self.hm_absent)
        f.addRow("Sem GFF:", self.hm_missing)
        self.hm_width = self._spin(0.3, 5, 1.0, 0.1)
        f.addRow("Largura da célula:", self.hm_width)
        self.hm_counts = QCheckBox("Mostrar nº de cópias (> 1)")
        self.hm_headers = QCheckBox("Nomes das colunas (retangular)")
        self.hm_headers.setChecked(True)
        self.hm_borders = QCheckBox("Bordas das células")
        self.hm_borders.setChecked(True)
        for cb in (self.hm_counts, self.hm_headers, self.hm_borders):
            cb.toggled.connect(self._emit)
            f.addRow(cb)
        f.addRow(QLabel("<b>Contexto gênico</b>"))
        self.ctx_width = self._spin(100, 2000, 360, 20)
        self.ctx_width.setDecimals(0)
        f.addRow("Largura (px):", self.ctx_width)
        self.ctx_labels = QCheckBox("Nomes dos genes (quando cabem)")
        self.ctx_labels.setChecked(True)
        self.ctx_labels.toggled.connect(self._emit)
        f.addRow(self.ctx_labels)
        hint = QLabel("As colunas vêm das buscas na aba GFF. No circular viram anéis (de dentro para fora "
                      "na ordem da lista; veja a legenda).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        f.addRow(hint)
        return w

    def _build_tree_bg(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(8, 0, 0, 6)
        self.ladder = QComboBox()
        for key, label in LADDERIZE.items():
            self.ladder.addItem(label, key)
        self.ladder.currentIndexChanged.connect(self._ladder_changed)
        f.addRow("Ladderize:", self.ladder)
        row = QHBoxLayout()
        self.reset_rot_btn = QPushButton("Desfazer rotações")
        self.expand_all_btn = QPushButton("Expandir todos")
        self.reset_rot_btn.clicked.connect(self.reset_rotations)
        self.expand_all_btn.clicked.connect(self.expand_all)
        row.addWidget(self.reset_rot_btn)
        row.addWidget(self.expand_all_btn)
        f.addRow(row)
        hint = QLabel("Clique direito num nó: girar (inverter filhos), colapsar em triângulo ou expandir.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        f.addRow(hint)
        self.bg_row = SwatchRow(BACKGROUNDS, selected="#ffffff")
        self.bg_row.color_changed.connect(self._emit)
        f.addRow("Fundo:", self.bg_row)
        self.bg_transparent = QCheckBox("Transparente (também no export)")
        self.bg_transparent.toggled.connect(lambda on: (self.bg_row.setEnabled(not on), self._emit()))
        f.addRow(self.bg_transparent)
        return w

    # ------------------------------------------------------- edições
    def _ladder_changed(self) -> None:
        self.edits.ladderize = self.ladder.currentData()
        self.changed.emit()

    def rotate(self, leaves: frozenset[str]) -> None:
        self.edits.toggle_rotation(leaves)
        self.changed.emit()

    def reset_rotations(self) -> None:
        self.edits.rotations.clear()
        self.changed.emit()

    def collapse(self, leaves: frozenset[str]) -> None:
        self.edits.collapse(leaves)
        self.changed.emit()

    def expand(self, leaves: frozenset[str]) -> None:
        self.edits.expand(leaves)
        self.changed.emit()

    def expand_all(self) -> None:
        self.edits.collapsed.clear()
        self.changed.emit()

    def _build_presets(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(8, 0, 0, 6)
        buttons = [
            ("Salvar preset…", "save", "Todas as configurações visuais, clados e edições em um arquivo JSON"),
            ("Carregar preset…", "load", "Aplica um preset salvo (clados com folhas ausentes ficam marcados com ⚠)"),
            ("Salvar como meu padrão", "save_default", "Estilo e detecção (sem clados/edições) usados ao abrir o app"),
            ("Restaurar padrão", "restore", "Volta ao padrão de fábrica do estilo (mantém clados, rotações e colapsos)"),
        ]
        self.preset_buttons: dict[str, QPushButton] = {}
        for i, (label, key, tip) in enumerate(buttons):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self.preset_action.emit(k))
            self.preset_buttons[key] = b
            g.addWidget(b, i // 2, i % 2)
        self.default_info = QLabel("")
        self.default_info.setWordWrap(True)
        self.default_info.setStyleSheet("color: #888;")
        g.addWidget(self.default_info, 2, 0, 1, 2)
        self.forget_default_btn = QPushButton("Esquecer meu padrão")
        self.forget_default_btn.clicked.connect(lambda: self.preset_action.emit("forget_default"))
        g.addWidget(self.forget_default_btn, 3, 0, 1, 2)
        return w

    def set_default_info(self, path: str | None) -> None:
        if path:
            self.default_info.setText(f"Meu padrão: {path}")
        else:
            self.default_info.setText("Sem padrão pessoal: o app abre com o padrão de fábrica.")
        self.forget_default_btn.setEnabled(bool(path))

    # ------------------------------------------------------------ presets
    def detection_dict(self) -> dict:
        return {
            "mode": self.current_mode(),
            "k": self.k_spin.value(),
            "support_threshold": float(self.sup_thr.value()),
            "support_index": self.sup_index.currentData() if self.sup_index.currentData() is not None else 1,
            "distance_fraction": self.dist_slider.value() / SLIDER_STEPS,
            "show_cut": self.show_cut.isChecked(),
        }

    def load_detection(self, det: dict) -> None:
        was = self.blockSignals(True)
        try:
            self.mode.setCurrentIndex(max(self.mode.findData(det["mode"]), 0))
            self.k_spin.setValue(int(det["k"]))
            self.sup_thr.setValue(float(det["support_threshold"]))
            idx = self.sup_index.findData(det["support_index"])
            if idx >= 0:
                self.sup_index.setCurrentIndex(idx)
            self.dist_slider.setValue(round(float(det["distance_fraction"]) * SLIDER_STEPS))
            self.show_cut.setChecked(bool(det["show_cut"]))
        finally:
            self.blockSignals(was)

    def load_style(self, style: RenderStyle) -> list[str]:
        """Põe o estilo nos controles (sem redesenhar a cada campo). Devolve avisos."""
        warnings: list[str] = []
        was = self.blockSignals(True)
        try:
            cs = style.clades
            self.palette_buttons.get(cs.palette, next(iter(self.palette_buttons.values()))).setChecked(True)
            self.opt_branches.setChecked(cs.color_branches)
            self.opt_labels.setChecked(cs.color_labels)
            self.opt_label_bg.setChecked(cs.label_background)
            self.label_bg_alpha.setValue(round(cs.label_background_alpha * 100))
            self.opt_background.setChecked(cs.background)
            self.opt_strip.setChecked(cs.outer_strip)
            self.opt_names.setChecked(cs.show_names)
            self.name_mode.setCurrentIndex(max(self.name_mode.findData(cs.name_mode), 0))
            self.neutral.set_color(cs.neutral_color)
            self.strip_width.setValue(cs.strip_width)
            self.bg_alpha.setValue(round(cs.background_alpha * 100))

            b = style.branch
            self.branch_row.set_color(b.color)
            self.branch_width.setValue(b.width)
            self.branch_cap.setCurrentIndex(max(self.branch_cap.findData(b.cap), 0))
            self.width_by_support.setChecked(b.width_by_support)
            self.min_width.setValue(b.min_width)
            self.max_width.setValue(b.max_width)

            g = style.guide
            self.guide_kind.setCurrentIndex(max(self.guide_kind.findData(g.kind), 0))
            self.guide_row.set_color(g.color)
            self.guide_width.setValue(g.width)
            self.guide_opacity.setValue(round(g.opacity * 100))

            lab = style.label
            self.show_labels.setChecked(lab.show)
            fam = self.font_family.findData(lab.family) if lab.family else 0
            if fam < 0:
                warnings.append(f"Fonte “{lab.family}” não instalada; usando a padrão do sistema.")
                fam = 0
            self.font_family.setCurrentIndex(fam)
            self.font_size.setValue(lab.size)
            self.font_bold.setChecked(lab.bold)
            self.font_italic.setChecked(lab.italic)
            self.label_row.set_color(lab.color)

            sym = style.symbols
            self.tip_shape.setCurrentIndex(max(self.tip_shape.findData(sym.shape), 0))
            self.tip_size.setValue(sym.size)
            self.tip_row.set_color(sym.color)
            self.tip_clade_color.setChecked(sym.use_clade_color)

            sup = style.support
            self.support_mode.setCurrentIndex(max(self.support_mode.findData(sup.mode), 0))
            idx = self.support_which.findData(sup.index)
            if idx >= 0:
                self.support_which.setCurrentIndex(idx)
            self.support_threshold.setValue(sup.threshold)
            self.support_symbol_size.setValue(sup.symbol_size)
            self.support_size_by_value.setChecked(sup.size_by_value)
            self.support_row.set_color(sup.color)

            sb = style.scale_bar
            self.scale_show.setChecked(sb.show)
            self.scale_pos.setCurrentIndex(max(self.scale_pos.findData(sb.position), 0))
            self.scale_auto.setChecked(sb.length is None)
            if sb.length is not None:
                self.scale_len.setValue(sb.length)

            hm = style.heatmap
            self.hm_present.set_color(hm.present_color)
            self.hm_absent.set_color(hm.absent_color)
            self.hm_missing.set_color(hm.missing_color)
            self.hm_width.setValue(hm.cell_width)
            self.hm_counts.setChecked(hm.show_counts)
            self.hm_headers.setChecked(hm.show_headers)
            self.hm_borders.setChecked(hm.borders)
            self.ctx_width.setValue(style.context.width)
            self.ctx_labels.setChecked(style.context.show_labels)

            md = style.metadata
            self.meta_labels.setChecked(md.color_labels)
            self.meta_branches.setChecked(md.color_branches)
            self.meta_strip_width.setValue(md.strip_width)
            self.meta_missing.set_color(md.missing_color)
            idx = self.color_by.findData(md.color_by) if md.color_by else 0
            self.color_by.setCurrentIndex(max(idx, 0))
            available = {self.meta_strips.item(i).data(Qt.ItemDataRole.UserRole)
                         for i in range(self.meta_strips.count())}
            for col in available:
                self.set_strip_checked(col, col in md.strips)
            missing_cols = [c for c in [md.color_by, *md.strips] if c and c not in available]
            if missing_cols and available:
                warnings.append("Colunas do preset ausentes nos metadados abertos: " + ", ".join(missing_cols))
            self._pending_meta = md if missing_cols or not available else None

            self.legend_in_figure.setChecked(style.legend.in_figure)
            self.legend_pos.setCurrentIndex(max(self.legend_pos.findData(style.legend.position), 0))
            self.bg_transparent.setChecked(style.background is None)
            if style.background:
                self.bg_row.set_color(style.background)
            self.clade_list.palette = self.palette_colors()
        finally:
            self.blockSignals(was)
        return warnings

    def load_tree_state(self, clade_set: CladeSet | None, edits: TreeEdits | None) -> None:
        if clade_set is not None:
            self.clade_set.clades = clade_set.clades
            self.clade_set.auto_mode = clade_set.auto_mode
            self.clade_list.refresh()
        if edits is not None:
            self.edits.ladderize = edits.ladderize
            self.edits.rotations = list(edits.rotations)
            self.edits.collapsed = list(edits.collapsed)
            self.edits.hidden = set(edits.hidden)
            self.edits.shortened = list(edits.shortened)
            self.edits.marked = set(edits.marked)
            self.edits.highlights = list(edits.highlights)
            was = self.ladder.blockSignals(True)
            self.ladder.setCurrentIndex(max(self.ladder.findData(edits.ladderize), 0))
            self.ladder.blockSignals(was)

    def _build_meta(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 0, 0, 6)
        self.color_by = QComboBox()
        self.color_by.currentIndexChanged.connect(self._emit)
        v.addWidget(QLabel("Colorir por coluna:"))
        v.addWidget(self.color_by)
        row = QHBoxLayout()
        self.meta_labels = QCheckBox("rótulos")
        self.meta_labels.setChecked(True)
        self.meta_branches = QCheckBox("ramos")
        for cb in (self.meta_labels, self.meta_branches):
            cb.toggled.connect(self._emit)
            row.addWidget(cb)
        row.addStretch(1)
        v.addLayout(row)
        hint = QLabel("A cor do metadado tem prioridade sobre a dos clados. Ramo interno só recebe a cor "
                      "se todas as folhas abaixo dele tiverem a mesma.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        v.addWidget(hint)
        v.addWidget(QLabel("Faixas de cor (ao lado da árvore / anéis):"))
        self.meta_strips = QListWidget()
        self.meta_strips.setMaximumHeight(110)
        self.meta_strips.itemChanged.connect(self._emit)
        v.addWidget(self.meta_strips)
        f = QFormLayout()
        self.meta_strip_width = self._spin(2, 80, 12, 1)
        f.addRow("Largura da faixa:", self.meta_strip_width)
        self.meta_missing = SwatchRow(HEAT_MISSING, selected="#d9d9d9")
        self.meta_missing.color_changed.connect(self._emit)
        f.addRow("Sem valor:", self.meta_missing)
        v.addLayout(f)
        self.set_metadata_columns([])
        v.addWidget(QLabel("<b>Legenda</b>"))
        self.legend_in_figure = QCheckBox("Incluir legenda na figura exportada")
        self.legend_in_figure.setToolTip("Desenha esta legenda ao lado da árvore (aparece também na tela,\n"
                                         "igual no SVG, PDF e PNG), sem cobrir árvore, heatmap ou escala")
        self.legend_in_figure.toggled.connect(self._emit)
        v.addWidget(self.legend_in_figure)
        self.legend_pos = QComboBox()
        for key, text in LEGEND_POSITIONS.items():
            self.legend_pos.addItem(text, key)
        self.legend_pos.currentIndexChanged.connect(self._emit)
        v.addWidget(self._row("Posição:", self.legend_pos))
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
            self.set_display_support_options(tree.max_support_values())
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

    def update_status(self, resolved: list[ResolvedClade], groups: list | None = None) -> None:
        """Chamado após cada desenho: cores efetivas, ⚠ e legenda (sem emitir changed)."""
        self.clade_list.palette = self.palette_colors()
        self.clade_list.set_status(resolved)
        self.legend.set_entries(
            [(rc.clade.name, rc.color) for rc in resolved if rc.valid and rc.clade.visible], groups
        )

    def set_layout(self, kind) -> None:  # type: ignore[no-untyped-def]
        """Desativa (com dica) as opções de clado que não se aplicam à árvore não enraizada."""
        ok = getattr(kind, "value", kind) != "unrooted"
        tip = "" if ok else "Não se aplica à árvore não enraizada (as cores valem nos ramos e rótulos)."
        for w in (self.opt_background, self.opt_strip, self.opt_names, self.name_mode):
            w.setEnabled(ok)
            w.setToolTip(tip)

    def _palette_changed(self) -> None:
        self.clade_list.palette = self.palette_colors()
        self.changed.emit()

    # ---------------------------------------------------------- metadados
    def set_metadata_columns(self, columns: list[str], kinds: dict[str, str] | None = None) -> None:
        """Preenche "colorir por" e a lista de faixas, preservando as escolhas que ainda existem."""
        kinds = kinds or {}
        current = self.color_by.currentData() if self.color_by.count() else None
        checked = set(self.checked_strips()) if hasattr(self, "meta_strips") else set()
        self.color_by.blockSignals(True)
        self.color_by.clear()
        if columns:
            self.color_by.addItem("— nenhuma —", None)
            for c in columns:
                self.color_by.addItem(f"{c} ({kinds[c]})" if c in kinds else c, c)
            idx = self.color_by.findData(current)
            self.color_by.setCurrentIndex(max(idx, 0))
        else:
            self.color_by.addItem("Carregue metadados (aba Metadados)", None)
        self.color_by.setEnabled(bool(columns))
        self.color_by.blockSignals(False)
        self.meta_strips.blockSignals(True)
        self.meta_strips.clear()
        for c in columns:
            item = QListWidgetItem(f"{c} ({kinds[c]})" if c in kinds else c)
            item.setData(Qt.ItemDataRole.UserRole, c)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if c in checked else Qt.CheckState.Unchecked)
            self.meta_strips.addItem(item)
        self.meta_strips.setEnabled(bool(columns))
        self.meta_strips.blockSignals(False)
        pend = self._pending_meta
        if pend is not None and columns:
            self.blockSignals(True)
            try:
                if pend.color_by in columns:
                    self.color_by.setCurrentIndex(self.color_by.findData(pend.color_by))
                for c in columns:
                    if c in pend.strips:
                        self.set_strip_checked(c, True)
            finally:
                self.blockSignals(False)
            self._pending_meta = None

    def checked_strips(self) -> list[str]:
        return [self.meta_strips.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.meta_strips.count())
                if self.meta_strips.item(i).checkState() == Qt.CheckState.Checked]

    def set_strip_checked(self, column: str, on: bool) -> None:
        for i in range(self.meta_strips.count()):
            item = self.meta_strips.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == column:
                item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

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
        cs.label_background = self.opt_label_bg.isChecked()
        cs.label_background_alpha = self.label_bg_alpha.value() / 100
        cs.background = self.opt_background.isChecked()
        cs.outer_strip = self.opt_strip.isChecked()
        cs.show_names = self.opt_names.isChecked()
        cs.name_mode = self.name_mode.currentData()
        cs.neutral_color = self.neutral.color()
        cs.strip_width = self.strip_width.value()
        cs.background_alpha = self.bg_alpha.value() / 100
        show_line = self.current_mode() == MODE_DISTANCE and self.show_cut.isChecked() and self.tree is not None
        cs.cut_distance = self.cut_distance() if show_line else None
        b = style.branch
        b.color = self.branch_row.color()
        b.width = self.branch_width.value()
        b.cap = self.branch_cap.currentData()
        b.width_by_support = self.width_by_support.isChecked()
        b.min_width = min(self.min_width.value(), self.max_width.value())
        b.max_width = max(self.min_width.value(), self.max_width.value())
        g = style.guide
        g.kind = self.guide_kind.currentData()
        g.color = self.guide_row.color()
        g.width = self.guide_width.value()
        g.opacity = self.guide_opacity.value() / 100
        lab = style.label
        lab.show = self.show_labels.isChecked()
        lab.family = self.font_family.currentData() or ""
        lab.size = self.font_size.value()
        lab.bold = self.font_bold.isChecked()
        lab.italic = self.font_italic.isChecked()
        lab.color = self.label_row.color()
        sym = style.symbols
        sym.shape = self.tip_shape.currentData()
        sym.size = self.tip_size.value()
        sym.color = self.tip_row.color()
        sym.use_clade_color = self.tip_clade_color.isChecked()
        sup = style.support
        sup.mode = self.support_mode.currentData() if self.support_mode.isEnabled() else "none"
        sup.index = self.support_which.currentData()
        sup.threshold = self.support_threshold.value()
        sup.symbol_size = self.support_symbol_size.value()
        sup.size_by_value = self.support_size_by_value.isChecked()
        sup.color = self.support_row.color()
        sb = style.scale_bar
        sb.show = self.scale_show.isChecked()
        sb.position = self.scale_pos.currentData()
        sb.length = None if self.scale_auto.isChecked() else self.scale_len.value()
        style.background = None if self.bg_transparent.isChecked() else self.bg_row.color()
        style.legend.in_figure = self.legend_in_figure.isChecked()
        style.legend.position = self.legend_pos.currentData()
        hm = style.heatmap
        hm.present_color = self.hm_present.color()
        hm.absent_color = self.hm_absent.color()
        hm.missing_color = self.hm_missing.color()
        hm.cell_width = self.hm_width.value()
        hm.show_counts = self.hm_counts.isChecked()
        hm.show_headers = self.hm_headers.isChecked()
        hm.borders = self.hm_borders.isChecked()
        style.context.width = self.ctx_width.value()
        style.context.show_labels = self.ctx_labels.isChecked()
        md = style.metadata
        md.color_by = self.color_by.currentData()
        md.color_labels = self.meta_labels.isChecked()
        md.color_branches = self.meta_branches.isChecked()
        md.strips = self.checked_strips()
        md.strip_width = self.meta_strip_width.value()
        md.missing_color = self.meta_missing.color()
        return style
