"""Bloco 3: linha de comando, configurações e recentes, log, menus/atalhos, erros e estados vazios."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from jabuti import __version__  # noqa: E402

TREE = "examples/paraburkholderia_40.treefile"
ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ linha de comando
def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "jabuti", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
                          timeout=60)


def test_cli_version_and_help():
    v = _run("--version")
    assert v.returncode == 0 and v.stdout.strip() == f"Jabuti {__version__}"
    h = _run("--help")
    assert h.returncode == 0
    for needle in ("uso: jabuti", "ÁRVORE", "--itol", "--no-splash", "mostra a versão",
                   "Produzido pelo Laboratório de Genômica Eco-evolutiva Microbiana", "Desenvolvido por Guilherme Gonçalves"):
        assert needle in h.stdout, needle
    bad = _run("--nao-existe")
    assert bad.returncode == 2 and "uso: jabuti" in bad.stderr


def test_cli_version_does_not_load_qt():
    code = ("import sys\nfrom jabuti.cli import main\ntry:\n    main(['--version'])\nexcept SystemExit:\n    pass\n"
            "print('QT' if any(m.startswith('PySide6') for m in sys.modules) else 'SEM-QT')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT, timeout=60)
    assert out.stdout.strip().endswith("SEM-QT")


def test_cli_parses_tree_and_itol(monkeypatch):
    import jabuti.app as app
    from jabuti.cli import main

    got = {}
    monkeypatch.setattr(app, "run", lambda tree, itol, splash=True: got.update(tree=tree, itol=itol, splash=splash) or 0)
    assert main([TREE, "--itol", "a.txt", "b.txt", "--no-splash"]) == 0
    assert got == {"tree": TREE, "itol": ["a.txt", "b.txt"], "splash": False}


def test_launcher_opens_tree_and_itol(qtbot):
    from jabuti.app import Launcher

    launcher = Launcher(["jabuti", TREE], use_splash=False, itol=["examples/itol/colorstrip.txt"])
    launcher.start()
    win = launcher.window
    qtbot.addWidget(win)
    assert win.tree is not None
    qtbot.waitUntil(lambda: not win.figure_panel.itol.is_loading(), timeout=5000)
    assert len(win.figure_panel.itol.entries) == 1


# ------------------------------------------------------------------ configurações e recentes
def test_settings_dirs_and_recent(tmp_path, isolated_config):
    from jabuti import settings

    assert settings.config_dir() == isolated_config
    assert settings.last_dir("tree") == ""
    f = tmp_path / "a" / "x.nwk"
    f.parent.mkdir()
    f.write_text("(a,b);", encoding="utf-8")
    settings.remember_dir("tree", f)
    assert settings.last_dir("tree") == str(f.parent)
    assert settings.last_dir("gff") == str(f.parent)          # sem pasta própria: a última usada
    files = []
    for i in range(12):
        p = tmp_path / f"t{i}.nwk"
        p.write_text("(a,b);", encoding="utf-8")
        files.append(p)
        settings.add_recent(p)
    rec = settings.recent_files()
    assert len(rec) == settings.MAX_RECENT and rec[0] == str(files[-1].resolve())
    settings.add_recent(files[5])                              # reabrir sobe para o topo, sem duplicar
    rec = settings.recent_files()
    assert rec[0] == str(files[5].resolve()) and len(set(rec)) == len(rec)
    files[5].unlink()                                          # sumiu do disco: sai da lista
    assert str(files[5].resolve()) not in settings.recent_files()
    settings.clear_recent()
    assert settings.recent_files() == []
    assert (isolated_config / "jabuti.ini").is_file()


def test_dialog_helpers_start_in_last_dir(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from jabuti import settings

    seen = []
    target = tmp_path / "pasta" / "arvore.nwk"
    target.parent.mkdir()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda p, t, start, f: seen.append(start) or (str(target), ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda p, t, start, f: seen.append(start) or ("", ""))
    assert settings.open_file(None, "Abrir", "tree", "*") == str(target)
    assert settings.save_file(None, "Salvar", "tree", "fig.svg", "*") == ""
    assert seen == ["", str(target.parent / "fig.svg")]


@pytest.fixture
def window(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    shown = []
    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    win = MainWindow()
    win.shown = shown
    qtbot.addWidget(win)
    return win


def test_open_adds_recent_and_menu_reopens(window, tmp_path):
    from jabuti import settings

    copy = tmp_path / "minha.treefile"
    copy.write_text(Path(TREE).read_text(encoding="utf-8"), encoding="utf-8")
    assert window.open_tree(copy)
    assert settings.recent_files()[0] == str(copy.resolve())
    window._fill_recent_menu()
    texts = [a.text() for a in window.recent_menu.actions()]
    assert "minha.treefile" in texts and "Limpar lista" in texts
    window.tree = None
    next(a for a in window.recent_menu.actions() if a.text() == "minha.treefile").trigger()
    assert window.tree is not None and window.tree_tab.path == copy
    next(a for a in window.recent_menu.actions() if a.text() == "Limpar lista").trigger()
    assert settings.recent_files() == []
    assert any(a.text() == "(nenhum arquivo recente)" for a in window.recent_menu.actions())


# ------------------------------------------------------------------ menus e atalhos
def test_menus_and_standard_shortcuts(window):
    from PySide6.QtGui import QAction, QKeySequence

    titles = [a.text().replace("&", "") for a in window.menuBar().actions()]
    assert titles == ["Arquivo", "Editar", "Exibir", "Ajuda"]
    act = window.actions_by_name
    SK = QKeySequence.StandardKey
    for name, key in (("open", SK.Open), ("quit", SK.Quit), ("find", SK.Find), ("zoom_in", SK.ZoomIn),
                      ("zoom_out", SK.ZoomOut)):
        assert act[name].shortcut() == QKeySequence(key), name
    assert act["fit"].shortcut() == QKeySequence("Ctrl+0")
    assert act["import_itol"].shortcut() == QKeySequence("Ctrl+Shift+I")
    assert not act["redraw"].shortcut().isEmpty()
    assert act["quit"].menuRole() == QAction.MenuRole.QuitRole
    assert act["about"].menuRole() == QAction.MenuRole.AboutRole
    shortcuts = [a.shortcut().toString() for a in act.values() if not a.shortcut().isEmpty()]
    assert len(shortcuts) == len(set(shortcuts)), "atalho repetido"
    for name in ("export_svg", "export_pdf", "export_png", "export_tiff", "export_itol", "import_meta", "import_gff"):
        assert name in act


def test_view_menu_zoom_fit_and_figure_toggle(window):
    window.open_tree(TREE)
    before = window.canvas.transform().m11()
    window.actions_by_name["zoom_in"].trigger()
    assert window.canvas.transform().m11() > before
    window.actions_by_name["fit"].trigger()
    was = window.figure_holder.collapsed
    window.actions_by_name["toggle_figure"].trigger()
    assert window.figure_holder.collapsed is not was


def test_about_text_and_readme(window, monkeypatch):
    from PySide6.QtGui import QDesktopServices

    text = window.about_text()
    for needle in (f"Jabuti {__version__}", "Produzido pelo Laboratório de Genômica Eco-evolutiva Microbiana",
                   "Desenvolvido por Guilherme Gonçalves", "README", "jabuti.log"):
        assert needle in text
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    assert window.open_readme()
    assert opened[0].endswith("README.md") or "github.com" in opened[0]


# ------------------------------------------------------------------ log e erros
def test_errors_are_logged_and_never_close(window, isolated_config, monkeypatch):
    from jabuti.logs import log_path, setup_logging
    from jabuti.views.errors import show_error

    assert setup_logging() == isolated_config / "logs" / "jabuti.log"
    try:
        raise ValueError("falha de teste 123")
    except ValueError as exc:
        show_error(window, exc, "Teste")
    assert window.shown[-1] == "falha de teste 123"
    text = log_path().read_text(encoding="utf-8")
    assert "falha de teste 123" in text and "Traceback" in text
    # erro durante o desenho: diálogo + log, a janela continua de pé
    window.open_tree(TREE)
    monkeypatch.setattr(window.renderer, "render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quebrou")))
    window.generate()
    assert window.shown[-1] == "quebrou" and window.isEnabled()
    assert "quebrou" in log_path().read_text(encoding="utf-8")


def test_excepthook_logs_and_survives(window, isolated_config):
    from jabuti.logs import log_path, setup_logging
    from jabuti.views.errors import install_excepthook

    setup_logging()
    old, old_thread = sys.excepthook, __import__("threading").excepthook
    try:
        install_excepthook()
        try:
            raise KeyError("sem-chave")
        except KeyError:
            sys.excepthook(*sys.exc_info())
        assert "sem-chave" in log_path().read_text(encoding="utf-8")
    finally:
        sys.excepthook = old
        __import__("threading").excepthook = old_thread


def test_error_text_is_short_and_clear():
    from jabuti.views.errors import error_text

    assert error_text(FileNotFoundError(2, "No such file", "/x/arvore.nwk")) == "Arquivo não encontrado: /x/arvore.nwk"
    assert "UTF-8" in error_text(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"))
    assert error_text(RuntimeError()) == "RuntimeError"


def test_bad_tree_file_does_not_close(window, tmp_path):
    bad = tmp_path / "ruim.nwk"
    bad.write_bytes(b"\x00\xff((((")
    assert window.open_tree(bad) is False
    assert window.shown and window.tree is None


# ------------------------------------------------------------------ estados vazios, dicas e janela
def test_empty_canvas_message_only_on_screen(window, tmp_path):
    from jabuti.views.export import export_svg

    assert window.canvas.is_empty()
    window.resize(1200, 800)
    window.show()
    window.canvas.viewport().grab()                       # desenha a mensagem sem erro
    window.open_tree(TREE)
    assert not window.canvas.is_empty()
    export_svg(window.canvas.tree_scene, tmp_path / "f.svg")
    assert "Nenhuma árvore" not in (tmp_path / "f.svg").read_text(encoding="utf-8")


def test_tooltips_applied(window):
    tips = {b.text(): b.toolTip() for b in window.findChildren(__import__("PySide6.QtWidgets", fromlist=["x"]).QPushButton)}
    for text in ("Detectar", "Aplicar enraizamento", "Mapear automaticamente", "Importar…", "Exportar…"):
        assert tips.get(text), text
    assert window.search_box.toolTip()


def test_figure_panel_sections_fit_without_clipping(window):
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    if not QFontDatabase.families():
        pytest.skip("sem fontes no sistema: o Qt desenha caixas de 16 px por letra e nada cabe")

    window.resize(1500, 900)
    window.show()
    for sec in window.figure_panel.sections.values():
        sec.set_expanded(True)
        QApplication.processEvents()
        assert window.figure_panel.minimumSizeHint().width() <= window.figure_holder.scroll.viewport().width()


def test_window_background_is_opaque_off_mac(window):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() == "cocoa":
        pytest.skip("no macOS nativo o fundo unificado é pintado pelo sistema")
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
