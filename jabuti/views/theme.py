"""Cores da interface derivadas da paleta do sistema (claro/escuro), em vez de cinzas fixos.

A figura em si (cena) tem fundo próprio (branco por padrão) e não segue o tema.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def _palette() -> QPalette:
    app = QApplication.instance()
    return app.palette() if app is not None else QPalette()  # type: ignore[union-attr]


def is_dark() -> bool:
    return _palette().color(QPalette.ColorRole.Window).lightness() < 110


def muted_color() -> str:
    """Texto secundário (dicas): mistura texto/fundo, legível nos dois temas."""
    p = _palette()
    fg, bg = p.color(QPalette.ColorRole.WindowText), p.color(QPalette.ColorRole.Window)
    t = 0.6
    c = QColor(round(fg.red() * t + bg.red() * (1 - t)), round(fg.green() * t + bg.green() * (1 - t)),
               round(fg.blue() * t + bg.blue() * (1 - t)))
    return c.name()


def error_color() -> str:
    return "#ff7b72" if is_dark() else "#b22222"


def muted_css() -> str:
    return f"color: {muted_color()};"
