"""Clados na cena: cores, paleta, faixas, nomes, linha de corte e GUI."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.clades import Clade  # noqa: E402
from jabuti.parsers.newick import parse_newick_string  # noqa: E402
from jabuti.style import PALETTES, CladeStyle, LayoutKind, RenderStyle  # noqa: E402

BIN = "((((A:1,B:1)95/99:1,C:2)60/80:1,(D:1,E:1)99/100:3)90/97:1,(F:1,(G:1,H:1)40/50:1)85/96:2);"


@pytest.fixture
def render(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    def _render(clades, layout=LayoutKind.RECTANGULAR, **clade_opts):
        scene = QGraphicsScene()
        style = RenderStyle(layout=layout, clades=CladeStyle(**clade_opts))
        res = TreeRenderer(scene).render(parse_newick_string(BIN), style, clades)
        return scene, res

    return _render


def tagged(scene, tag):
    return [i for i in scene.items() if i.data(1) == tag]


def branch_colors(scene):
    return {i.pen().color().name() for i in tagged(scene, "branches")}


LAYOUTS = [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_branch_and_label_colors(render, layout):
    clades = [Clade("abc", frozenset("ABC")), Clade("fgh", frozenset("FGH"))]
    scene, res = render(clades, layout)
    pal = PALETTES["Tableau 10"]
    assert {pal[0], pal[1], "#8a8a8a"} <= branch_colors(scene)  # 2 clados + neutro
    assert res.leaf_items["A"][0].brush().color().name() == pal[0]
    assert res.leaf_items["G"][0].brush().color().name() == pal[1]
    assert res.leaf_items["D"][0].brush().color().name() == "#8a8a8a"  # fora de clado


def test_palette_change_recolors(render):
    clades = [Clade("abc", frozenset("ABC"))]
    _, res = render(clades, palette="Set2")
    assert res.leaf_items["A"][0].brush().color().name() == PALETTES["Set2"][0]


def test_individual_color_overrides_palette(render):
    _, res = render([Clade("abc", frozenset("ABC"), color="#ff00ff")])
    assert res.leaf_items["B"][0].brush().color().name() == "#ff00ff"


def test_coloring_options_off(render):
    scene, res = render([Clade("abc", frozenset("ABC"))], color_branches=False, color_labels=False)
    assert branch_colors(scene) == {"#202020"}
    assert res.leaf_items["A"][0].brush().color().name() == "#202020"


def test_no_clades_uses_base_colors(render):
    scene, _ = render([])
    assert branch_colors(scene) == {"#202020"}


def test_stem_branch_not_colored(render):
    """O ramo que chega ao MRCA do clado fica fora do clado (cor de fora)."""
    scene, res = render([Clade("de", frozenset("DE"))])
    # D/E coloridos, e existe ramo neutro (o tronco de DE e o resto)
    assert "#8a8a8a" in branch_colors(scene)


@pytest.mark.parametrize("layout", LAYOUTS)
def test_background_strip_and_names(render, layout):
    clades = [Clade("Grupo ABC", frozenset("ABC")), Clade("Grupo FGH", frozenset("FGH"))]
    scene, _ = render(clades, layout, background=True, outer_strip=True, show_names=True)
    assert len(tagged(scene, "clade-background")) == 2
    assert len(tagged(scene, "clade-strip")) == 2
    bg = tagged(scene, "clade-background")[0]
    assert bg.brush().color().alphaF() < 0.5      # translúcido
    assert bg.zValue() < 0                         # atrás da árvore
    assert tagged(scene, "clade-name")


def test_curved_name_is_one_item_per_char(render):
    scene, _ = render([Clade("ABC", frozenset("ABC"))], LayoutKind.CIRCULAR, show_names=True)
    chars = [i for i in tagged(scene, "clade-name") if hasattr(i, "text")]
    assert "".join(sorted(i.text() for i in chars)) == "ABC"


def test_strip_sits_in_reserved_ring_area(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    scene = QGraphicsScene()
    r = TreeRenderer(scene)
    style = RenderStyle(layout=LayoutKind.CIRCULAR, clades=CladeStyle(outer_strip=True))
    r.render(parse_newick_string(BIN), style, [Clade("x", frozenset("ABC"))])
    g = r.geometry
    assert g.tip_ring < g.rings_start < g.rings_end < g.label_radius
    strip = tagged(scene, "clade-strip")[0]
    br = strip.path().boundingRect()
    assert max(abs(br.left()), abs(br.right()), abs(br.top()), abs(br.bottom())) <= g.rings_end + 1


def test_invalid_clade_not_drawn(render):
    t = parse_newick_string(BIN)
    t.reroot_outgroup("A")
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    scene = QGraphicsScene()  # manter referência: a cena é dona dos itens
    res = TreeRenderer(scene).render(t, RenderStyle(), [Clade("x", frozenset("ABCDE"))])
    assert not res.clades[0].valid
    assert res.leaf_items["A"][0].brush().color().name() == "#202020"


@pytest.mark.parametrize("layout", LAYOUTS)
def test_cut_line(render, layout):
    scene, _ = render([], layout, cut_distance=1.5)
    assert len(tagged(scene, "cut-line")) == 1
    scene, _ = render([], layout)
    assert tagged(scene, "cut-line") == []


@pytest.mark.parametrize("fmt", ["svg", "pdf", "png"])
def test_export_with_clades(render, tmp_path, fmt):
    from jabuti.views import export

    clades = [Clade("abc", frozenset("ABC")), Clade("fgh", frozenset("FGH"))]
    scene, _ = render(clades, LayoutKind.CIRCULAR, background=True, outer_strip=True, show_names=True)
    out = getattr(export, f"export_{fmt}")(scene, tmp_path / f"c.{fmt}")
    if fmt == "svg":
        text = out.read_text().lower()
        assert PALETTES["Tableau 10"][0] in text and "fill-opacity" in text


# ------------------------------------------------------------------ GUI
@pytest.fixture
def window(qtbot, monkeypatch, data_dir):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    win = MainWindow()
    qtbot.addWidget(win)
    win.tree_tab.load("examples/paraburkholderia_40.treefile")
    return win


def _set_mode(panel, mode):
    panel.mode.setCurrentIndex(panel.mode.findData(mode))


def test_gui_detect_k_and_palette(window):
    sp = window.style_panel
    _set_mode(sp, "k")
    sp.k_spin.setValue(5)
    n = sp.detect()
    window.render_live()
    assert n >= 5
    assert len(window.canvas.result.clades) == n
    assert len(sp.legend.entries) == n
    first_before = sp.legend.entries[0][1]
    sp.palette_buttons["Okabe-Ito (daltônico)"].click()
    window.render_live()
    assert sp.legend.entries[0][1] == PALETTES["Okabe-Ito (daltônico)"][0] != first_before


def test_gui_live_param_redetects(window):
    sp = window.style_panel
    _set_mode(sp, "k")
    sp.k_spin.setValue(3)
    sp.detect()
    sp.k_spin.setValue(6)  # ao vivo: mesmo modo
    assert len([c for c in sp.clade_set.clades if c.source == "auto"]) >= 6


def test_gui_support_mode(window):
    sp = window.style_panel
    _set_mode(sp, "support")
    sp.sup_thr.setValue(100)
    n = sp.detect()
    assert n > 0
    assert all(c.source == "auto" for c in sp.clade_set.clades)


def test_gui_distance_mode_cut_line(window):
    sp = window.style_panel
    _set_mode(sp, "distance")
    sp.dist_slider.setValue(500)
    window.render_live()
    assert tagged(window.canvas.tree_scene, "cut-line")
    sp.detect()
    sp.dist_slider.setValue(700)  # ao vivo
    window.render_live()
    assert window.current_style().clades.cut_distance == pytest.approx(sp.max_depth * 0.7)


def test_gui_manual_clade_from_node_menu(window):
    sp = window.style_panel
    tree = window.tree
    node = next(n for n in tree.root.traverse_preorder() if not n.is_leaf and 3 <= len(n.leaves()) <= 6)
    menu = window.build_node_menu(node)
    actions = [a for a in menu.actions() if a.text() == "Definir como clado"]
    actions[0].trigger()
    window.render_live()
    (clade,) = sp.clade_set.clades
    assert clade.source == "manual" and len(clade.leaves) == len(node.leaves())
    # o menu agora oferece remover
    menu = window.build_node_menu(node)
    rm = [a for a in menu.actions() if a.text().startswith("Remover clado")]
    rm[0].trigger()
    assert sp.clade_set.clades == []


def test_gui_rename_and_hide(window):
    sp = window.style_panel
    _set_mode(sp, "k")
    sp.k_spin.setValue(3)
    sp.detect()
    window.render_live()
    sp.clade_list.item(0, 1).setText("Paraburkholderia s.s.")
    assert sp.clade_set.clades[0].name == "Paraburkholderia s.s."
    sp.clade_list.cellWidget(0, 3).setChecked(False)
    window.render_live()
    assert all(name != "Paraburkholderia s.s." for name, _ in sp.legend.entries)


def test_gui_manual_kept_after_reroot(window):
    sp = window.style_panel
    burk = frozenset({"Burkholderia_cepacia_ATCC25416", "Burkholderia_cenocepacia_J2315"})
    sp.add_manual_clade(burk, "Burkholderia")
    window.tree_tab.rb_mid.setChecked(True)
    window.tree_tab.apply_rooting()
    assert window.canvas.result.clades[0].valid


def test_gui_option_checkboxes_redraw(window, qtbot):
    """Marcar as opções no painel agenda o redesenho (sinal sem argumento)."""
    sp = window.style_panel
    _set_mode(sp, "k")
    sp.k_spin.setValue(4)
    sp.detect()
    window.render_live()
    for cb in (sp.opt_background, sp.opt_strip, sp.opt_names):
        with qtbot.waitSignal(sp.changed, timeout=500):
            cb.setChecked(True)
    window.render_live()
    scene = window.canvas.tree_scene
    assert tagged(scene, "clade-background") and tagged(scene, "clade-strip") and tagged(scene, "clade-name")
    with qtbot.waitSignal(sp.changed, timeout=500):
        sp.show_cut.setChecked(False)
