"""Destaque de rótulos: grupos por clado, seleção e padrão; desenho, export e presets."""

import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.clades import Clade  # noqa: E402
from jabuti.models.label_groups import LabelGroupSet, LabelLook, match_pattern  # noqa: E402
from jabuti.parsers.newick import parse_newick_string  # noqa: E402
from jabuti.presets import preset_from_dict, preset_to_dict  # noqa: E402
from jabuti.style import CladeStyle, LayoutKind, RenderStyle  # noqa: E402

BIN = "((((A:1,B:1)95/99:1,C:2)60/80:1,(D:1,E:1)99/100:3)90/97:1,(F:1,(G:1,H:1)40/50:1)85/96:2);"
NAMES = ["Paraburkholderia_xenovorans_LB400", "P_xenovorans_CCUG", "LB400_like", "Burkholderia_cepacia"]
LAYOUTS = [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR]


# ------------------------------------------------------------------ modelo
def test_pattern_plain_is_case_insensitive_contains():
    assert match_pattern(NAMES, "XENOVORANS") == NAMES[:2]
    assert match_pattern(NAMES, "  ") == []


def test_pattern_regex():
    assert match_pattern(NAMES, "^LB400", regex=True) == ["LB400_like"]
    assert match_pattern(NAMES, "lb400$", regex=True) == ["Paraburkholderia_xenovorans_LB400"]
    assert match_pattern(NAMES, "^LB400", regex=False) == []   # texto simples não é regex


def test_pattern_invalid_regex_message():
    with pytest.raises(ValueError, match="Expressão regular inválida"):
        match_pattern(NAMES, "(abc", regex=True)


def test_conflict_last_group_wins_and_counts():
    gs = LabelGroupSet()
    g1 = gs.add("ABCD", "selection")
    g2 = gs.add("CDE", "pattern")
    eff = gs.effective()
    assert eff["A"] is g1 and eff["C"] is g2 and eff["E"] is g2
    counts = gs.effective_counts()
    assert counts[id(g1)] == 2 and counts[id(g2)] == 3
    g2.visible = False                        # invisível não disputa
    assert gs.effective()["C"] is g1
    assert gs.group_of("E") is None


def test_new_groups_get_distinct_highlights():
    gs = LabelGroupSet()
    a, b = gs.add("A", "selection"), gs.add("B", "selection")
    assert a.look.background and b.look.background and a.look.background != b.look.background


def test_restricted_to_ignores_missing_leaves():
    gs = LabelGroupSet()
    gs.add(["A", "X", "Y"], "selection")
    gs.add(["Z"], "selection")
    out, ignored, dropped = gs.restricted_to("ABC")
    assert ignored == 3 and dropped == 1
    assert [g.leaves for g in out.groups] == [frozenset("A")]


# --------------------------------------------------------------- desenho
@pytest.fixture
def render(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    def _render(groups=None, layout=LayoutKind.RECTANGULAR, tree=None, clades=None, columns=None, **cs):
        scene = QGraphicsScene()
        style = RenderStyle(layout=layout, clades=CladeStyle(**cs))
        res = TreeRenderer(scene).render(tree or parse_newick_string(BIN), style, clades, None, columns,
                                         label_groups=groups)
        return scene, res

    return _render


def tagged(scene, tag):
    return [i for i in scene.items() if i.data(1) == tag]


def branch_colors(scene):
    return {i.pen().color().name() for i in tagged(scene, "branches")}


def _assert_bg_follows_text(res):
    """Fundo com a mesma transformação do texto e contendo-o (em coordenadas de cena)."""
    from PySide6.QtCore import QPointF

    for name, bg in res.label_backgrounds.items():
        text = res.leaf_items[name][0]
        assert bg.rotation() == pytest.approx(text.rotation())
        assert bg.pos() == text.pos()
        assert bg.transformOriginPoint() == text.transformOriginPoint()
        br = text.boundingRect()
        center = text.mapToScene(QPointF(br.width() / 2, br.height() / 2))
        assert bg.contains(bg.mapFromScene(center))


@pytest.mark.parametrize("layout", LAYOUTS)
def test_group_style_applies_only_to_labels(render, layout):
    gs = LabelGroupSet()
    gs.add("AB", "selection", look=LabelLook(text_color="#ff0000", background="#00ff00", bold=True,
                                             size_scale=1.5))
    scene0, _ = render(None, layout)
    scene, res = render(gs, layout)
    assert branch_colors(scene) == branch_colors(scene0)          # ramos intactos
    a = res.leaf_items["A"][0]
    assert a.brush().color().name() == "#ff0000"
    assert a.font().bold() and a.font().pointSizeF() == pytest.approx(15)
    assert res.leaf_items["C"][0].brush().color().name() == "#202020"   # fora do grupo: padrão
    assert set(res.label_backgrounds) == {"A", "B"}
    assert res.label_backgrounds["A"].brush().color().name() == "#00ff00"
    _assert_bg_follows_text(res)


def test_empty_fields_inherit_clade_color(render):
    gs = LabelGroupSet()
    gs.add("A", "selection", look=LabelLook(background="#ffe066"))   # sem cor de texto
    clades = [Clade("ab", frozenset("AB"), color="#123456")]
    _, res = render(gs, clades=clades)
    assert res.leaf_items["A"][0].brush().color().name() == "#123456"


def test_clade_label_background_option(render):
    clades = [Clade("ab", frozenset("AB"), color="#123456")]
    scene, res = render(None, clades=clades, label_background=True, color_labels=False,
                        color_branches=False)
    assert set(res.label_backgrounds) == {"A", "B"}
    c = res.label_backgrounds["A"].brush().color()
    assert c.name() == "#123456" and c.alphaF() == pytest.approx(0.35, abs=0.01)
    assert res.leaf_items["A"][0].brush().color().name() == "#202020"   # texto não colorido
    assert "#123456" not in branch_colors(scene)                        # ramos também não


def test_group_from_clade_in_panel(qtbot):
    from jabuti.views.style_panel import StylePanel

    sp = StylePanel()
    qtbot.addWidget(sp)
    clade = sp.clade_set.add_manual(frozenset("DE"), "de", "#aa0000")
    sp.clade_list.refresh()
    sp.clade_list.cellWidget(0, 3).click()          # botão "Aa"
    (g,) = sp.label_groups.groups
    assert g.source == "clade" and g.name == "de" and g.leaves == clade.leaves
    assert g.look.background == "#aa0000"


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("how", ["midpoint", "A", "G"])
def test_backgrounds_follow_reroot(render, layout, how):
    gs = LabelGroupSet()
    gs.add("ADG", "selection", look=LabelLook(background="#b7e4a3", padding=3))
    tree = parse_newick_string(BIN)
    tree.reroot_midpoint() if how == "midpoint" else tree.reroot_outgroup(how)
    _, res = render(gs, layout, tree=tree)
    assert set(res.label_backgrounds) == set("ADG")
    _assert_bg_follows_text(res)


def test_circular_left_half_background_is_flipped_with_text(render):
    gs = LabelGroupSet()
    gs.add("ABCDEFGH", "selection", look=LabelLook(background="#b7e4a3"))
    _, res = render(gs, LayoutKind.CIRCULAR)
    rotations = {round(bg.rotation()) for bg in res.label_backgrounds.values()}
    assert any(-90 < r < 90 for r in rotations)                        # inclui metade invertida
    _assert_bg_follows_text(res)


def test_rect_background_does_not_overlap_neighbors(render):
    gs = LabelGroupSet()
    gs.add("ABCDEFGH", "selection", look=LabelLook(background="#b7e4a3", padding=12))
    _, res = render(gs)
    rects = sorted((bg.sceneBoundingRect() for bg in res.label_backgrounds.values()), key=lambda r: r.top())
    for upper, lower in zip(rects, rects[1:]):
        assert upper.bottom() <= lower.top() + 1e-6


def test_circular_background_does_not_overlap_neighbors(render):
    from PySide6.QtGui import QPainterPath

    gs = LabelGroupSet()
    gs.add("ABCDEFGH", "selection", look=LabelLook(background="#b7e4a3", padding=12))
    _, res = render(gs, LayoutKind.CIRCULAR)
    shapes = []
    for bg in res.label_backgrounds.values():
        p = QPainterPath()
        p.addPolygon(bg.mapToScene(bg.path().boundingRect()))
        shapes.append(p)
    for i, a in enumerate(shapes):
        for b in shapes[i + 1:]:
            assert a.intersected(b).boundingRect().width() * a.intersected(b).boundingRect().height() < 1.0


@pytest.mark.parametrize("layout", LAYOUTS)
def test_heatmap_starts_after_backgrounds(render, layout):
    from jabuti.models.annotations import LeafColumn

    gs = LabelGroupSet()
    gs.add("ABCDEFGH", "selection", look=LabelLook(background="#b7e4a3", padding=8, size_scale=1.6))
    col = LeafColumn("gene:x", "x", {n: "#2b6cb0" for n in "ABCDEFGH"})
    scene, res = render(gs, layout, columns=[col])
    cells = tagged(scene, "heatmap")
    if layout == LayoutKind.RECTANGULAR:
        left = min(c.sceneBoundingRect().left() for c in cells)
        assert all(bg.sceneBoundingRect().right() <= left for bg in res.label_backgrounds.values())
    else:
        # alinhado: anéis por dentro do raio onde começam os fundos
        ring_out = max(math.hypot(p.x(), p.y()) for c in cells
                       for p in (c.path().pointAtPercent(t) for t in (0, 0.25, 0.5, 0.75)))
        from PySide6.QtCore import QPointF

        for name, bg in res.label_backgrounds.items():
            text = res.leaf_items[name][0]
            br = bg.path().boundingRect()
            inner = min(math.hypot(q.x(), q.y()) for q in (
                bg.mapToScene(QPointF(br.left(), br.center().y())),
                bg.mapToScene(QPointF(br.right(), br.center().y()))))
            assert inner >= ring_out - 0.5, (name, text.text())


@pytest.mark.parametrize("fmt", ["svg", "pdf", "png"])
def test_export_contains_backgrounds(render, tmp_path, fmt):
    from jabuti.views import export

    gs = LabelGroupSet()
    gs.add("AB", "selection", look=LabelLook(background="#00cc66", background_alpha=0.5))
    scene, _ = render(gs, LayoutKind.CIRCULAR)
    out = getattr(export, f"export_{fmt}")(scene, tmp_path / f"t.{fmt}")
    assert out.stat().st_size > 0
    if fmt == "svg":
        text = out.read_text().lower()
        assert 'fill="#00cc66"' in text and 'fill-opacity="0.5' in text


def test_collapsed_leaves_have_no_label_background(render, qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    gs = LabelGroupSet()
    gs.add("ABF", "selection", look=LabelLook(background="#b7e4a3"))
    res = TreeRenderer(QGraphicsScene()).render(parse_newick_string(BIN), RenderStyle(), None,
                                                [frozenset("AB")], label_groups=gs)
    assert set(res.label_backgrounds) == {"F"}


# --------------------------------------------------------------- presets
def test_preset_round_trip():
    gs = LabelGroupSet(show_in_legend=False)
    gs.add("AB", "pattern", "xeno", LabelLook(text_color="#ff0000", background=None, bold=True, italic=False,
                                              size_scale=1.2, padding=4, radius=0))
    loaded = preset_from_dict(preset_to_dict(RenderStyle(), label_groups=gs))
    assert loaded.warnings == []
    (g,) = loaded.label_groups.groups
    assert (g.name, g.source, g.leaves) == ("xeno", "pattern", frozenset("AB"))
    assert g.look == gs.groups[0].look
    assert loaded.label_groups.show_in_legend is False


def test_preset_invalid_look_warns():
    data = preset_to_dict(RenderStyle())
    data["label_groups"] = {"groups": [{"name": "x", "leaves": ["A"], "look": {"background": "verde"}},
                                       {"name": "y", "leaves": []}]}
    loaded = preset_from_dict(data)
    assert len(loaded.label_groups.groups) == 1
    assert loaded.label_groups.groups[0].look.background is None
    assert len(loaded.warnings) == 2


# -------------------------------------------------------------------- GUI
@pytest.fixture
def window(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    win = MainWindow()
    qtbot.addWidget(win)
    win.tree_tab.load("examples/paraburkholderia_40.treefile")
    return win


def test_gui_cmd_and_shift_selection(window):
    from PySide6.QtCore import Qt

    c = window.canvas
    order = list(c.result.leaf_points)
    c.click_leaf(order[2], Qt.KeyboardModifier.NoModifier)
    c.click_leaf(order[5], Qt.KeyboardModifier.ControlModifier)
    assert c.selected == [order[2], order[5]]
    c.click_leaf(order[5], Qt.KeyboardModifier.ControlModifier)       # alterna
    assert c.selected == [order[2]]
    c.click_leaf(order[6], Qt.KeyboardModifier.ShiftModifier)          # intervalo a partir da âncora
    assert c.selected == order[2:7]
    assert window.style_panel.label_panel.selection == order[2:7]


def test_gui_mouse_cmd_click_on_label(window, qtbot):
    from PySide6.QtCore import Qt

    c = window.canvas
    window.show()
    c.fit()
    name = window.tree.leaf_names()[3]
    item = c.result.leaf_items[name][0]
    pos = c.mapFromScene(item.sceneBoundingRect().center())
    qtbot.mouseClick(c.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, pos)
    assert c.selected == [name]
    qtbot.keyClick(c, Qt.Key.Key_Escape)
    assert c.selected == []


def test_gui_search_fills_selection_and_style(window):
    window.search_box.setText("xenovorans")
    window.do_search()
    sel = window.canvas.selected
    assert sel and all("xenovorans" in n.lower() for n in sel)
    menu = window.build_node_menu(next(n for n in window.display_tree.leaves() if n.name == sel[0]))
    titles = [a.text() for a in menu.actions()]
    assert any(t.startswith("Estilizar rótulos selecionados") for t in titles)
    g = window.style_panel.label_panel.style_leaves(sel, background="#b7e4a3")
    window.render_live()
    assert set(window.canvas.result.label_backgrounds) == set(sel)
    # mesmo estilo rápido de novo atualiza o grupo em vez de criar outro
    window.style_panel.label_panel.style_leaves(sel, text_color="#b22222")
    assert window.style_panel.label_groups.groups == [g]


def test_gui_selection_survives_rerender_not_exported(window, tmp_path):
    from jabuti.views.export import export_svg

    names = window.tree.leaf_names()[:3]
    window.canvas.set_selection(names)
    window.render_live()
    assert window.canvas.selected == names
    sel_items = [i for i in window.canvas.tree_scene.items() if i.data(0) == "selection"]
    assert len(sel_items) == 3
    out = export_svg(window.canvas.tree_scene, tmp_path / "x.svg")
    assert "#1971c2" not in out.read_text().lower()


def test_gui_pattern_count_and_group(window):
    lp = window.style_panel.label_panel
    lp.pattern.setText("^Paraburkholderia_x.*A00$")
    lp.regex.setChecked(True)
    assert lp.pattern_count.text() == "1 folha(s) casam"
    lp.pattern.setText("(")
    assert "inválida" in lp.pattern_count.text() and not lp.pattern_group.isEnabled()
    lp.pattern.setText("xenovorans")
    lp.regex.setChecked(False)
    lp.pattern_group.click()
    (g,) = window.style_panel.label_groups.groups
    assert g.source == "pattern" and g.name == "xenovorans"


def test_gui_conflict_shown_in_panel(window):
    lp = window.style_panel.label_panel
    names = window.tree.leaf_names()
    lp.create_group(names[:5], "selection")
    lp.create_group(names[3:8], "selection")
    window.render_live()
    assert lp.table.item(0, 2).text() == "3/5"
    assert lp.table.item(1, 2).text() == "5"
    assert "Seleção 2" in lp.describe_leaf(names[4]) and "Seleção 1" in lp.describe_leaf(names[4])


def test_gui_legend_lists_label_groups(window):
    lp = window.style_panel.label_panel
    lp.create_group(window.tree.leaf_names()[:2], "selection", name="Destaque")
    window.render_live()
    titles = [g.title for g in window.style_panel.legend.groups]
    assert "Grupos de rótulos" in titles
    lp.legend_cb.setChecked(False)
    window.render_live()
    assert "Grupos de rótulos" not in [g.title for g in window.style_panel.legend.groups]


def test_gui_preset_ignores_unknown_leaves(window):
    names = window.tree.leaf_names()
    gs = LabelGroupSet()
    gs.add([names[0], names[1], "Nao_existe_1", "Nao_existe_2"], "selection", "g1")
    gs.add(["So_fantasma"], "selection", "g2")
    loaded = preset_from_dict(preset_to_dict(RenderStyle(), label_groups=gs))
    warnings = window.apply_preset(loaded)
    window._report_preset("Preset carregado", warnings)
    (g,) = window.style_panel.label_groups.groups
    assert g.leaves == frozenset(names[:2])
    assert "3 folha(s) de grupos de rótulo ignoradas" in window.statusBar().currentMessage()
    # e o preset salvo de volta leva os grupos
    assert window.collect_preset()["label_groups"]["groups"][0]["name"] == "g1"
