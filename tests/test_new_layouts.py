"""Etapa 5: layouts leque, diagonal e não enraizado."""

import itertools
import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.layout.unrooted import unrooted_layout  # noqa: E402
from jabuti.models.document import TreeEdits, apply_edits  # noqa: E402
from jabuti.parsers.newick import load_tree, parse_newick_string  # noqa: E402
from jabuti.style import LayoutKind, RenderStyle  # noqa: E402

EX = "examples/paraburkholderia_40.treefile"
T = "((A:1,B:2)90:1,(C:1,(D:1,E:3)80:1)70:2);"


def _cross(p1, p2, p3, p4) -> bool:
    def o(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    return o(p3, p4, p1) * o(p3, p4, p2) < -1e-12 and o(p1, p2, p3) * o(p1, p2, p4) < -1e-12


def crossings(lay) -> int:
    segs = [(n, lay.pos[n.parent], lay.pos[n]) for n in lay.pos if n.parent is not None]
    n = 0
    for (a, p1, p2), (b, p3, p4) in itertools.combinations(segs, 2):
        if a.parent is b or b.parent is a or a.parent is b.parent:
            continue
        n += _cross(p1, p2, p3, p4)
    return n


def spread(lay) -> float:
    pts = [lay.pos[l] for l in lay.leaf_order]
    return sum(min(math.dist(a, b) for b in pts if b is not a) for a in pts) / len(pts)


# ------------------------------------------------------------ não enraizada
@pytest.mark.parametrize("path", [EX, "tests/data/iqtree_ufboot.treefile", "tests/data/small.nwk"])
def test_equal_angle_no_crossings_and_daylight_not_worse(path):
    t = load_tree(path)
    ea = unrooted_layout(t)
    dl = unrooted_layout(t, daylight=True)
    assert crossings(ea) == 0 and crossings(dl) == 0
    assert spread(dl) >= spread(ea) * 0.999


def test_branch_lengths_proportional():
    t = parse_newick_string(T)
    lay = unrooted_layout(t)
    for n in lay.pos:
        if n.parent is not None:
            assert math.dist(lay.pos[n], lay.pos[n.parent]) == pytest.approx(n.length)
    clad = unrooted_layout(t, use_lengths=False)
    assert all(math.dist(clad.pos[n], clad.pos[n.parent]) == pytest.approx(1)
               for n in clad.pos if n.parent is not None)


def test_rotation_and_mirror():
    t = parse_newick_string(T)
    base = unrooted_layout(t)
    rot = unrooted_layout(t, rotation=90)
    mir = unrooted_layout(t, mirror=True)
    for n, (x, y) in base.pos.items():
        rx, ry = rot.pos[n]
        assert (rx, ry) == pytest.approx((-y, x), abs=1e-9)
        assert mir.pos[n] == pytest.approx((x, -y), abs=1e-9)


def test_unrooted_collapsed_counts_as_tip():
    from jabuti.models.document import collapsed_nodes

    t = parse_newick_string(T)
    nodes = collapsed_nodes(t, TreeEdits(collapsed=[frozenset("DE")]))
    lay = unrooted_layout(t, collapsed=nodes)
    assert sorted(l.name for l in lay.leaf_order) == ["A", "B", "C"]
    (node,) = nodes
    assert lay.collapsed[node] == pytest.approx(3)


# ------------------------------------------------------------ desenho
@pytest.fixture
def draw(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    keep = []

    def _draw(tree, style, **kw):
        scene = QGraphicsScene()
        r = TreeRenderer(scene)
        res = r.render(tree, style, **kw)
        keep.append(scene)
        return scene, r, res

    return _draw


def tagged(scene, tag):
    return [i for i in scene.items() if i.data(1) == tag]


@pytest.mark.parametrize("angle,start", [(180, 0), (270, 135), (90, 300)])
def test_fan_rings_aligned_and_nothing_in_gap(draw, angle, start):
    from jabuti.models.tracks import bar_track

    t = load_tree(EX)
    st = RenderStyle(layout=LayoutKind.FAN)
    st.fan.angle, st.fan.start = angle, start
    cols = [bar_track("bar:x", "tamanho", {n: 1.0 for n in t.leaf_names()})]
    scene, r, res = draw(t, st, columns=cols)
    g = r.geometry
    assert g.tip_ring < g.ring_bounds(0)[0] < g.label_radius
    a0, a1 = math.radians(start), math.radians(start + angle)
    for item in tagged(scene, "bar"):                     # nada no vão
        for poly in item.path().toSubpathPolygons():
            for p in poly:
                th = (math.atan2(p.y(), p.x()) - a0) % (2 * math.pi)
                assert th <= (a1 - a0) + 1e-6 or math.hypot(p.x(), p.y()) < 1e-6
    # rótulos vizinhos não se sobrepõem no leque: a corda entre folhas vizinhas no raio dos
    # rótulos é pelo menos a altura do texto (o raio cresce quando o arco diminui)
    h = max(it.boundingRect().height() for items in res.leaf_items.values() for it in items)
    n = len(res.leaf_items)
    chord = 2 * g.label_radius * math.sin(math.radians(angle) / n / 2)
    assert chord >= h * 0.95
    assert tagged(scene, "column-header")                 # nome da coluna no vão


def test_fan_smaller_arc_bigger_radius(draw):
    t = load_tree(EX)
    radii = {}
    for angle in (360, 90):
        st = RenderStyle(layout=LayoutKind.FAN if angle < 360 else LayoutKind.CIRCULAR)
        st.fan.angle = angle
        _s, r, _res = draw(t, st)
        radii[angle] = r.geometry.tip_ring
    assert radii[90] > radii[360]


def test_slanted_edges_are_diagonal_and_columns_right(draw):
    from jabuti.models.tracks import bar_track

    t = parse_newick_string(T)
    scene, _r, res = draw(t, RenderStyle(layout=LayoutKind.SLANTED),
                          columns=[bar_track("bar:x", "x", {"A": 1.0})])
    paths = tagged(scene, "branches")
    segs = []
    for item in paths:
        path = item.path()
        for i in range(0, path.elementCount() - 1, 2):
            a, b = path.elementAt(i), path.elementAt(i + 1)
            segs.append(((a.x, a.y), (b.x, b.y)))
    assert len(segs) == 8                                  # só os ramos, sem conectores verticais
    assert all(abs(a[1] - b[1]) > 1e-6 or abs(a[0] - b[0]) > 1e-6 for a, b in segs)
    assert any(abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6 for a, b in segs)
    label_right = max(i.sceneBoundingRect().right() for items in res.leaf_items.values() for i in items)
    assert min(i.sceneBoundingRect().left() for i in tagged(scene, "bar")) > label_right


@pytest.mark.parametrize("layout", [LayoutKind.FAN, LayoutKind.SLANTED, LayoutKind.UNROOTED])
def test_new_layouts_with_edits_and_export(draw, tmp_path, layout):
    from jabuti.models.clades import Clade
    from jabuti.models.document import RowHighlight, ShortBranch
    from jabuti.views.export import export_pdf, export_png, export_svg, export_tiff

    t = load_tree(EX)
    t.reroot_on_group({"Burkholderia_cepacia_ATCC25416", "Burkholderia_cenocepacia_J2315"})
    burk = frozenset({"Burkholderia_cepacia_ATCC25416", "Burkholderia_cenocepacia_J2315"})
    edits = TreeEdits(ladderize="desc", collapsed=[frozenset({"Paraburkholderia_tropica_A02",
                                                               "Paraburkholderia_unamae_A03"})],
                      hidden={"Paraburkholderia_terrae_B28"}, shortened=[ShortBranch(burk, 0.001)],
                      highlights=[RowHighlight(frozenset({"Paraburkholderia_ferrariae_A18"}))])
    shown = apply_edits(t, edits)
    st = RenderStyle(layout=layout)
    st.figure.support_levels.enabled = True
    scene, _r, res = draw(shown, st, clades=[Clade("B", burk, "#ff0000", True, "manual")],
                          collapsed=edits.collapsed, hidden=edits.hidden, highlights=edits.highlights)
    assert "Paraburkholderia_terrae_B28" not in res.leaf_items
    assert tagged(scene, "collapsed") and tagged(scene, "branch-break") and tagged(scene, "support-level")
    assert tagged(scene, "row-highlight") and tagged(scene, "scale-bar")
    assert res.clades[0].valid
    for fn, ext in ((export_svg, "svg"), (export_pdf, "pdf"), (export_png, "png"), (export_tiff, "tif")):
        out = tmp_path / f"f.{ext}"
        fn(scene, out)
        assert out.stat().st_size > 0


def test_unrooted_ignores_tracks_with_note(draw):
    from jabuti.models.tracks import bar_track

    t = parse_newick_string(T)
    scene, _r, res = draw(t, RenderStyle(layout=LayoutKind.UNROOTED), columns=[bar_track("bar:x", "x", {"A": 1.0})])
    assert not tagged(scene, "bar") and any("não enraizada" in n for n in res.notes)


def test_preset_roundtrip_layouts():
    from jabuti.presets import preset_from_dict, preset_to_dict

    st = RenderStyle(layout=LayoutKind.FAN)
    st.fan.angle, st.fan.start = 270.0, 45.0
    st.unrooted.rotation, st.unrooted.mirror, st.unrooted.daylight = 30.0, True, True
    loaded = preset_from_dict(preset_to_dict(st))
    assert loaded.warnings == []
    assert loaded.style.layout == LayoutKind.FAN and loaded.style.fan == st.fan and loaded.style.unrooted == st.unrooted


# ------------------------------------------------------------ GUI
@pytest.fixture
def window(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    win = MainWindow()
    qtbot.addWidget(win)
    win.tree_tab.load(EX)
    return win


def test_gui_layout_list_and_disabled_controls(window):
    vt, fp, sp = window.viz_tab, window.figure_panel, window.style_panel
    names = [vt.layout_cb.itemText(i) for i in range(vt.layout_cb.count())]
    assert names == ["Retangular", "Circular", "Leque", "Diagonal", "Não enraizada"]
    vt.layout_cb.setCurrentIndex(names.index("Não enraizada"))
    assert not fp.add_bar_btn.isEnabled() and "não enraizada" in fp.add_bar_btn.toolTip()
    assert not sp.opt_strip.isEnabled() and sp.opt_strip.toolTip()
    assert not vt.align_tips.isEnabled() and vt.ur_box.isEnabled() and not vt.fan_box.isEnabled()
    window.generate()
    assert window.canvas.result.leaf_items
    vt.layout_cb.setCurrentIndex(names.index("Leque"))
    assert fp.add_bar_btn.isEnabled() and sp.opt_strip.isEnabled() and vt.fan_box.isEnabled()
    vt.fan_angle.setValue(200)
    window.generate()
    assert window.current_style().fan.angle == 200


def test_gui_context_menu_and_selection_in_unrooted(window):
    vt = window.viz_tab
    vt.layout_cb.setCurrentIndex(4)
    window.generate()
    name = "Paraburkholderia_tropica_A02"
    window.canvas.set_selection([name])
    assert window.canvas.selected == [name]
    node = window.tree.find_leaf(name)
    assert window.build_node_menu(node) is not None
