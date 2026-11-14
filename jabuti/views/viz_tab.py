"""Aba "Visualização": opções de desenho e exportação."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from jabuti.style import BranchStyle, LabelStyle, LayoutKind, RenderStyle, SupportStyle


class VizTab(QWidget):
    generate_requested = Signal()
    export_requested = Signal(str)  # "svg" | "pdf" | "png"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gen_btn = QPushButton("Gerar")
        self.gen_btn.setDefault(True)
        self.gen_btn.clicked.connect(self.generate_requested.emit)

        self.layout_cb = QComboBox()
        self.layout_cb.addItem("Retangular", LayoutKind.RECTANGULAR)
        self.layout_cb.addItem("Circular", LayoutKind.CIRCULAR)
        self.use_lengths = QCheckBox("Usar comprimentos de ramo")
        self.use_lengths.setToolTip("Desmarcado = cladograma (todas as folhas alinhadas)")
        self.use_lengths.setChecked(True)
        self.align_tips = QCheckBox("Alinhar pontas no anel externo")
        self.align_tips.setChecked(True)
        self.align_tips.setToolTip(
            "Circular: todas as folhas terminam no mesmo raio; a diferença até o anel\n"
            "é ligada por uma linha pontilhada cinza. Desmarque para ver o desenho original."
        )
        self.layout_cb.currentIndexChanged.connect(self._sync_layout_options)
        self.show_labels = QCheckBox("Mostrar nomes das folhas")
        self.show_labels.setChecked(True)
        self.show_support = QCheckBox("Mostrar suporte (bootstrap/UFBoot)")
        self.support_which = QComboBox()
        self.support_threshold = QDoubleSpinBox()
        self.support_threshold.setRange(0, 100)
        self.support_threshold.setDecimals(1)
        self.support_threshold.setToolTip("Exibe apenas valores ≥ limiar")
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(2, 48)
        self.font_size.setValue(10)
        self.branch_scale = QSpinBox()
        self.branch_scale.setRange(10, 1000)
        self.branch_scale.setSuffix(" %")
        self.branch_scale.setValue(100)
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(1.0, 5.0)
        self.spacing.setSingleStep(0.1)
        self.spacing.setValue(1.6)
        self.branch_width = QDoubleSpinBox()
        self.branch_width.setRange(0.2, 10)
        self.branch_width.setSingleStep(0.2)
        self.branch_width.setValue(1.2)
        self.set_support_options(0)
        self._sync_layout_options()

        form = QFormLayout()
        form.addRow("Layout:", self.layout_cb)
        form.addRow(self.use_lengths)
        form.addRow(self.align_tips)
        form.addRow(self.show_labels)
        form.addRow(self.show_support)
        form.addRow("Valor de suporte:", self.support_which)
        form.addRow("Limiar de suporte:", self.support_threshold)
        form.addRow("Tamanho da fonte:", self.font_size)
        form.addRow("Escala dos ramos:", self.branch_scale)
        form.addRow("Espaço entre folhas:", self.spacing)
        form.addRow("Espessura dos ramos:", self.branch_width)

        exp = QGroupBox("Exportar")
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 1200)
        self.dpi.setValue(300)
        self.dpi.setSuffix(" dpi")
        row = QHBoxLayout()
        for fmt in ("svg", "pdf", "png"):
            b = QPushButton(fmt.upper())
            b.clicked.connect(lambda _=False, f=fmt: self.export_requested.emit(f))
            row.addWidget(b)
        el = QFormLayout(exp)
        el.addRow(row)
        el.addRow("Resolução PNG:", self.dpi)

        lay = QVBoxLayout(self)
        lay.addWidget(self.gen_btn)
        lay.addLayout(form)
        lay.addWidget(exp)
        lay.addStretch(1)

    def _sync_layout_options(self) -> None:
        self.align_tips.setEnabled(self.layout_cb.currentData() == LayoutKind.CIRCULAR)

    def set_support_options(self, n_values: int) -> None:
        self.support_which.clear()
        if n_values >= 2:
            self.support_which.addItem("Todos (ex.: SH-aLRT/UFBoot)", 99)
            self.support_which.addItem("1º valor (ex.: SH-aLRT)", 0)
            self.support_which.addItem("2º valor (ex.: UFBoot)", 1)
            self.support_which.setCurrentIndex(2)
        else:
            self.support_which.addItem("Único", -1)
        self.support_which.setEnabled(n_values >= 2)
        self.show_support.setEnabled(n_values > 0)
        if n_values == 0:
            self.show_support.setChecked(False)

    def render_style(self) -> RenderStyle:
        return RenderStyle(
            layout=self.layout_cb.currentData(),
            branch_scale=self.branch_scale.value() / 100,
            leaf_spacing=self.spacing.value(),
            use_lengths=self.use_lengths.isChecked(),
            align_tips=self.align_tips.isChecked(),
            branch=BranchStyle(width=self.branch_width.value()),
            label=LabelStyle(size=self.font_size.value(), show=self.show_labels.isChecked()),
            support=SupportStyle(
                show=self.show_support.isChecked(),
                index=self.support_which.currentData(),
                threshold=self.support_threshold.value(),
            ),
        )
