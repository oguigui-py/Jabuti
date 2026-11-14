"""Etapa 2: enraizar no grupo selecionado, ocultar folhas e ramo encurtado."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.document import ShortBranch, TreeEdits, apply_edits, prune  # noqa: E402
from jabuti.parsers.newick import parse_newick_string  # noqa: E402
from jabuti.style import LayoutKind, RenderStyle  # noqa: E402

T = "((A:1,B:1)90:1,(C:1,(D:1,E:1)80:1)70:1);"


def leafsets_with_support(tree):
    """{frozenset(lado menor da bipartição): suporte} — independente da raiz."""
    names = frozenset(tree.leaf_names())
    out = {}
    for n in tree.root.traverse_preorder():
        if n is tree.root or n.is_leaf or not n.supports:
            continue
        side = frozenset(l.name for l in n.leaves())
        other = names - side
        key = min(side, other, key=lambda s: (len(s), sorted(s)))
        out[key] = n.supports[-1]
    return out


def lengths(tree):
    return {l.name: l.length for l in tree.leaves()}


# ------------------------------------------------------------- enraizar
def test_reroot_on_monophyletic_group():
    t = parse_newick_string(T)
    extras = t.reroot_on_group({"D", "E"})
    assert extras == []
    kids = [frozenset(l.name for l in c.leaves()) for c in t.root.children]
    assert frozenset({"D", "E"}) in kids
    assert sum(c.length for c in t.root.children) == pytest.approx(1.0)   # ramo dividido ao meio


def test_reroot_on_group_spanning_current_root():
    t = parse_newick_string(T)
    assert t.reroot_on_group({"C", "D", "E"}) == []                         # o outro lado da raiz
    kids = sorted(sorted(l.name for l in c.leaves()) for c in t.root.children)
    assert kids == [["A", "B"], ["C", "D", "E"]]
    assert sum(c.length for c in t.root.children) == pytest.approx(2.0)


def test_reroot_non_monophyletic_reports_extras():
    t = parse_newick_string(T)
    assert t.group_extras({"A", "C"}) == ["D", "E"]
    assert lengths(t) == lengths(parse_newick_string(T))                    # group_extras não altera
    assert t.reroot_on_group({"A", "C"}) == ["D", "E"]


def test_reroot_keeps_supports_per_bipartition():
    t = parse_newick_string("(((A:1,B:1)95:1,C:1)80:1,(D:1,(E:1,F:1)60:1)70:1);")
    before = leafsets_with_support(t)
    t.reroot_on_group({"E", "F"})
    after = leafsets_with_support(t)
    for key in (frozenset({"A", "B"}), frozenset({"E", "F"})):
        assert after[key] == before[key]


def test_reroot_errors():
    t = parse_newick_string(T)
    with pytest.raises(ValueError, match="não encontrada"):
        t.reroot_on_group({"Z"})
    with pytest.raises(ValueError, match="todas as folhas"):
        t.reroot_on_group(set("ABCDE"))


# ---------------------------------------------------------------- poda
def test_prune_joins_branch_lengths_and_keeps_child_support():
    t = parse_newick_string(T)
    prune(t, {"C"})
    de = next(n for n in t.root.traverse_preorder() if sorted(l.name for l in n.leaves()) == ["D", "E"])
    assert de.length == pytest.approx(2.0) and de.supports == [80.0]
    assert sorted(t.leaf_names()) == ["A", "B", "D", "E"]


def test_prune_unary_root_removed():
    t = parse_newick_string(T)
    prune(t, {"A", "B"})
    assert sorted(t.leaf_names()) == ["C", "D", "E"]
    assert t.root.parent is None and t.root.length is None and len(t.root.children) == 2


def test_apply_edits_keeps_at_least_two_leaves_and_never_touches_original():
    t = parse_newick_string(T)
    shown = apply_edits(t, TreeEdits(hidden={"A", "B", "C", "D"}))
    assert len(shown.leaves()) == 5                     # poda recusada: sobraria 1 folha
    shown = apply_edits(t, TreeEdits(hidden={"A"}))
    assert sorted(shown.leaf_names()) == ["B", "C", "D", "E"]
    assert len(t.leaves()) == 5


def test_hidden_leaves_ignored_by_clades_and_collapse(qapp):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.models.clades import Clade
    from jabuti.views.tree_renderer import TreeRenderer

    t = parse_newick_string(T)
    edits = TreeEdits(hidden={"E"})
    shown = apply_edits(t, edits)
    scene = QGraphicsScene()
    res = TreeRenderer(scene).render(shown, RenderStyle(), [Clade("x", frozenset("CDE"), "#ff0000", True, "manual")],
                                     [frozenset("CDE")], hidden=edits.hidden)
    assert res.clades[0].valid
    assert any(i.data(1) == "collapsed" for i in scene.items())


def test_tracks_skip_hidden_leaves(qapp):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.models.tracks import bar_track
    from jabuti.views.tree_renderer import TreeRenderer

    shown = apply_edits(parse_newick_string(T), TreeEdits(hidden={"A"}))
    scene = QGraphicsScene()
    TreeRenderer(scene).render(shown, RenderStyle(), columns=[bar_track("bar:x", "x", {k: 1.0 for k in "ABCDE"})])
    (bars,) = [i for i in scene.items() if i.data(1) == "bar"]
    assert len(bars.path().toSubpathPolygons()) == 4


# ------------------------------------------------------- ramo encurtado
@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_shortened_branch_length_and_mark(qapp, layout):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    t = parse_newick_string("((A:1,B:1):1,(C:1,D:1):20);")
    shown = apply_edits(t, TreeEdits(shortened=[ShortBranch(frozenset("CD"), 2.0)]))
    cd = next(n for n in shown.root.children if sorted(l.name for l in n.leaves()) == ["C", "D"])
    assert cd.length == 2.0 and shown.broken == {cd}
    scene = QGraphicsScene()
    TreeRenderer(scene).render(shown, RenderStyle(layout=layout))
    marks = [i for i in scene.items() if i.data(1) == "branch-break"]
    assert len(marks) == 2                                            # lacuna + barras
    assert all(m.zValue() >= 1 for m in marks)


def test_short_branch_not_applied_when_already_short():
    t = parse_newick_string("((A:1,B:1):1,(C:1,D:1):1);")
    shown = apply_edits(t, TreeEdits(shortened=[ShortBranch(frozenset("CD"), 5.0)]))
    assert shown.broken == set()


def test_preset_roundtrip_hidden_and_shortened():
    from jabuti.models.clades import CladeSet
    from jabuti.presets import preset_from_dict, preset_to_dict

    edits = TreeEdits(hidden={"A", "C"}, shortened=[ShortBranch(frozenset("CD"), 0.5)])
    loaded = preset_from_dict(preset_to_dict(RenderStyle(), CladeSet(), edits))
    assert loaded.edits.hidden == {"A", "C"} and loaded.edits.shortened == edits.shortened
    bad = preset_from_dict({"version": 1, "edits": {"hidden": "A", "shortened": [{"leaves": ["A"], "max_length": -1}]}})
    assert bad.edits.hidden == set() and bad.edits.shortened == [] and len(bad.warnings) == 2


# ----------------------------------------------------------------- GUI
@pytest.fixture
def window(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    shown = []
    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    win = MainWindow()
    win.shown = shown
    qtbot.addWidget(win)
    win.tree_tab.load("examples/paraburkholderia_40.treefile")
    return win


BURK = ["Burkholderia_cepacia_ATCC25416", "Burkholderia_cenocepacia_J2315"]


def test_gui_root_on_selection(window):
    window.canvas.set_selection(BURK)
    assert window.figure_panel.root_group_btn.isEnabled()
    window.root_on_selection()
    kids = [sorted(l.name for l in c.leaves()) for c in window.tree.root.children]
    assert sorted(BURK) in kids
    assert window.tree_tab.rb_group.isChecked()


def test_gui_root_non_monophyletic_asks(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No)
    before = [sorted(l.name for l in c.leaves()) for c in window.tree.root.children]
    window.canvas.set_selection([BURK[0], "Robbsia_andropogonis_LMG2129"])
    window.root_on_selection()
    assert asked and "mais" in asked[0]
    assert [sorted(l.name for l in c.leaves()) for c in window.tree.root.children] == before   # recusado
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.root_on_selection()
    assert [sorted(l.name for l in c.leaves()) for c in window.tree.root.children] != before


def test_gui_hide_and_restore(window):
    fp = window.figure_panel
    window.canvas.set_selection(BURK)
    fp.hide_selected()
    window.render_live()                                  # (o redesenho real tem debounce)
    assert set(window.display_tree.leaf_names()).isdisjoint(BURK)
    assert fp.hidden_list.count() == 2 and window.canvas.selected == []
    assert "oculta" in window.statusBar().currentMessage()
    window.search_box.setText("cepacia")
    window.do_search()
    assert "oculta" in window.statusBar().currentMessage()
    fp.hidden_list.item(0).setSelected(True)
    fp.restore_selected()
    window.render_live()
    assert len(window.display_tree.leaves()) == 39
    fp.restore_all()
    window.render_live()
    assert len(window.display_tree.leaves()) == 40


def test_gui_cannot_hide_almost_everything(window):
    fp = window.figure_panel
    assert fp.hide_leaves(window.tree.leaf_names()[:-1]) is False
    assert "2 folhas" in fp.prune_hint.text()


def test_gui_context_menu_hide_and_shorten(window):
    node = window.tree.find_leaf(BURK[0]).parent
    menu = window.build_node_menu(node)
    texts = [a.text() for a in menu.actions()]
    assert "Ocultar estas 2 folhas" in texts and "Encurtar este ramo (marca //)" in texts
    next(a for a in menu.actions() if a.text().startswith("Encurtar")).trigger()
    assert len(window.style_panel.edits.shortened) == 1
    assert [i for i in window.canvas.tree_scene.items() if i.data(1) == "branch-break"]
    assert window.figure_panel.short_list.count() == 1
    window.figure_panel.short_len.setValue(0.001)
    assert window.style_panel.edits.shortened[0].max_length == 0.001
    window.figure_panel.break_legend.setChecked(True)
    window.render_live()
    assert any(g.title == "Escala" for g in window.style_panel.legend.groups)
    menu = window.build_node_menu(node)
    assert "Desfazer encurtamento do ramo" in [a.text() for a in menu.actions()]
