"""Preferências do usuário: pasta de configuração, última pasta por tipo de arquivo e recentes.

Tudo fica na pasta padrão do sistema (``QStandardPaths.AppDataLocation``, ex.:
``~/Library/Application Support/Jabuti/Jabuti`` no macOS); ``JABUTI_CONFIG_DIR`` sobrepõe (testes).
Os diálogos de arquivo passam por ``open_file``/``open_files``/``save_file``/``pick_dir`` para
abrir na última pasta usada para aquele tipo de arquivo.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtWidgets import QFileDialog, QWidget

MAX_RECENT = 10


def config_dir() -> Path:
    base = os.environ.get("JABUTI_CONFIG_DIR") or QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base or Path.home() / ".jabuti")


def settings() -> QSettings:
    """Arquivo INI na pasta de configuração (legível e fácil de apagar)."""
    return QSettings(str(config_dir() / "jabuti.ini"), QSettings.Format.IniFormat)


# ------------------------------------------------------------------ última pasta
def last_dir(kind: str) -> str:
    d = settings().value(f"dirs/{kind}", "", str) or settings().value("dirs/_any", "", str)
    return d if d and Path(d).is_dir() else ""


def remember_dir(kind: str, path: str | Path) -> None:
    p = Path(path)
    d = p if p.is_dir() else p.parent
    s = settings()
    s.setValue(f"dirs/{kind}", str(d))
    s.setValue("dirs/_any", str(d))


def _start(kind: str, name: str = "") -> str:
    d = last_dir(kind)
    return str(Path(d) / name) if d and name else (d or name)


def open_file(parent: QWidget | None, title: str, kind: str, filters: str) -> str:
    path, _ = QFileDialog.getOpenFileName(parent, title, _start(kind), filters)
    if path:
        remember_dir(kind, path)
    return path


def open_files(parent: QWidget | None, title: str, kind: str, filters: str) -> list[str]:
    paths, _ = QFileDialog.getOpenFileNames(parent, title, _start(kind), filters)
    if paths:
        remember_dir(kind, paths[0])
    return list(paths)


def save_file(parent: QWidget | None, title: str, kind: str, name: str, filters: str) -> str:
    path, _ = QFileDialog.getSaveFileName(parent, title, _start(kind, name), filters)
    if path:
        remember_dir(kind, path)
    return path


def pick_dir(parent: QWidget | None, title: str, kind: str) -> str:
    path = QFileDialog.getExistingDirectory(parent, title, _start(kind))
    if path:
        settings().setValue(f"dirs/{kind}", path)
    return path


# ------------------------------------------------------------------ recentes
def recent_files(kind: str = "files") -> list[str]:
    """Arquivos abertos recentemente (mais novo primeiro). ``kind``: "files" (todos: o menu
    Abrir recentes), "trees" ou "projects". Os que sumiram do disco saem da lista."""
    key = f"recent/{kind}"
    st = settings()
    if kind == "files" and not st.contains(key):       # configuração antiga: junta as duas listas
        merged: list[str] = []
        for sub in ("trees", "projects"):
            raw = st.value(f"recent/{sub}", [], list) or []
            merged += [p for p in ([raw] if isinstance(raw, str) else raw) if p and p not in merged]
        st.setValue(key, merged[:MAX_RECENT])
    raw = st.value(key, [], list) or []
    if isinstance(raw, str):
        raw = [raw]
    alive = [p for p in raw if p and Path(p).is_file()]
    if alive != raw:
        st.setValue(key, alive)
    return alive


def add_recent(path: str | Path, kind: str = "trees") -> list[str]:
    """Registra no tipo (``trees``/``projects``) e na lista geral do menu."""
    p = str(Path(path).resolve())
    for k in dict.fromkeys((kind, "files")):
        items = [p, *[x for x in recent_files(k) if x != p]][:MAX_RECENT]
        settings().setValue(f"recent/{k}", items)
    return recent_files(kind)


def clear_recent(kind: str = "files") -> None:
    """Limpa uma lista; ``files`` (o menu) limpa todas."""
    for k in (("files", "trees", "projects") if kind == "files" else (kind,)):
        settings().setValue(f"recent/{k}", [])
