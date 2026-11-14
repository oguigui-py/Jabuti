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
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from jabuti.style import LAYOUT_NAMES, FanStyle, LayoutKind, RenderStyle, UnrootedStyle

NOT_UNROOTED = "Não se aplica à árvore não enraizada."


class VizTab(QWidget):
    generate_requested = Signal()
    export_requested = Signal(str)  # "svg" | "pdf" | "png" | "tiff"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gen_btn = QPushButton("Gerar")
        self.gen_btn.setDefault(True)
        self.gen_btn.clicked.connect(self.generate_requested.emit)

        self.layout_cb = QComboBox()
        for kind in (LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR, LayoutKind.FAN, LayoutKind.SLANTED,
                     LayoutKind.UNROOTED):
            self.layout_cb.addItem(LAYOUT_NAMES[kind.value], kind)
        self.use_lengths = QCheckBox("Usar comprimentos de ramo")
        self.use_lengths.setToolTip("Desmarcado = cladograma (todas as folhas alinhadas)")
        self.use_lengths.setChecked(True)
        self.align_tips = QCheckBox("Alinhar pontas no anel externo")
        self.align_tips.setChecked(True)
        self.align_tips.setToolTip(
            "Circular: todas as folhas terminam no mesmo raio; a diferença até o anel\n"
            "é ligada por uma linha pontilhada cinza. Desmarque para ver o desenho original."
        )
        self._align_tip = self.align_tips.toolTip()
        self.layout_cb.currentIndexChanged.connect(self._sync_layout_options)
        # leque
        self.fan_angle = QSpinBox()
        self.fan_angle.setRange(30, 350)
        self.fan_angle.setValue(180)
        self.fan_angle.setSuffix("°")
        self.fan_angle.setToolTip("Ângulo total do leque")
        self.fan_start = QSpinBox()
        self.fan_start.setRange(0, 359)
        self.fan_start.setWrapping(True)
        self.fan_start.setSuffix("°")
        self.fan_start.setToolTip("Direção da primeira folha (0° = direita, sentido horário)")
        # não enraizada
        self.rotation = QSpinBox()
        self.rotation.setRange(0, 359)
        self.rotation.setWrapping(True)
        self.rotation.setSuffix("°")
        self.mirror = QCheckBox("Espelhar")
        self.daylight = QCheckBox("Refinar (daylight)")
        self.daylight.setToolTip("Gira as subárvores para igualar os vãos entre elas (mais lento em árvores grandes)")
        self.branch_scale = QSpinBox()
        self.branch_scale.setRange(10, 1000)
        self.branch_scale.setSuffix(" %")
        self.branch_scale.setValue(100)
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(1.0, 5.0)
        self.spacing.setSingleStep(0.1)
        self.spacing.setValue(1.6)
        self._sync_layout_options()

        form = QFormLayout()
        form.addRow("Layout:", self.layout_cb)
        fan_row = QHBoxLayout()
        fan_row.addWidget(QLabel("ângulo"))
        fan_row.addWidget(self.fan_angle)
        fan_row.addWidget(QLabel("início"))
        fan_row.addWidget(self.fan_start)
        self.fan_box = QWidget()
        self.fan_box.setLayout(fan_row)
        fan_row.setContentsMargins(0, 0, 0, 0)
        form.addRow("Leque:", self.fan_box)
        ur_row = QHBoxLayout()
        ur_row.setContentsMargins(0, 0, 0, 0)
        ur_row.addWidget(QLabel("girar"))
        ur_row.addWidget(self.rotation)
        ur_row.addWidget(self.mirror)
        ur_row.addWidget(self.daylight)
        self.ur_box = QWidget()
        self.ur_box.setLayout(ur_row)
        form.addRow("Não enraizada:", self.ur_box)
        form.addRow(self.use_lengths)
        form.addRow(self.align_tips)
        self._sync_layout_options()
        form.addRow("Escala dos ramos:", self.branch_scale)
        form.addRow("Espaço entre folhas:", self.spacing)

        exp = QGroupBox("Exportar")
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 1200)
        self.dpi.setValue(300)
        self.dpi.setSuffix(" dpi")
        self.tiff_dpi = QSpinBox()
        self.tiff_dpi.setRange(72, 2400)
        self.tiff_dpi.setValue(600)
        self.tiff_dpi.setSuffix(" dpi")
        self.tiff_lzw = QCheckBox("Compressão LZW")
        self.tiff_lzw.setChecked(True)
        row = QHBoxLayout()
        for fmt in ("svg", "pdf", "png", "tiff"):
            b = QPushButton(fmt.upper())
            b.clicked.connect(lambda _=False, f=fmt: self.export_requested.emit(f))
            row.addWidget(b)
        el = QFormLayout(exp)
        el.addRow(row)
        el.addRow("Resolução PNG:", self.dpi)
        trow = QHBoxLayout()
        trow.addWidget(self.tiff_dpi, 1)
        trow.addWidget(self.tiff_lzw)
        el.addRow("TIFF:", trow)

        lay = QVBoxLayout(self)
        lay.addWidget(self.gen_btn)
        lay.addLayout(form)
        hint = QLabel("Cores, clados, ramos, rótulos, símbolos, suporte e barra de escala ficam no painel "
                      "<b>Estilo</b>, à direita (atualizam na hora).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        lay.addWidget(hint)
        lay.addWidget(exp)
        lay.addStretch(1)

    def _sync_layout_options(self) -> None:
        kind = LayoutKind(self.layout_cb.currentData())
        self.align_tips.setEnabled(kind.is_radial)
        self.align_tips.setToolTip(self._align_tip if kind.is_radial else "Só nos layouts circular e leque.")
        if not hasattr(self, "fan_box"):          # ainda montando a aba
            return
        self.fan_box.setEnabled(kind == LayoutKind.FAN)
        self.fan_box.setToolTip("" if kind == LayoutKind.FAN else "Escolha o layout Leque.")
        self.ur_box.setEnabled(kind == LayoutKind.UNROOTED)
        self.ur_box.setToolTip("" if kind == LayoutKind.UNROOTED else "Escolha o layout Não enraizada.")

    def load_style(self, style: RenderStyle) -> None:
        self.layout_cb.setCurrentIndex(max(self.layout_cb.findData(style.layout), 0))
        self.use_lengths.setChecked(style.use_lengths)
        self.align_tips.setChecked(style.align_tips)
        self.branch_scale.setValue(round(style.branch_scale * 100))
        self.spacing.setValue(style.leaf_spacing)
        self.fan_angle.setValue(round(min(max(style.fan.angle, 30), 350)))
        self.fan_start.setValue(round(style.fan.start) % 360)
        self.rotation.setValue(round(style.unrooted.rotation) % 360)
        self.mirror.setChecked(style.unrooted.mirror)
        self.daylight.setChecked(style.unrooted.daylight)
        self._sync_layout_options()

    def render_style(self) -> RenderStyle:
        return RenderStyle(
            layout=LayoutKind(self.layout_cb.currentData()),  # o Qt devolve str puro
            branch_scale=self.branch_scale.value() / 100,
            leaf_spacing=self.spacing.value(),
            use_lengths=self.use_lengths.isChecked(),
            align_tips=self.align_tips.isChecked(),
            fan=FanStyle(float(self.fan_angle.value()), float(self.fan_start.value())),
            unrooted=UnrootedStyle(float(self.rotation.value()), self.mirror.isChecked(), self.daylight.isChecked()),
        )
