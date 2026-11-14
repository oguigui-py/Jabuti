"""Amostras de cor clicáveis (sem janelas soltas)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QGridLayout,
    QHBoxLayout,
    QMenu,
    QToolButton,
    QWidget,
    QWidgetAction,
)

BASE_COLORS: dict[str, str] = {
    "Preto": "#202020",
    "Cinza": "#6b6b6b",
    "Cinza claro": "#8a8a8a",
    "Azul": "#1f4e79",
    "Vermelho": "#b22222",
    "Verde": "#2e7d32",
    "Roxo": "#5e3c99",
}


def swatch_css(color: str, checked_border: bool = True) -> str:
    css = f"QToolButton {{ background: {color}; border: 1px solid #999; border-radius: 3px; }}"
    if checked_border:
        css += "QToolButton:checked { border: 3px solid #f0a000; }"
    return css


def swatch_button(color: str, tooltip: str = "", size: int = 22, checkable: bool = True) -> QToolButton:
    b = QToolButton()
    b.setCheckable(checkable)
    b.setToolTip(tooltip or color)
    b.setFixedSize(QSize(size, size))
    b.setStyleSheet(swatch_css(color, checkable))
    return b


class SwatchStrip(QWidget):
    """Faixa de quadradinhos de cor (pré-visualização da paleta)."""

    def __init__(self, colors: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.setFixedHeight(12)
        self.setMinimumWidth(6 * len(colors))

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        p = QPainter(self)
        w = self.width() / max(len(self.colors), 1)
        for i, c in enumerate(self.colors):
            p.fillRect(int(i * w), 0, int(w + 1), self.height(), QColor(c))


class SwatchRow(QWidget):
    """Linha de amostras exclusivas; ``color_changed`` ao escolher."""

    color_changed = Signal(str)

    def __init__(self, colors: dict[str, str] | None = None, selected: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        colors = colors or BASE_COLORS
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QToolButton] = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        for name, color in colors.items():
            b = swatch_button(color, name)
            self.group.addButton(b)
            self.buttons[color] = b
            lay.addWidget(b)
        lay.addStretch(1)
        self.set_color(selected or next(iter(colors.values())))
        self.group.buttonToggled.connect(self._on_toggle)

    def _on_toggle(self, _b, on: bool) -> None:  # type: ignore[no-untyped-def]
        if on:
            self.color_changed.emit(self.color())

    def color(self) -> str:
        return next((c for c, b in self.buttons.items() if b.isChecked()), next(iter(self.buttons)))

    def set_color(self, color: str) -> None:
        """Seleciona a amostra; cor fora da lista (ex.: vinda de um preset) vira amostra extra."""
        color = color.lower()
        b = self.buttons.get(color)
        if b is None:
            b = swatch_button(color, f"Personalizada ({color})")
            self.group.addButton(b)
            self.buttons[color] = b
            lay = self.layout()
            lay.insertWidget(lay.count() - 1, b)  # antes do stretch
        b.setChecked(True)


def color_menu(parent: QWidget, palette: list[str], on_pick, allow_auto: bool = True) -> QMenu:  # type: ignore[no-untyped-def]
    """Menu contextual com amostras (paleta + cores base); ``on_pick(cor | None)``.

    ``None`` = voltar à cor automática da paleta.
    """
    menu = QMenu(parent)
    grid_w = QWidget()
    grid = QGridLayout(grid_w)
    grid.setContentsMargins(6, 6, 6, 6)
    grid.setSpacing(3)
    colors = list(dict.fromkeys([*palette, *BASE_COLORS.values()]))
    for i, c in enumerate(colors):
        b = swatch_button(c, c, 20, checkable=False)
        b.clicked.connect(lambda _=False, col=c: (on_pick(col), menu.close()))
        grid.addWidget(b, i // 8, i % 8)
    act = QWidgetAction(menu)
    act.setDefaultWidget(grid_w)
    menu.addAction(act)
    menu.addSeparator()
    if allow_auto:
        menu.addAction("Cor automática (paleta)", lambda: on_pick(None))

    def other() -> None:
        c = QColorDialog.getColor(parent=parent)
        if c.isValid():
            on_pick(c.name())

    menu.addAction("Outra cor…", other)
    return menu
