"""Painel fixo de cores: paleta, cor de ramos/rótulos, coluna de metadados e legenda.

Tudo é escolhido por amostras clicáveis sempre visíveis (sem popups/janelas soltas).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from jabuti.style import PALETTES, RenderStyle

BASE_COLORS: dict[str, str] = {
    "Preto": "#202020",
    "Cinza": "#6b6b6b",
    "Azul": "#1f4e79",
    "Vermelho": "#b22222",
    "Verde": "#2e7d32",
    "Roxo": "#5e3c99",
}


class SwatchStrip(QWidget):
    """Faixa de quadradinhos de cor (pré-visualização da paleta)."""

    def __init__(self, colors: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setFixedHeight(14)
        self.setMinimumWidth(12 * len(colors))

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        p = QPainter(self)
        w = self.width() / max(len(self.colors), 1)
        for i, c in enumerate(self.colors):
            p.fillRect(int(i * w), 0, int(w + 1), self.height(), QColor(c))


def _swatch_button(color: str, tooltip: str) -> QToolButton:
    b = QToolButton()
    b.setCheckable(True)
    b.setToolTip(tooltip)
    b.setFixedSize(QSize(24, 24))
    b.setStyleSheet(
        f"QToolButton {{ background: {color}; border: 1px solid #999; border-radius: 3px; }}"
        "QToolButton:checked { border: 3px solid #f0a000; }"
    )
    return b


class LegendWidget(QFrame):
    """Legenda: quadrado de cor + rótulo, por categoria."""

    EMPTY_TEXT = "A legenda aparece quando uma coluna de metadados for escolhida para colorir."

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(2)
        self.set_entries([])

    def set_entries(self, entries: list[tuple[str, str]]) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not entries:
            lbl = QLabel(self.EMPTY_TEXT)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #888;")
            self._lay.addWidget(lbl)
            self.entries = []
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
        self.entries = list(entries)


class ColorPanel(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # --- paleta (lista de opções sempre visível)
        pal_box = QGroupBox("Paleta")
        pal_lay = QGridLayout(pal_box)
        self.palette_group = QButtonGroup(self)
        self.palette_buttons: dict[str, QRadioButton] = {}
        for row, (name, colors) in enumerate(PALETTES.items()):
            rb = QRadioButton(name)
            self.palette_group.addButton(rb)
            self.palette_buttons[name] = rb
            pal_lay.addWidget(rb, 2 * row, 0)
            pal_lay.addWidget(SwatchStrip(colors), 2 * row + 1, 0)
        next(iter(self.palette_buttons.values())).setChecked(True)
        self.palette_group.buttonToggled.connect(lambda _b, on: on and self.changed.emit())

        # --- cores base
        base_box = QGroupBox("Cores da árvore")
        base_lay = QGridLayout(base_box)
        self.branch_group, self.branch_buttons = self._swatch_row(base_lay, 0, "Ramos:")
        self.label_group, self.label_buttons = self._swatch_row(base_lay, 1, "Rótulos:")

        # --- metadados
        meta_box = QGroupBox("Colorir por metadado")
        meta_lay = QVBoxLayout(meta_box)
        self.color_by = QComboBox()
        self.set_metadata_columns([])
        self.color_by.currentIndexChanged.connect(lambda _i: self.changed.emit())
        meta_lay.addWidget(self.color_by)
        meta_lay.addWidget(QLabel("<b>Legenda</b>"))
        self.legend = LegendWidget()
        meta_lay.addWidget(self.legend)

        lay = QVBoxLayout(self)
        lay.addWidget(pal_box)
        lay.addWidget(base_box)
        lay.addWidget(meta_box)
        lay.addStretch(1)

    def _swatch_row(self, grid: QGridLayout, row: int, title: str) -> tuple[QButtonGroup, dict[str, QToolButton]]:
        grid.addWidget(QLabel(title), row, 0)
        group = QButtonGroup(self)
        group.setExclusive(True)
        buttons: dict[str, QToolButton] = {}
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(3)
        for name, color in BASE_COLORS.items():
            b = _swatch_button(color, name)
            group.addButton(b)
            buttons[color] = b
            hl.addWidget(b)
        hl.addStretch(1)
        next(iter(buttons.values())).setChecked(True)
        group.buttonToggled.connect(lambda _b, on: on and self.changed.emit())
        grid.addWidget(holder, row, 1)
        return group, buttons

    # ---------------------------------------------------------------- API
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

    def set_legend(self, entries: list[tuple[str, str]]) -> None:
        self.legend.set_entries(entries)

    def palette_name(self) -> str:
        return next(n for n, b in self.palette_buttons.items() if b.isChecked())

    def branch_color(self) -> str:
        return next(c for c, b in self.branch_buttons.items() if b.isChecked())

    def label_color(self) -> str:
        return next(c for c, b in self.label_buttons.items() if b.isChecked())

    def apply_to(self, style: RenderStyle) -> RenderStyle:
        style.palette = self.palette_name()
        style.branch_color = self.branch_color()
        style.label_color = self.label_color()
        style.color_by = self.color_by.currentData()
        return style
