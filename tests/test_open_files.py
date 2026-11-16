"""Abrir arquivos pelo sistema: tipos, QFileOpenEvent (macOS), arrastar, recentes, linha de comando.

Nada aqui abre janela real: plataforma offscreen e eventos entregues direto ao filtro."""

from __future__ import annotations

import os
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from jabuti.file_types import OPEN_WITH_SUFFIXES, classify, group  # noqa: E402

TREE = "examples/paraburkholderia_40.treefile"


@pytest.fixture
def files(tmp_path):  # type: ignore[no-untyped-def]
    d = tmp_path / "arquivos com acento ç"
    d.mkdir()
    newick = open(TREE, encoding="utf-8").read()
    out = {}
    for suf in (".nwk", ".newick", ".treefile", ".tree", ".tre"):
        out[suf] = d / f"árvore{suf}"
        out[suf].write_text(newick, encoding="utf-8")
    out["newick_txt"] = d / "arvore.txt"
    out["newick_txt"].write_text(newick, encoding="utf-8")
    out["meta"] = d / "metadados.tsv"
    shutil.copy("examples/metadata.tsv", out["meta"])
    out["itol"] = d / "faixa.txt"
    shutil.copy("examples/itol/colorstrip.txt", out["itol"])
    out["gff"] = d / "A00.gff3"
    shutil.copy("examples/gff/A00.gff3", out["gff"])
    out["gffgz"] = d / "A01.gff.gz"
    import gzip

    out["gffgz"].write_bytes(gzip.compress(open("examples/gff/A01.gff3", "rb").read()))
    out["unknown"] = d / "foto.png"
    out["unknown"].write_bytes(b"\x89PNG\r\n")
    return out


# ------------------------------------------------------------------ tipos
def test_classify_by_extension_and_content(files, tmp_path):
    for suf in (".nwk", ".newick", ".treefile", ".tree", ".tre"):
        assert classify(files[suf]) == "tree", suf
    assert classify(files["newick_txt"]) == "tree"
    assert classify(files["meta"]) == "metadata"
    assert classify(files["itol"]) == "itol"
    assert classify(files["gff"]) == "gff" and classify(files["gffgz"]) == "gff"
    assert classify(files["unknown"]) is None
    assert classify(tmp_path / "nao_existe.nwk") is None
    assert set(OPEN_WITH_SUFFIXES) == {".jabuti", ".nwk", ".newick", ".treefile", ".tree", ".tre"}
    g = group([files[".nwk"], files["meta"], files["unknown"]])
    assert set(g) == {"tree", "metadata", "unknown"}


@pytest.fixture
def win(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    w = MainWindow()
    qtbot.addWidget(w)
    return w


@pytest.fixture
def project_file(win, tmp_path):  # type: ignore[no-untyped-def]
    shutil.copy(TREE, tmp_path / "t.treefile")
    assert win.open_tree(tmp_path / "t.treefile")
    return win.project._write(tmp_path / "meu projeto é.jabuti")


def test_classify_project_and_bundle(win, project_file, tmp_path):
    from jabuti.project import read_project, write_bundle

    assert classify(project_file) == "project"
    data, _ = read_project(project_file)
    bundle = tmp_path / "pacote.zip"
    write_bundle(bundle, data, project_file.parent, "pacote")
    assert classify(bundle) == "project"
    plain = tmp_path / "outro.zip"
    import zipfile

    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("leia.txt", "oi")
    assert classify(plain) is None


# ------------------------------------------------------------------ arrastar
def _drop(w, paths):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    ev = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier)
    w.dropEvent(ev)


def test_drop_each_kind(win, files, qtbot):
    _drop(win, [files[".tre"]])
    assert win.tree is not None and win.tree_tab.path.name == "árvore.tre"
    _drop(win, [files["meta"]])
    assert win.metadata_tab.table is not None
    _drop(win, [files["itol"]])
    qtbot.waitUntil(lambda: len(win.figure_panel.itol.entries) == 1, timeout=10000)
    _drop(win, [files["gff"], files["gffgz"]])
    qtbot.waitUntil(lambda: not win.gff_tab.is_loading() and len(win.gff_tab.genomes) == 2, timeout=10000)
    _drop(win, [files["unknown"]])
    assert "não reconhecido" in win.statusBar().currentMessage()


def test_drop_tree_and_itol_together(win, files, qtbot):
    _drop(win, [files["itol"], files[".nwk"]])
    assert win.tree is not None
    qtbot.waitUntil(lambda: len(win.figure_panel.itol.entries) == 1, timeout=10000)


def test_drop_project(win, project_file, qtbot):
    from jabuti.views.main_window import MainWindow

    other = MainWindow()
    qtbot.addWidget(other)
    _drop(other, [project_file])
    qtbot.waitUntil(lambda: other.project.path == project_file and not other.project.loading, timeout=10000)
    assert other.tree is not None


def test_replacing_asks_to_save_when_dirty(win, files, project_file, monkeypatch):
    sp = win.style_panel
    sp.ladder.setCurrentIndex(sp.ladder.findData("asc"))
    win.render_live()
    assert win.project.is_dirty()
    asked = []
    monkeypatch.setattr(win, "maybe_save", lambda: asked.append(1) or False)      # "Cancelar"
    before = win.tree_tab.path
    assert not win.open_paths([files[".nwk"]])
    assert asked and win.tree_tab.path == before
    assert not win.open_paths([project_file]) and len(asked) == 2
    monkeypatch.setattr(win, "maybe_save", lambda: True)                           # "Descartar"
    assert win.open_paths([files[".nwk"]]) and win.tree_tab.path.name == "árvore.nwk"


# ------------------------------------------------------------------ QFileOpenEvent (macOS)
def _file_open_event(path):  # type: ignore[no-untyped-def]
    from PySide6.QtGui import QFileOpenEvent

    return QFileOpenEvent(str(path))


def test_file_open_event_at_startup_is_queued(qtbot, files):
    from jabuti.app import FileOpenFilter, Launcher

    launcher = Launcher(["jabuti"], use_splash=False)
    filt = FileOpenFilter(launcher)
    assert filt.eventFilter(None, _file_open_event(files[".treefile"])) is True   # antes da janela
    assert launcher.paths == [str(files[".treefile"])]
    launcher.start()
    qtbot.addWidget(launcher.window)
    assert launcher.window.tree is not None and launcher.window.tree_tab.path.name == "árvore.treefile"
    assert launcher.paths == []


def test_file_open_event_with_app_running(qtbot, files, project_file, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from jabuti.app import FileOpenFilter, Launcher

    launcher = Launcher(["jabuti", str(files[".nwk"])], use_splash=False)
    launcher.start()
    w = launcher.window
    qtbot.addWidget(w)
    assert w.tree_tab.path.name == "árvore.nwk"
    filt = FileOpenFilter(launcher)
    app = QApplication.instance()
    app.installEventFilter(filt)
    try:
        QApplication.sendEvent(app, _file_open_event(project_file))               # duplo clique num .jabuti
        qtbot.waitUntil(lambda: w.project.path == project_file and not w.project.loading, timeout=10000)
        asked = []
        monkeypatch.setattr(w, "maybe_save", lambda: asked.append(1) or True)
        QApplication.sendEvent(app, _file_open_event(files[".tree"]))
        assert asked and w.tree_tab.path.name == "árvore.tree"
    finally:
        app.removeEventFilter(filt)


def test_other_events_pass_through():
    from PySide6.QtCore import QEvent

    from jabuti.app import FileOpenFilter, Launcher

    filt = FileOpenFilter(Launcher(["jabuti"], use_splash=False))
    assert filt.eventFilter(None, QEvent(QEvent.Type.KeyPress)) is False


# ------------------------------------------------------------------ recentes
def test_recent_menu_mixes_trees_and_projects(win, files, project_file):
    from jabuti import settings

    win.open_paths([files[".nwk"]], ask=False)
    assert settings.recent_files()[0].endswith("árvore.nwk")
    win.project.open(project_file, wait=True)
    rec = settings.recent_files()
    assert rec[0] == str(project_file.resolve()) and rec[1].endswith("árvore.nwk")
    win._fill_recent_menu()
    texts = [a.text() for a in win.recent_menu.actions()]
    assert win.recent_menu.title() == "Abrir recentes"
    assert texts[:2] == [project_file.name, "árvore.nwk"] and "Limpar lista" in texts
    next(a for a in win.recent_menu.actions() if a.text() == "árvore.nwk").trigger()
    assert win.tree_tab.path.name == "árvore.nwk"
    files[".nwk"].unlink()                                       # sumiu do disco: sai da lista
    win._fill_recent_menu()
    assert "árvore.nwk" not in [a.text() for a in win.recent_menu.actions()]
    next(a for a in win.recent_menu.actions() if a.text() == "Limpar lista").trigger()
    assert settings.recent_files() == settings.recent_files("trees") == settings.recent_files("projects") == []


def test_recent_limit_and_old_settings_migrate(tmp_path):
    from jabuti import settings

    paths = []
    for i in range(3):
        p = tmp_path / f"p{i}.jabuti"
        p.write_text("{}", encoding="utf-8")
        paths.append(str(p.resolve()))
    t = tmp_path / "t.nwk"
    t.write_text("(a,b);", encoding="utf-8")
    st = settings.settings()
    st.setValue("recent/trees", [str(t.resolve())])           # configuração de versões anteriores
    st.setValue("recent/projects", paths)
    st.remove("recent/files")
    assert settings.recent_files() == [str(t.resolve()), *paths]
    for i in range(15):
        p = tmp_path / f"a{i}.nwk"
        p.write_text("(a,b);", encoding="utf-8")
        settings.add_recent(p)
    assert len(settings.recent_files()) == settings.MAX_RECENT == 10
    assert settings.recent_files()[0].endswith("a14.nwk")


# ------------------------------------------------------------------ linha de comando
def test_cli_ignores_finder_psn_argument(monkeypatch):
    import jabuti.app
    from jabuti import cli

    seen = {}
    monkeypatch.setattr(jabuti.app, "run", lambda tree, itol, splash: seen.update(tree=tree) or 0)
    assert cli.main(["-psn_0_12345", "x.nwk", "--no-splash"]) == 0
    assert seen["tree"] == "x.nwk"
