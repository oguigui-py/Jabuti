"""Fundos dos nomes terminam todos juntos: arco contínuo (circular/leque), borda reta (retangular)."""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from jabuti.models.clades import Clade  # noqa: E402
from jabuti.parsers.newick import parse_newick_string  # noqa: E402
from jabuti.style import LayoutKind, RenderStyle  # noqa: E402

# nomes de 1 a 60 caracteres, em clados de cores diferentes (vizinhos e isolados)
NAMES = ["A", "Bb", "C" * 60, "Dddd", "E" * 35, "F", "G" * 48, "Hh", "I" * 12, "J" * 55, "K", "L" * 25]
_L = {n: f"{n}:{0.1 + 0.05 * (i % 4)}" for i, n in enumerate(NAMES)}
NWK = (f"(({_L['A']},{_L['Bb']},{_L['C' * 60]}):0.1,({_L['Dddd']},{_L['E' * 35]}):0.2,{_L['F']},{_L['G' * 48]},"
       f"{_L['Hh']},(({_L['I' * 12]},{_L['J' * 55]}):0.1,({_L['K']},{_L['L' * 25]}):0.05):0.1);")
CLADES = [Clade("um", frozenset(NAMES[0:3]), "#4e79a7"), Clade("dois", frozenset(NAMES[3:5]), "#f28e2b"),
          Clade("tres", frozenset(NAMES[6:7]), "#59a14f"), Clade("quatro", frozenset(NAMES[8:12]), "#e15759")]
TOL = 0.5


@pytest.fixture
def render(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    def _render(layout, align=True, merge=True, gap=None, strip=False):  # type: ignore[no-untyped-def]
        scene = QGraphicsScene()
        st = RenderStyle(layout=layout)
        st.align_tips = align
        st.merge_backgrounds = merge
        st.clades.outer_strip = strip
        if gap is not None:
            st.clades.label_background_gap = gap
        res = TreeRenderer(scene).render(parse_newick_string(NWK), st, CLADES)
        return scene, res

    return _render


def _bgs(res):  # type: ignore[no-untyped-def]
    return list({id(b): b for b in res.label_backgrounds.values()}.values())


def _radii(item):  # type: ignore[no-untyped-def]
    pts = item.mapToScene(item.path().toFillPolygon())
    d = [math.hypot(p.x(), p.y()) for p in pts]
    return min(d), max(d)


CIRC = [(LayoutKind.CIRCULAR, True, True), (LayoutKind.FAN, True, True), (LayoutKind.CIRCULAR, False, True),
        (LayoutKind.CIRCULAR, True, False), (LayoutKind.FAN, False, False)]


@pytest.mark.parametrize("layout,align,merge", CIRC)
def test_circular_blocks_share_outer_radius(render, layout, align, merge):
    _scene, res = render(layout, align, merge)
    bgs = _bgs(res)
    assert len(bgs) >= 4
    outers = [_radii(b)[1] for b in bgs]
    assert max(outers) - min(outers) < TOL, outers
    # passa do fim do texto mais longo
    text_end = max(max(math.hypot(p.x(), p.y()) for p in it[0].mapToScene(it[0].boundingRect()))
                   for it in res.leaf_items.values())
    assert min(outers) > text_end


@pytest.mark.parametrize("layout", [LayoutKind.CIRCULAR, LayoutKind.FAN])
def test_aligned_tips_share_inner_radius(render, layout):
    _scene, res = render(layout)
    inners = [_radii(b)[0] for b in _bgs(res)]
    assert max(inners) - min(inners) < TOL, inners


def test_gap_is_configurable(render):
    s1, a = render(LayoutKind.CIRCULAR, gap=4.0)
    s2, b = render(LayoutKind.CIRCULAR, gap=10.0)
    assert _radii(_bgs(b)[0])[1] - _radii(_bgs(a)[0])[1] == pytest.approx(6.0, abs=TOL)
    s3, r4 = render(LayoutKind.RECTANGULAR, gap=4.0)
    s4, r0 = render(LayoutKind.RECTANGULAR, gap=0.0)
    assert _bgs(r4)[0].sceneBoundingRect().right() - _bgs(r0)[0].sceneBoundingRect().right() == pytest.approx(4.0)


@pytest.mark.parametrize("layout,merge", [(LayoutKind.RECTANGULAR, True), (LayoutKind.RECTANGULAR, False),
                                          (LayoutKind.SLANTED, True)])
def test_rectangular_blocks_share_right_edge(render, layout, merge):
    _scene, res = render(layout, merge=merge)
    rights = [b.sceneBoundingRect().right() for b in _bgs(res)]
    assert max(rights) - min(rights) < 1e-6, rights
    text_end = max(it[0].sceneBoundingRect().right() for it in res.leaf_items.values())
    assert min(rights) >= text_end + 4.0 - 1e-6


@pytest.mark.parametrize("layout", [LayoutKind.CIRCULAR, LayoutKind.RECTANGULAR])
def test_outer_layers_start_after_the_backgrounds(render, layout):
    from jabuti.views.tree_renderer import TAG_CLADE_STRIP

    scene, res = render(layout, align=False, strip=True)
    strips = [i for i in scene.items() if i.data(1) == TAG_CLADE_STRIP]
    assert strips
    if layout == LayoutKind.RECTANGULAR:
        edge = max(b.sceneBoundingRect().right() for b in _bgs(res))
        assert min(s.sceneBoundingRect().left() for s in strips) >= edge
    else:
        edge = max(_radii(b)[1] for b in _bgs(res))
        assert min(_radii(s)[0] for s in strips) >= edge - TOL


def test_gap_in_panel_and_presets(qtbot):
    from jabuti.presets import style_from_dict, style_to_dict
    from jabuti.views.style_panel import StylePanel

    assert RenderStyle().clades.label_background_gap == 4.0
    st = RenderStyle()
    st.clades.label_background_gap = 9.0
    assert style_from_dict(style_to_dict(st)).clades.label_background_gap == 9.0
    assert style_from_dict({"clades": {}}).clades.label_background_gap == 4.0      # presets antigos
    panel = StylePanel()
    qtbot.addWidget(panel)
    panel.load_style(st)
    assert panel.label_bg_gap.value() == 9.0
    panel.label_bg_gap.setValue(2.0)
    assert panel.apply_to(RenderStyle()).clades.label_background_gap == 2.0
