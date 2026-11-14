"""Colapso, ladderize/girar pela GUI e fundo (cor/transparente) no export."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.clades import Clade  # noqa: E402
from jabuti.parsers.newick import parse_newick_string  # noqa: E402
from jabuti.style import CladeStyle, LayoutKind, RenderStyle  # noqa: E402

T = "((A:1,(B:1,C:1)90:1)80:1,(D:1,(E:1,(F:1,G:1)99:1)70:1)95:1,H:1);"
DEFG = frozenset("DEFG")


@pytest.fixture
def draw(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    keep = []

    def _draw(style=None, clades=None, collapsed=None):
        scene = QGraphicsScene()
        r = TreeRenderer(scene)
        res = r.render(parse_newick_string(T), style or RenderStyle(), clades, collapsed)
        keep.append(scene)
        return scene, res

    return _draw


def tagged(scene, tag):
    return [i for i in scene.items() if i.data(1) == tag]


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_collapsed_triangle_and_label(draw, layout):
    scene, res = draw(RenderStyle(layout=layout), [Clade("Grupo D", DEFG)], [DEFG])
    items = tagged(scene, "collapsed")
    texts = [i.text() for i in items if hasattr(i, "text")]
    assert texts == ["Grupo D (4)"]
    assert any(not hasattr(i, "text") for i in items)       # o triângulo
    assert set(res.leaf_items) == {"A", "B", "C", "H"}     # folhas internas ocultas
    collapsed_node = next(n for n in res.node_points if not n.is_leaf and len(n.leaves()) == 4)
    assert collapsed_node in res.node_points                # clicável (expandir)
    assert all(c not in res.node_points for c in collapsed_node.children)


def test_collapsed_label_without_clade(draw):
    scene, _ = draw(collapsed=[DEFG])
    assert [i.text() for i in tagged(scene, "collapsed") if hasattr(i, "text")] == ["4 folhas"]


def test_collapsed_uses_clade_color(draw):
    scene, _ = draw(clades=[Clade("x", DEFG, color="#ff8800")], collapsed=[DEFG])
    tri = next(i for i in tagged(scene, "collapsed") if not hasattr(i, "text"))
    assert tri.pen().color().name() == "#ff8800"


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_strip_spans_collapsed_clade(draw, layout):
    style = RenderStyle(layout=layout, clades=CladeStyle(outer_strip=True, background=True))
    scene, _ = draw(style, [Clade("x", DEFG)], [DEFG])
    assert len(tagged(scene, "clade-strip")) == 1
    assert len(tagged(scene, "clade-background")) == 1


def test_clade_hidden_inside_collapse_not_drawn(draw):
    style = RenderStyle(clades=CladeStyle(outer_strip=True))
    scene, _ = draw(style, [Clade("fg", frozenset("FG"))], [DEFG])
    assert tagged(scene, "clade-strip") == []


def test_aligned_guide_reaches_collapsed_triangle(draw):
    scene, _ = draw(RenderStyle(layout=LayoutKind.CIRCULAR), collapsed=[DEFG])
    assert tagged(scene, "tip-guides")


# ------------------------------------------------------------------ fundo
def test_background_color_in_scene_and_svg(draw, tmp_path):
    from jabuti.views.export import export_svg

    scene, _ = draw(RenderStyle(background="#fbf7ee"))
    assert scene.backgroundBrush().color().name() == "#fbf7ee"
    assert "#fbf7ee" in export_svg(scene, tmp_path / "b.svg").read_text().lower()


@pytest.mark.parametrize("bg, alpha", [(None, 0), ("#ffffff", 255)])
def test_png_background_alpha(draw, tmp_path, bg, alpha):
    from PySide6.QtGui import QImage

    from jabuti.views.export import export_png

    scene, _ = draw(RenderStyle(background=bg))
    img = QImage(str(export_png(scene, tmp_path / "t.png", dpi=72)))
    assert img.pixelColor(1, 1).alpha() == alpha


def test_transparent_svg_has_no_background(draw, tmp_path):
    from jabuti.views.export import export_svg

    scene, _ = draw(RenderStyle(background=None))
    txt = export_svg(scene, tmp_path / "t.svg").read_text().lower()
    assert 'fill="#ffffff"' not in txt


# -------------------------------------------------------------------- GUI
@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    f = tmp_path / "t.nwk"
    f.write_text(T)
    win = MainWindow()
    qtbot.addWidget(win)
    win.tree_tab.load(f)
    return win


def node_with(tree, names):
    from jabuti.models.clades import mrca

    return mrca(tree, frozenset(names))


def action(menu, prefix):
    return next(a for a in menu.actions() if a.text().startswith(prefix))


def visible_order(win):
    return [l.name for l in win.display_tree.leaves()]


def test_gui_ladderize(window):
    sp = window.style_panel
    sp.ladder.setCurrentIndex(sp.ladder.findData("desc"))
    window.render_live()
    assert visible_order(window)[-1] == "H"
    sp.ladder.setCurrentIndex(sp.ladder.findData("asc"))
    window.render_live()
    assert visible_order(window)[0] == "H"
    assert [l.name for l in window.tree.leaves()][0] == "A"  # árvore enraizada intacta


def test_gui_rotate_via_menu(window):
    node = node_with(window.display_tree, "ABC")
    action(window.build_node_menu(node), "Girar nó").trigger()
    window.render_live()
    assert visible_order(window)[:3] == ["B", "C", "A"]
    window.style_panel.reset_rotations()
    window.render_live()
    assert visible_order(window)[:3] == ["A", "B", "C"]


def test_gui_collapse_and_expand(window):
    node = node_with(window.display_tree, "DEFG")
    action(window.build_node_menu(node), "Colapsar").trigger()
    window.render_live()
    assert "E" not in window.canvas.result.leaf_items
    node = node_with(window.display_tree, "DEFG")
    action(window.build_node_menu(node), "Expandir").trigger()
    window.render_live()
    assert "E" in window.canvas.result.leaf_items


def test_gui_search_inside_collapsed_explains(window):
    window.style_panel.collapse(DEFG)
    window.render_live()
    window.search_box.setText("F")
    window.do_search()
    assert "colapsado" in window.statusBar().currentMessage()


def test_gui_root_has_no_collapse(window):
    menu = window.build_node_menu(window.display_tree.root)
    assert not any(a.text().startswith("Colapsar") for a in menu.actions())


def test_gui_transparent_background(window):
    from PySide6.QtCore import Qt

    sp = window.style_panel
    sp.bg_transparent.setChecked(True)
    window.render_live()
    assert window.canvas.tree_scene.backgroundBrush().style() == Qt.BrushStyle.NoBrush
    assert window.canvas.backgroundBrush().style() == Qt.BrushStyle.TexturePattern  # xadrez na tela
    sp.bg_transparent.setChecked(False)
    sp.bg_row.buttons["#f4f4f4"].click()
    window.render_live()
    assert window.canvas.tree_scene.backgroundBrush().color().name() == "#f4f4f4"
