"""Arquivo de log de erros (rotativo), na pasta padrão de dados locais do sistema.

macOS: ``~/Library/Application Support/Jabuti/Jabuti/logs/jabuti.log``; Linux:
``~/.local/share/Jabuti/Jabuti/logs``; Windows: ``%LOCALAPPDATA%\\Jabuti\\Jabuti\\logs``.
``JABUTI_CONFIG_DIR`` sobrepõe (testes): o log vai para ``<dir>/logs``.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER = "jabuti"
_handler: RotatingFileHandler | None = None


def log_dir() -> Path:
    override = os.environ.get("JABUTI_CONFIG_DIR")
    if override:
        return Path(override) / "logs"
    from PySide6.QtCore import QStandardPaths

    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    return Path(base or Path.home() / ".jabuti") / "logs"


def log_path() -> Path:
    return log_dir() / "jabuti.log"


def setup_logging() -> Path | None:
    """Liga o arquivo de log (idempotente). Sem permissão de escrita, segue sem log em arquivo."""
    global _handler
    logger = logging.getLogger(LOGGER)
    logger.setLevel(logging.INFO)
    path = log_path()
    if _handler is not None and Path(_handler.baseFilename) == path:
        return path
    if _handler is not None:
        logger.removeHandler(_handler)
        _handler.close()
        _handler = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    except OSError:
        return None
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    return path


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER}.{name}" if name else LOGGER)
