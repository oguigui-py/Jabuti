"""Rótulos (fonte), símbolos nas pontas, suporte como símbolos e barra de escala."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.clades import Clade  # noqa: E402
from jabuti.parsers.newick import load_tree, parse_newick_string  # noqa: E402
from jabuti.style import (  # noqa: E402
    LabelStyle,
    LayoutKind,
    RenderStyle,
    ScaleBarStyle,
    SupportStyle,
    SymbolStyle,
)

BIN = "((((A:1,B:1)95/99:1,C:2)60/80:1,(D:1,E:1)99/100:3)90/97:1,(F:1,(G:1,H:1)40/50:1)85/96:2);"


@pytest.fixture
def draw(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    keep = []

    def _draw(style: RenderStyle, clades=None, newick=BIN):
        scene = QGraphicsScene()
        r = TreeRenderer(scene)
        res = r.render(parse_newick_string(newick), style, clades)
        keep.append((scene, r))
        return scene, res, r

    return _draw


def tagged(scene, tag):
    return [i for i in scene.items() if i.data(1) == tag]


def test_italic_by_default_and_bold(draw):
    _, res, _ = draw(RenderStyle())
    f = res.leaf_items["A"][0].font()
    assert f.italic() and not f.bold()
    _, res, _ = draw(RenderStyle(label=LabelStyle(bold=True, italic=False, size=14)))
    f = res.leaf_items["A"][0].font()
    assert f.bold() and not f.italic() and f.pointSizeF() == 14


def test_font_family_applied(draw):
    from PySide6.QtGui import QFontDatabase

    family = QFontDatabase.families()[0]
    _, res, _ = draw(RenderStyle(label=LabelStyle(family=family)))
    assert res.leaf_items["A"][0].font().family() == family


def test_scale_label_not_italic(draw):
    scene, _, _ = draw(RenderStyle())
    texts = [i for i in tagged(scene, "scale-bar") if hasattr(i, "font")]
    assert texts and not texts[0].font().italic()


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_hide_labels(draw, layout):
    _, res, _ = draw(RenderStyle(layout=layout, label=LabelStyle(show=False)))
    assert res.leaf_items == {}
    assert len(res.leaf_points) == 8


@pytest.mark.parametrize("shape", ["circle", "square", "diamond"])
@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_tip_symbols(draw, shape, layout):
    scene, _, _ = draw(RenderStyle(layout=layout, symbols=SymbolStyle(shape=shape, size=8, color="#123456")))
    (item,) = tagged(scene, "tip-symbol")
    assert item.brush().color().name() == "#123456"
    assert item.path().boundingRect().width() > 0


def test_tip_symbols_none(draw):
    scene, _, _ = draw(RenderStyle())
    assert tagged(scene, "tip-symbol") == []


def test_tip_symbols_use_clade_color(draw):
    scene, _, _ = draw(RenderStyle(symbols=SymbolStyle(shape="circle", color="#000000")),
                       [Clade("ab", frozenset("AB"), color="#ff0000")])
    colors = {i.brush().color().name() for i in tagged(scene, "tip-symbol")}
    assert colors == {"#ff0000", "#000000"}


def test_tip_symbol_pushes_circular_labels_out(draw):
    _, _, r0 = draw(RenderStyle(layout=LayoutKind.CIRCULAR))
    _, _, r1 = draw(RenderStyle(layout=LayoutKind.CIRCULAR, symbols=SymbolStyle(shape="circle", size=10)))
    assert r1.geometry.tip_ring == pytest.approx(r0.geometry.tip_ring)
    assert r1.geometry.label_radius == pytest.approx(r0.geometry.label_radius + 5)


def test_support_symbols_filled_vs_hollow(draw):
    scene, _, _ = draw(RenderStyle(support=SupportStyle(mode="symbols", index=1, threshold=95, color="#333333")))
    items = tagged(scene, "support-symbol")
    fills = {i.brush().color().name(): i.path().elementCount() for i in items}
    assert set(fills) == {"#333333", "#ffffff"}  # cheios (>=95) e vazados
    # UFBoot >= 95: (AB)=99, (DE)=100, (ABCDE)=97, (FGH)=96 -> 4 cheios; 80 e 50 -> 2 vazados
    filled = next(i for i in items if i.brush().color().name() == "#333333")
    hollow = next(i for i in items if i.brush().color().name() == "#ffffff")
    n_ellipse = lambda it: len([e for e in range(it.path().elementCount()) if it.path().elementAt(e).isMoveTo()])  # noqa: E731
    assert n_ellipse(filled) == 4 and n_ellipse(hollow) == 2


def test_support_symbol_size_by_value(draw):
    scene, _, _ = draw(RenderStyle(support=SupportStyle(mode="symbols", index=1, size_by_value=True, symbol_size=10)))
    full = next(i for i in tagged(scene, "support-symbol"))
    sizes = set()
    path = full.path()
    for poly in path.toSubpathPolygons():
        sizes.add(round(poly.boundingRect().width(), 1))
    assert len(sizes) > 1 and max(sizes) <= 10.01


def test_support_numbers_threshold(draw):
    scene, _, _ = draw(RenderStyle(support=SupportStyle(mode="numbers", index=1, threshold=96)))
    texts = sorted(i.text() for i in scene.items()
                   if hasattr(i, "text") and i.text().isdigit() and i.data(1) != "scale-bar")
    assert texts == ["100", "96", "97", "99"]
    assert tagged(scene, "support-symbol") == []


@pytest.mark.parametrize("pos", ["bottom-left", "bottom-right", "top-left", "top-right"])
def test_scale_bar_positions(draw, pos):
    scene, _, _ = draw(RenderStyle(scale_bar=ScaleBarStyle(position=pos)))
    bar = next(i for i in tagged(scene, "scale-bar") if not hasattr(i, "text"))
    tree_items = [i for i in scene.items() if i.data(1) == "branches"]
    tree_box = tree_items[0].sceneBoundingRect()
    for it in tree_items[1:]:
        tree_box = tree_box.united(it.sceneBoundingRect())
    b = bar.sceneBoundingRect()
    if pos.startswith("top"):
        assert b.bottom() < tree_box.top()
    else:
        assert b.top() > tree_box.bottom()
    center_x = b.center().x()
    if pos.endswith("left"):
        assert center_x < tree_box.center().x()
    else:
        assert center_x > tree_box.center().x() - 1


def test_scale_bar_custom_length_and_hide(draw):
    scene, _, _ = draw(RenderStyle(scale_bar=ScaleBarStyle(length=2.0)))
    texts = [i.text() for i in tagged(scene, "scale-bar") if hasattr(i, "text")]
    assert texts == ["2"]
    scene, _, _ = draw(RenderStyle(scale_bar=ScaleBarStyle(show=False)))
    assert tagged(scene, "scale-bar") == []


def test_svg_export_keeps_italic_and_symbols(draw, tmp_path):
    from jabuti.views.export import export_svg

    scene, _, _ = draw(RenderStyle(layout=LayoutKind.CIRCULAR,
                                   symbols=SymbolStyle(shape="diamond", color="#0a0b0c"),
                                   support=SupportStyle(mode="symbols", color="#0d0e0f")))
    txt = export_svg(scene, tmp_path / "s.svg").read_text(encoding="utf-8").lower()
    assert 'font-style="italic"' in txt
    assert "#0a0b0c" in txt and "#0d0e0f" in txt


def test_panel_label_controls(qtbot):
    from jabuti.views.style_panel import StylePanel

    sp = StylePanel()
    qtbot.addWidget(sp)
    sp.set_tree(load_tree("tests/data/iqtree_ufboot.treefile"))
    st = sp.apply_to(RenderStyle())
    assert st.label.italic and st.support.mode == "none"
    sp.font_bold.setChecked(True)
    sp.font_italic.setChecked(False)
    sp.tip_shape.setCurrentIndex(sp.tip_shape.findData("square"))
    sp.support_mode.setCurrentIndex(sp.support_mode.findData("symbols"))
    sp.scale_pos.setCurrentIndex(sp.scale_pos.findData("top-right"))
    sp.scale_auto.setChecked(False)
    sp.scale_len.setValue(0.02)
    st = sp.apply_to(RenderStyle())
    assert st.label.bold and not st.label.italic
    assert st.symbols.shape == "square" and st.support.mode == "symbols" and st.support.index == 1
    assert st.scale_bar.position == "top-right" and st.scale_bar.length == pytest.approx(0.02)


def test_panel_support_disabled_without_supports(qtbot):
    from jabuti.views.style_panel import StylePanel

    sp = StylePanel()
    qtbot.addWidget(sp)
    sp.set_tree(load_tree("tests/data/small.nwk"))
    assert not sp.support_mode.isEnabled()
    assert sp.apply_to(RenderStyle()).support.mode == "none"


def test_font_default_is_system(qtbot):
    from jabuti.views.style_panel import StylePanel

    sp = StylePanel()
    qtbot.addWidget(sp)
    assert sp.font_family.currentText() == "Padrão do sistema"
    assert sp.apply_to(RenderStyle()).label.family == ""
    sp.font_family.setCurrentIndex(1)
    assert sp.apply_to(RenderStyle()).label.family == sp.font_family.itemText(1)
