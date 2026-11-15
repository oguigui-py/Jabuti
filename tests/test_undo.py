"""Desfazer/refazer: cada tipo de ação volta à cena idêntica, mescla, limite, projeto alterado."""

from __future__ import annotations

import os
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from scene_baseline import same, signature  # noqa: E402

TREE = "examples/paraburkholderia_40.treefile"
ROB = "Robbsia_andropogonis_LMG2129"


@pytest.fixture
def win(qtbot, monkeypatch, tmp_path):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    shutil.copy(TREE, tmp_path / "t.treefile")
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.open_tree(tmp_path / "t.treefile")
    w.tmp = tmp_path
    return w


def ladder(w, mode: str) -> None:  # type: ignore[no-untyped-def]
    sp = w.style_panel
    sp.ladder.setCurrentIndex(sp.ladder.findData(mode))


def sig(w):  # type: ignore[no-untyped-def]
    return signature(w.renderer.scene)


def check(w, action, label_part: str):  # type: ignore[no-untyped-def]
    """Faz a ação, confere o texto do menu, desfaz (cena idêntica à de antes) e refaz (idêntica à de depois)."""
    before = sig(w)
    n = w.undo.stack.count()
    action()
    w.render_live()
    after = sig(w)
    assert w.undo.stack.count() == n + 1, label_part
    assert label_part in w.actions_by_name["undo"].text() and w.actions_by_name["undo"].text().startswith("Desfazer: ")
    assert same(after, before) is not None, f"{label_part}: a ação não mudou a cena"
    w.actions_by_name["undo"].trigger()
    assert same(sig(w), before) is None, f"{label_part}: desfazer"
    assert label_part in w.actions_by_name["redo"].text()
    w.actions_by_name["redo"].trigger()
    assert same(sig(w), after) is None, f"{label_part}: refazer"


# ------------------------------------------------------------------ estrutura
def test_rooting_midpoint_outgroup_group(win):
    tt = win.tree_tab

    def mid():  # type: ignore[no-untyped-def]
        tt.rb_mid.setChecked(True)
        tt.apply_rooting()
    check(win, mid, "Enraizar no ponto médio")

    def out():  # type: ignore[no-untyped-def]
        tt.rb_out.setChecked(True)
        tt.outgroup.setCurrentText(ROB)
        tt.apply_rooting()
    check(win, out, f"Enraizar na folha {ROB}")
    names = [n for n in win.tree.leaf_names() if n.endswith(("_A00", "_A01"))]
    check(win, lambda: tt.root_on_group(names), "Enraizar no grupo")
    win.actions_by_name["undo"].trigger()
    win.actions_by_name["undo"].trigger()
    win.actions_by_name["undo"].trigger()
    assert tt.rooting == {"mode": "file"}


def test_ladderize_rotate_collapse_hide(win):
    sp = win.style_panel
    leaves = frozenset(n for n in win.tree.leaf_names() if n.endswith(("_A00", "_A01")))
    check(win, lambda: ladder(win, "asc"), "Ladderize")
    check(win, lambda: sp.rotate(leaves), "Girar nó")
    check(win, lambda: sp.collapse(leaves), "Colapsar")
    check(win, lambda: sp.expand(leaves), "Colapsar")
    check(win, lambda: win.figure_panel.hide_leaves([ROB]), "Ocultar")


# ------------------------------------------------------------------ estilo
def test_clades_colors_groups_layout_params_itol(win):
    sp = win.style_panel

    def detect3():  # type: ignore[no-untyped-def]
        sp.k_spin.setValue(3)
        sp.detect()
    check(win, detect3, "Clados")

    def recolor():  # type: ignore[no-untyped-def]
        sp.clade_set.clades[0].color = "#123456"
        sp.clade_list.refresh()
    check(win, recolor, "Clados")
    check(win, lambda: sp.label_mode_text.setChecked(True), "Cores dos clados")
    check(win, lambda: sp.label_panel.style_leaves([ROB], bold=True), "Grupos de rótulos")
    vt = win.viz_tab
    check(win, lambda: vt.layout_cb.setCurrentIndex(vt.layout_cb.findData("fan")), "Layout leque")
    check(win, lambda: vt.fan_angle.setValue(250), "Ângulo do leque")
    check(win, lambda: vt.use_lengths.setChecked(False), "Modo cladograma")
    itol = win.figure_panel.itol
    check(win, lambda: itol.import_files(["examples/itol/colorstrip.txt"], wait=True), "Importar anotação iTOL")

    def remove():  # type: ignore[no-untyped-def]
        itol.list.setCurrentRow(0)
        itol.remove_current()
    check(win, remove, "Remover anotação iTOL")


def test_slider_drag_is_one_step(win):
    vt = win.viz_tab
    vt.layout_cb.setCurrentIndex(vt.layout_cb.findData("fan"))
    win.render_live()
    n = win.undo.stack.count()
    before = sig(win)
    for angle in range(190, 300, 10):                 # vários valores, um desenho por valor
        vt.fan_angle.setValue(angle)
        win.render_live()
    assert win.undo.stack.count() == n + 1
    assert win.actions_by_name["undo"].text() == "Desfazer: Ângulo do leque"
    win.undo.stack.undo()
    assert same(sig(win), before) is None and vt.fan_angle.value() == 180


def test_separate_interactions_are_separate_steps(win, monkeypatch):
    from jabuti.views import undo as undo_mod

    vt = win.viz_tab
    n = win.undo.stack.count()
    vt.branch_scale.setValue(120)
    win.render_live()
    monkeypatch.setattr(undo_mod, "MERGE_SECONDS", -1.0)       # simula uma pausa longa
    vt.branch_scale.setValue(140)
    win.render_live()
    assert win.undo.stack.count() == n + 2


def test_history_resets_on_other_tree_not_on_save_and_has_limit(win, monkeypatch):
    from jabuti.views import undo as undo_mod
    from jabuti.views.undo import UNDO_LIMIT

    ladder(win, "asc")
    win.render_live()
    assert win.undo.stack.count() == 1
    win.project._write(win.tmp / "p.jabuti")                    # salvar não limpa
    assert win.undo.stack.count() == 1
    shutil.copy(TREE, win.tmp / "outra.treefile")
    win.open_tree(win.tmp / "outra.treefile")                    # outra árvore: zera
    assert win.undo.stack.count() == 0 and not win.actions_by_name["undo"].isEnabled()
    assert win.undo.stack.undoLimit() == UNDO_LIMIT == 100
    monkeypatch.setattr(undo_mod, "MERGE_SECONDS", -1.0)       # cada mudança = um passo
    for i in range(UNDO_LIMIT + 5):
        ladder(win, "asc" if i % 2 == 0 else "desc")
        win.render_live()
    assert win.undo.stack.count() == UNDO_LIMIT


def test_history_not_saved_in_project(win):
    import json

    ladder(win, "asc")
    win.render_live()
    text = (win.project._write(win.tmp / "p.jabuti")).read_text(encoding="utf-8")
    assert "undo" not in json.loads(text) and "Ladderize" not in text


def test_dirty_marker_follows_undo(win):
    path = win.project._write(win.tmp / "p.jabuti")
    assert not win.isWindowModified()
    ladder(win, "asc")
    win.render_live()
    assert win.isWindowModified()
    win.undo.stack.undo()                                       # de volta ao estado salvo
    assert not win.isWindowModified() and not win.project.is_dirty()
    win.undo.stack.redo()
    assert win.isWindowModified()
    assert path.is_file()


def test_project_open_resets_history(win, qtbot):
    from jabuti.views.main_window import MainWindow

    ladder(win, "asc")
    win.render_live()
    path = win.project._write(win.tmp / "p.jabuti")
    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.open_project(path, wait=True)
    assert w2.undo.stack.count() == 0 and not w2.isWindowModified()
    ladder(w2, "none")
    w2.render_live()
    assert w2.undo.stack.count() == 1


def test_shortcuts_and_menu(win):
    from PySide6.QtGui import QKeySequence

    act = win.actions_by_name
    assert act["undo"].shortcut() == QKeySequence(QKeySequence.StandardKey.Undo)
    assert not act["redo"].shortcut().isEmpty()
    assert act["undo"].text() == "Desfazer" and not act["undo"].isEnabled()
    edit_menu = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "Editar")
    assert edit_menu.actions()[0] is act["undo"] and edit_menu.actions()[1] is act["redo"]


def test_closed_window_is_freed(qtbot):
    """O histórico não pode manter a janela viva (vazamento) depois de fechada."""
    import gc
    import weakref

    from PySide6.QtCore import QCoreApplication, QEvent

    from jabuti.views.main_window import MainWindow

    w = MainWindow()
    w.open_tree(TREE)
    ladder(w, "asc")
    w.render_live()
    ref = weakref.ref(w)
    w.close()
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    del w
    gc.collect()
    assert ref() is None
