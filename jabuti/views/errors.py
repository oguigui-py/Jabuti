"""Diálogos de erro: nunca derrubam o app."""

from __future__ import annotations

import sys
import traceback

from PySide6.QtWidgets import QMessageBox, QWidget

from jabuti.parsers.errors import JabutiParseError


def show_error(parent: QWidget | None, exc: BaseException, title: str = "Erro") -> None:
    if isinstance(exc, JabutiParseError):
        text = exc.user_message()
    else:
        text = str(exc) or exc.__class__.__name__
    box = QMessageBox(QMessageBox.Icon.Warning, title, text, parent=parent)
    if not isinstance(exc, JabutiParseError):
        box.setDetailedText("".join(traceback.format_exception(exc)))
    box.exec()


def install_excepthook() -> None:
    """Exceções não tratadas viram diálogo em vez de fechar o app."""

    def hook(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        traceback.print_exception(exc_type, exc, tb)
        try:
            show_error(None, exc, "Erro inesperado")
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = hook
