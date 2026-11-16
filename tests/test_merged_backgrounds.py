"""Fundos vizinhos (rótulos, clados, destaques de linha) sem vão branco entre grupos."""

import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.clades import Clade  # noqa: E402
from jabuti.models.document import RowHighlight, TreeEdits, apply_edits  # noqa: E402
from jabuti.models.label_groups import LabelGroupSet, LabelLook  # noqa: E402
from jabuti.parsers.newick import parse_newick_string  # noqa: E402
from jabuti.style import LayoutKind, RenderStyle  # noqa: E402
from jabuti.views.background_blocks import blocks  # noqa: E402

T = "(((A:1,B:1):1,(C:1,D:1):1):1,((E:1,F:1):1,(G:1,H:1):1):1);"
YEL, BLUE, PINK = "#ffe066", "#a5d8ff", "#ffc9c9"
RADIAL = (LayoutKind.CIRCULAR, LayoutKind.FAN)


# ------------------------------------------------------------------ função pura
def test_blocks_group_same_key_and_flag_neighbors():
    keys = {"A": 1, "B": 1, "C": 2, "D": None, "E": 2, "F": 2}
    out = blocks(list("ABCDEF"), keys.get)
    assert [b.tips for b in out] == [["A", "B"], ["C"], ["E", "F"]]
    assert (out[0].before, out[0].after) == (False, True)
    assert (out[1].before, out[1].after) == (True, False)       # D (sem fundo) separa C de E
    assert (out[2].before, out[2].after) == (False, False)


def test_blocks_respect_adjacency():
    out = blocks(list("AB"), lambda _t: 1, adjacent=lambda a, b: False)
    assert [b.tips for b in out] == [["A"], ["B"]] and not out[1].before


# ------------------------------------------------------------------ desenho
def groups(*specs):
    gs = LabelGroupSet()
    for leaves, color, alpha in specs:
        gs.add(leaves, "selection", look=LabelLook(background=color, background_alpha=alpha))
    return gs


@pytest.fixture
def draw(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    keep = []

    def _draw(layout=LayoutKind.RECTANGULAR, merge=True, tree=None, **kw):
        scene = QGraphicsScene()
        style = RenderStyle(layout=layout, merge_backgrounds=merge)
        for k in ("background", "background_alpha"):
            if f"clade_{k}" in kw:
                setattr(style.clades, k, kw.pop(f"clade_{k}"))
        if kw.pop("aligned", False):
            style.use_lengths = False                           # cladograma: rótulos alinhados
        renderer = TreeRenderer(scene)
        res = renderer.render(tree or parse_newick_string(T), style, **kw)
        res.geometry = renderer.geometry
        keep.append(scene)
        return scene, res

    return _draw


def tagged(scene, tag):
    return [i for i in scene.items() if i.data(1) == tag]


def pixel(scene, point, scale=4.0):
    """Cor do pixel da cena em ``point`` (renderizado como no export PNG)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    src = scene.sceneRect()
    img = QImage(int(src.width() * scale), int(src.height() * scale), QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(p, QRectF(0, 0, img.width(), img.height()), src)
    p.end()
    return img, (lambda q: QColor(img.pixel(int((q.x() - src.left()) * scale), int((q.y() - src.top()) * scale))))


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.SLANTED, *RADIAL])
def test_same_color_neighbors_one_block_uniform_opacity(draw, layout):
    scene, res = draw(layout, aligned=True, label_groups=groups(("AB", YEL, 0.5), ("CD", YEL, 0.5)))
    items = tagged(scene, "label-background")
    assert len(items) == 1                                      # um bloco único para A–D
    (block,) = items
    assert block.brush().color().alphaF() == pytest.approx(0.5, abs=0.01)
    assert all(res.label_backgrounds[n] is block for n in "ABCD")
    assert block.path().fillRule().name == "WindingFill"
    if layout in RADIAL:
        return
    # na margem à esquerda do texto: a cor na divisa B|C é a mesma do meio da linha B
    # (sem emenda clara e sem opacidade dobrada onde as partes do bloco se encontram)
    _img, at = pixel(scene, None)
    b, c = (res.leaf_items[n][0].sceneBoundingRect() for n in "BC")
    from PySide6.QtCore import QPointF

    x = b.left() - 1
    row = at(QPointF(x, b.center().y())).name()
    seam = at(QPointF(x, (b.center().y() + c.center().y()) / 2)).name()
    assert row == seam != "#ffffff"


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.SLANTED])
def test_different_colors_touch_at_midpoint_rect(draw, layout):
    scene, res = draw(layout, label_groups=groups(("AB", YEL, 1.0), ("CD", BLUE, 1.0)))
    yel, blue = res.label_backgrounds["A"], res.label_backgrounds["C"]
    assert yel is not blue
    b, c = (res.leaf_items[n][0].sceneBoundingRect() for n in "BC")
    mid = (b.center().y() + c.center().y()) / 2
    assert yel.sceneBoundingRect().bottom() == pytest.approx(mid)
    assert blue.sceneBoundingRect().top() <= mid                # distância zero (avança sob a divisa)
    assert mid - blue.sceneBoundingRect().top() < 0.5


@pytest.mark.parametrize("layout", RADIAL)
def test_different_colors_touch_at_mid_angle_radial(draw, layout):
    from PySide6.QtCore import QPointF

    scene, res = draw(layout, label_groups=groups(("AB", YEL, 1.0), ("CD", BLUE, 1.0)))
    yel, blue = res.label_backgrounds["A"], res.label_backgrounds["C"]
    pb, pc = res.leaf_items["B"][0].sceneBoundingRect().center(), res.leaf_items["C"][0].sceneBoundingRect().center()
    tb, tc = math.atan2(pb.y(), pb.x()), math.atan2(pc.y(), pc.x())
    mid = (tb + tc) / 2
    r = min(math.hypot(pb.x(), pb.y()), math.hypot(pc.x(), pc.y()))
    for eps, item in ((-1e-3, yel), (1e-3, blue)):              # dos dois lados da divisa radial
        th = mid + (eps if tc > tb else -eps)
        q = QPointF(r * math.cos(th), r * math.sin(th))
        assert item.contains(item.mapFromScene(q))


def _no_white_across(scene, res, a: str, b: str, radial: bool) -> None:
    """Ao longo da divisa entre os rótulos ``a`` e ``b``, nenhum pixel branco."""
    from PySide6.QtCore import QPointF

    _img, at = pixel(scene, None)
    ra, rb = (res.leaf_items[n][0].sceneBoundingRect() for n in (a, b))
    if radial:
        pa, pb = res.leaf_points[a], res.leaf_points[b]
        ta, tb = math.atan2(pa.y(), pa.x()), math.atan2(pb.y(), pb.x())
        th = (ta + tb) / 2
        r0 = res.geometry.label_radius + 1                     # dentro dos dois fundos (rótulos curtos)
        width = min(r.width() for r in (ra, rb)) * 0.6
        pts = [QPointF((r0 + width * k / 20) * math.cos(th), (r0 + width * k / 20) * math.sin(th))
               for k in range(21)]
    else:
        y = (ra.center().y() + rb.center().y()) / 2
        x0, x1 = max(ra.left(), rb.left()) + 1, min(ra.right(), rb.right()) - 1
        pts = [QPointF(x0 + (x1 - x0) * k / 40, y) for k in range(41)]
    whites = [p for p in pts if at(p).name() == "#ffffff"]
    assert not whites, whites[:3]


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
@pytest.mark.parametrize("alpha", [1.0, 0.4])
def test_png_no_white_seam_label_backgrounds(draw, layout, alpha):
    scene, res = draw(layout, label_groups=groups(("AB", YEL, alpha), ("CD", BLUE, alpha)))
    _no_white_across(scene, res, "B", "C", layout == LayoutKind.CIRCULAR)
    _no_white_across(scene, res, "A", "B", layout == LayoutKind.CIRCULAR)


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_png_no_white_seam_clades_and_highlights(draw, layout):
    clades = [Clade("x", frozenset("ABCD"), YEL), Clade("y", frozenset("EFGH"), BLUE)]
    scene, res = draw(layout, clades=clades, clade_background=True, clade_background_alpha=0.3)
    _no_white_across(scene, res, "D", "E", layout == LayoutKind.CIRCULAR)
    _no_white_across(scene, res, "C", "D", layout == LayoutKind.CIRCULAR)
    hl = [RowHighlight(frozenset("AB"), YEL, 0.5, None), RowHighlight(frozenset("CD"), BLUE, 0.5, None)]
    scene, res = draw(layout, highlights=hl)
    _no_white_across(scene, res, "B", "C", layout == LayoutKind.CIRCULAR)


def test_same_color_clades_one_path(draw):
    clades = [Clade("x", frozenset("AB"), YEL), Clade("y", frozenset("CD"), YEL), Clade("z", frozenset("EF"), BLUE)]
    scene, _res = draw(clades=clades, clade_background=True)
    colors = sorted(i.brush().color().name() for i in tagged(scene, "clade-background"))
    assert colors == [BLUE, YEL]                                # x e y viraram um caminho só
    scene, _res = draw(clades=clades, clade_background=True, merge=False)
    assert len(tagged(scene, "clade-background")) == 3


def test_highlights_last_wins_and_same_style_merge(draw):
    hl = [RowHighlight(frozenset("ABC"), YEL, 0.5), RowHighlight(frozenset("CD"), YEL, 0.5),
          RowHighlight(frozenset("D"), BLUE, 0.5)]
    scene, _res = draw(highlights=hl)
    items = tagged(scene, "row-highlight")
    assert sorted(i.brush().color().name() for i in items) == [BLUE, YEL]   # A–C num bloco, D azul


def test_separated_groups_keep_gap_and_round_corners(draw):
    scene, res = draw(label_groups=groups(("AB", YEL, 1.0), ("DE", YEL, 1.0)))   # C sem fundo
    a, d = res.label_backgrounds["A"], res.label_backgrounds["D"]
    assert a is not d
    assert a.sceneBoundingRect().bottom() < d.sceneBoundingRect().top()
    c = res.leaf_items["C"][0].sceneBoundingRect()
    _img, at = pixel(scene, None)
    assert at(c.center()).name() != YEL                         # a linha de C fica sem fundo


def test_isolated_leaf_unchanged(draw):
    s1, r1 = draw(label_groups=groups(("C", YEL, 1.0)))
    s2, r2 = draw(label_groups=groups(("C", YEL, 1.0)), merge=False)
    assert r1.label_backgrounds["C"].sceneBoundingRect() == r2.label_backgrounds["C"].sceneBoundingRect()
    assert r1.label_backgrounds["C"].rotation() == r2.label_backgrounds["C"].rotation()


def test_option_off_one_background_per_leaf(draw):
    scene, res = draw(merge=False, label_groups=groups(("ABCD", YEL, 1.0)))
    assert len(tagged(scene, "label-background")) == 4
    assert len({id(b) for b in res.label_backgrounds.values()}) == 4


def test_collapsed_breaks_and_hidden_joins(draw):
    gs = groups(("ABEF", YEL, 1.0))
    tree = parse_newick_string("((A:1,B:1):1,((C:1,D:1):1,(E:1,F:1):1):1);")
    scene, res = draw(tree=tree, label_groups=gs, collapsed=[frozenset("CD")])
    assert res.label_backgrounds["B"] is not res.label_backgrounds["E"]   # triângulo ocupa a linha
    shown = apply_edits(tree, TreeEdits(hidden={"C", "D"}))
    scene, res = draw(tree=shown, label_groups=gs, hidden={"C", "D"})
    assert res.label_backgrounds["B"] is res.label_backgrounds["E"]       # ocultas: viram vizinhas


def test_svg_single_path_per_block(draw, tmp_path):
    from jabuti.views.export import export_svg

    scene, _res = draw(label_groups=groups(("ABCD", YEL, 1.0)))
    svg = export_svg(scene, tmp_path / "b.svg").read_text(encoding="utf-8").lower()
    assert svg.count(f'fill="{YEL}"') == 1                      # um <path>, nenhum retângulo vizinho
    scene, _res = draw(label_groups=groups(("ABCD", YEL, 1.0)), merge=False)
    svg = export_svg(scene, tmp_path / "c.svg").read_text(encoding="utf-8").lower()
    assert svg.count(f'fill="{YEL}"') == 4


def test_preset_old_opens_with_merge_and_roundtrip():
    from jabuti.presets import preset_from_dict, preset_to_dict

    assert preset_from_dict({"version": 1, "style": {"background": "#ffffff"}}).style.merge_backgrounds is True
    st = RenderStyle(merge_backgrounds=False)
    assert preset_from_dict(preset_to_dict(st)).style.merge_backgrounds is False


# ------------------------------------------------------------------ GUI
@pytest.fixture
def window(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    win = MainWindow()
    qtbot.addWidget(win)
    win.tree_tab.load("examples/paraburkholderia_40.treefile")
    return win


def test_gui_click_on_shared_block_picks_nearest_leaf(window):
    from PySide6.QtCore import QPointF

    names = window.tree.leaf_names()[2:6]
    window.style_panel.label_panel.create_group(names, "selection")
    window.render_live()
    res = window.canvas.result
    assert len({id(res.label_backgrounds[n]) for n in names}) == 1
    target = res.leaf_items[names[2]][0].sceneBoundingRect()
    leaf_y = res.leaf_points[names[2]].y()
    # no fundo compartilhado, à direita do texto e na altura da folha (não na borda do texto:
    # sem fontes a caixa do texto tem altura zero e a borda cai na divisa entre duas folhas)
    pt = QPointF(target.right() + 0.5, leaf_y)
    view = window.canvas.mapFromScene(pt)
    assert window.canvas.leaf_at(view) == names[2]
    window.canvas.set_selection([names[1]])
    (outline,) = window.canvas._sel_items
    assert outline.sceneBoundingRect().height() < res.label_backgrounds[names[1]].sceneBoundingRect().height()


def test_gui_option_toggles(window):
    sp = window.style_panel
    names = window.tree.leaf_names()[2:6]
    sp.label_panel.create_group(names, "selection")
    window.render_live()
    assert len(tagged(window.canvas.tree_scene, "label-background")) == 1
    sp.merge_bgs.setChecked(False)
    window.render_live()
    assert len(tagged(window.canvas.tree_scene, "label-background")) == 4
    assert window.collect_preset()["style"]["merge_backgrounds"] is False


def test_click_in_shared_block_beside_short_name_next_to_long_name(qtbot):
    """Clique logo à direita de um nome curto, com um nome bem mais longo na linha vizinha:
    escolhe a folha da linha clicada (antes, o centro do nome longo ficava mais perto)."""
    from PySide6.QtCore import QPointF

    from jabuti.parsers.newick import parse_newick_string
    from jabuti.views.canvas import TreeCanvas
    from jabuti.views.tree_renderer import TreeRenderer

    long_name = "Nome_muito_muito_muito_comprido_de_especie_" + "x" * 30
    tree = parse_newick_string(f"(({long_name}:1,Curto:1):1,Outro:2);")
    canvas = TreeCanvas()
    qtbot.addWidget(canvas)
    gs = groups(({long_name, "Curto"}, "#ffd43b", 0.6))
    res = TreeRenderer(canvas.tree_scene).render(tree, RenderStyle(), label_groups=gs)
    canvas.result = res
    assert res.label_backgrounds["Curto"] is res.label_backgrounds[long_name]
    short = res.leaf_items["Curto"][0].sceneBoundingRect()
    pt = QPointF(short.right() + 3 * short.width(), res.leaf_points["Curto"].y())   # no fundo, linha do Curto
    assert res.label_backgrounds["Curto"].contains(res.label_backgrounds["Curto"].mapFromScene(pt))
    assert canvas.leaf_at(canvas.mapFromScene(pt)) == "Curto"
