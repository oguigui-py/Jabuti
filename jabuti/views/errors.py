"""Diálogos de erro: nunca derrubam o app.

Mensagem curta (com arquivo:linha quando é erro de leitura); o traceback fica em
"Mostrar detalhes…" e vai sempre para o arquivo de log (``jabuti.logs``).
"""

from __future__ import annotations

import sys
import threading
import traceback

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from jabuti.logs import get_logger, log_path
from jabuti.parsers.errors import JabutiParseError

_log = get_logger("errors")


def error_text(exc: BaseException) -> str:
    if isinstance(exc, JabutiParseError):
        return exc.user_message()
    if isinstance(exc, FileNotFoundError):
        return f"Arquivo não encontrado: {exc.filename or exc}"
    if isinstance(exc, PermissionError):
        return f"Sem permissão para acessar: {exc.filename or exc}"
    if isinstance(exc, UnicodeDecodeError):
        return "O arquivo não está em texto UTF-8 (ou é binário). Salve-o como texto UTF-8 e tente de novo."
    if isinstance(exc, MemoryError):
        return "Memória insuficiente para esta operação."
    return str(exc) or exc.__class__.__name__


def show_error(parent: QWidget | None, exc: BaseException, title: str = "Erro") -> None:
    if isinstance(exc, JabutiParseError):
        _log.warning("%s: %s", title, exc.user_message())
    else:
        _log.error("%s: %s", title, exc, exc_info=(type(exc), exc, exc.__traceback__))
    app = QApplication.instance()
    if app is None or QThread.currentThread() is not app.thread():
        return                         # fora da thread da GUI: só o log
    box = QMessageBox(QMessageBox.Icon.Warning, title, error_text(exc), parent=parent)
    if not isinstance(exc, JabutiParseError):
        box.setInformativeText(f"Os detalhes técnicos estão em “Mostrar detalhes…” e no log:\n{log_path()}")
        box.setDetailedText("".join(traceback.format_exception(exc)))
    box.exec()


def install_excepthook() -> None:
    """Exceções não tratadas viram diálogo (e entrada no log) em vez de fechar o app."""

    def hook(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        traceback.print_exception(exc_type, exc, tb)
        try:
            if exc.__traceback__ is None:
                exc = exc.with_traceback(tb)
            show_error(None, exc, "Erro inesperado")
        except Exception:  # noqa: BLE001
            pass

    def thread_hook(args) -> None:  # type: ignore[no-untyped-def]
        if args.exc_value is not None:
            _log.error("Erro numa thread (%s)", getattr(args.thread, "name", "?"),
                       exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = hook
    threading.excepthook = thread_hook
