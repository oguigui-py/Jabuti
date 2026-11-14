"""Layout circular com pontas alinhadas no anel externo."""

import math
import os

import pytest

from jabuti.layout.circular import circular_geometry, circular_layout, outer_ring_radius
from jabuti.parsers.newick import load_tree, parse_newick_string

GEOM = dict(font_size=10, leaf_spacing=1.6, base_width=600, branch_scale=1.0)


def geometry(tree, align=True, use_lengths=True):
    lay = circular_layout(tree, use_lengths)
    return lay, circular_geometry(lay, align_tips=align, **GEOM)


def test_all_leaves_end_on_same_radius(data_dir):
    lay, g = geometry(load_tree(data_dir / "iqtree_ufboot.treefile"))
    ends = {round(g.leaf_end_radius(lay, l), 9) for l in lay.leaf_order}
    assert ends == {round(g.tip_ring, 9)}


def test_branches_stay_proportional(data_dir):
    tree = load_tree(data_dir / "iqtree_ufboot.treefile")
    lay, g = geometry(tree)
    tips = [g.tip_radius(lay, l) for l in lay.leaf_order]
    assert len(set(round(t, 6) for t in tips)) > 1           # pontas reais diferentes
    assert max(tips) == pytest.approx(g.tip_ring)             # a mais longa toca o anel
    assert all(t <= g.tip_ring + 1e-9 for t in tips)
    for leaf in lay.leaf_order:                               # raio = profundidade × escala
        assert g.tip_radius(lay, leaf) == pytest.approx(lay.pos[leaf][0] * g.scale)


def test_unaligned_keeps_original_tips(data_dir):
    lay, g = geometry(load_tree(data_dir / "iqtree_ufboot.treefile"), align=False)
    for leaf in lay.leaf_order:
        assert g.leaf_end_radius(lay, leaf) == pytest.approx(g.tip_radius(lay, leaf))


def test_cladogram_tips_already_on_ring(data_dir):
    lay, g = geometry(load_tree(data_dir / "nolengths.nwk"), align=False)
    assert {round(g.tip_radius(lay, l), 9) for l in lay.leaf_order} == {round(g.tip_ring, 9)}


@pytest.mark.parametrize("how", ["midpoint", "A", "D", "F"])
def test_reroot_with_alignment(how):
    t = parse_newick_string("(A:0.1,(B:0.4,(C:0.05,D:0.9)80:0.2)90:0.1,(E:0.3,F:0.02)70:0.5);")
    t.reroot_midpoint() if how == "midpoint" else t.reroot_outgroup(how)
    lay, g = geometry(t)
    assert sorted(l.name for l in lay.leaf_order) == list("ABCDEF")
    ends = [g.leaf_end_radius(lay, l) for l in lay.leaf_order]
    assert max(ends) - min(ends) < 1e-9
    assert max(g.tip_radius(lay, l) for l in lay.leaf_order) == pytest.approx(g.tip_ring)


def test_outer_ring_radius_single_source():
    small = outer_ring_radius(10, 10, 1.6, 600, 1.0)
    big = outer_ring_radius(2000, 10, 1.6, 600, 1.0)
    assert big > small
    # reduzir a escala nunca faz os rótulos se sobreporem
    assert outer_ring_radius(2000, 10, 1.6, 600, 0.1) == pytest.approx(2000 * 16 / (2 * math.pi))


def test_annotation_rings_sit_outside_tip_ring(data_dir):
    lay = circular_layout(load_tree(data_dir / "small.nwk"))
    g = circular_geometry(lay, ring_widths=(12, 12), **GEOM)
    assert g.tip_ring < g.rings_start < g.rings_end < g.label_radius
    assert g.rings_end - g.rings_start == pytest.approx(12 + 12 + 2)


# ------------------------------------------------------------- renderização
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def rendered(qtbot, data_dir):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.style import LayoutKind, RenderStyle
    from jabuti.views.tree_renderer import TreeRenderer

    def _render(path="iqtree_ufboot.treefile", align=True):
        scene = QGraphicsScene()
        r = TreeRenderer(scene)
        res = r.render(load_tree(data_dir / path), RenderStyle(layout=LayoutKind.CIRCULAR, align_tips=align))
        return scene, r, res

    return _render


def _guides(scene):
    return [i for i in scene.items() if i.data(1) == "tip-guides"]


def _label_start_radius(item):
    from PySide6.QtCore import QPointF

    br = item.boundingRect()
    # rótulo invertido (metade esquerda) começa pela borda direita do texto
    x = br.width() if item.transformOriginPoint().x() > 0 else 0.0
    p = item.mapToScene(QPointF(x, br.height() / 2))
    return math.hypot(p.x(), p.y())


def test_render_aligned_labels_and_guides(rendered):
    from PySide6.QtCore import Qt

    scene, r, res = rendered()
    g = r.geometry
    dists = [math.hypot(p.x(), p.y()) for p in res.leaf_points.values()]
    assert max(dists) - min(dists) < 1e-6 and dists[0] == pytest.approx(g.tip_ring)
    starts = [_label_start_radius(items[0]) for items in res.leaf_items.values()]
    assert max(starts) - min(starts) < 1e-3
    assert starts[0] == pytest.approx(g.label_radius, abs=1e-3)
    (guide,) = _guides(scene)
    assert guide.pen().style() == Qt.PenStyle.CustomDashLine  # padrão: pontos pequenos
    assert list(guide.pen().dashPattern()) == [1.0, 2.0]
    # uma linha por folha que não toca o anel (a mais longa toca)
    assert guide.path().elementCount() == 2 * (len(res.leaf_items) - 1)


def test_render_unaligned_has_no_guides(rendered):
    scene, r, res = rendered(align=False)
    assert _guides(scene) == []
    dists = {round(math.hypot(p.x(), p.y()), 3) for p in res.leaf_points.values()}
    assert len(dists) > 1


def test_cladogram_render_has_no_guides(rendered):
    scene, _, _ = rendered("nolengths.nwk")
    assert _guides(scene) == []


@pytest.mark.parametrize("fmt", ["svg", "pdf", "png"])
def test_export_includes_guides(rendered, tmp_path, fmt):
    from jabuti.views import export

    scene, _, _ = rendered()
    out = getattr(export, f"export_{fmt}")(scene, tmp_path / f"t.{fmt}")
    assert out.stat().st_size > 0
    if fmt == "svg":
        text = out.read_text()
        assert "stroke-dasharray" in text and "#a0a0a0" in text.lower()
