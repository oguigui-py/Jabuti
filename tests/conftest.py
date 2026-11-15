from pathlib import Path

import os

import pytest

# a abertura animada só atrasaria os testes
os.environ.setdefault("JABUTI_NO_SPLASH", "1")

DATA = Path(__file__).parent / "data"


@pytest.fixture
def data_dir() -> Path:
    return DATA


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Nunca ler/gravar o "meu padrão" real do usuário durante os testes."""
    cfg = tmp_path / "config"
    monkeypatch.setenv("JABUTI_CONFIG_DIR", str(cfg))
    return cfg


@pytest.fixture(autouse=True)
def stop_gff_threads(request):
    """Garante que nenhuma thread de leitura sobreviva ao teste."""
    yield
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    from jabuti.views.figure_panel import FigurePanel
    from jabuti.views.gff_tab import GffTab

    for w in app.allWidgets():
        if isinstance(w, (GffTab, FigurePanel)):
            w.shutdown()


@pytest.fixture(autouse=True)
def flush_deleted_widgets():
    """Destrói de fato as janelas fechadas no teste anterior (deleteLater + coleta de lixo).

    Sem isso, janelas de testes anteriores se acumulam e o teste que mede pausas do laço
    de eventos durante a leitura em segundo plano (test_async_loading) falha conforme a
    ordem dos testes."""
    yield
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        if not w.isVisible():
            w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
