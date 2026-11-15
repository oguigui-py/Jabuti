"""Rótulos sem sobreposição na árvore não enraizada: colisões, determinismo, geometria intacta."""

from __future__ import annotations

import math
import os
import random
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from jabuti.layout.label_placement import (  # noqa: E402
    LabelBox,
    count_overlaps,
    oriented_rect,
    place_labels,
    rects_overlap,
)
from jabuti.parsers.newick import load_tree, parse_newick_string  # noqa: E402
from jabuti.style import LayoutKind, RenderStyle  # noqa: E402
from scene_baseline import same, signature  # noqa: E402

TREE = "examples/paraburkholderia_40.treefile"


def dense_newick(n: int, seed: int = 3) -> str:
    rng = random.Random(seed)
    nodes = [f"Especie_muito_longa_{i:04d}:{rng.uniform(0.01, 0.2):.4f}" for i in range(n)]
    while len(nodes) > 1:
        a = nodes.pop(rng.randrange(len(nodes)))
        b = nodes.pop(rng.randrange(len(nodes)))
        nodes.append(f"({a},{b}):{rng.uniform(0.001, 0.05):.4f}")
    return nodes[0].rsplit(":", 1)[0] + ";"


# ------------------------------------------------------------------ geometria pura
def test_rotated_rect_overlap():
    a = LabelBox("a", 0, 0, 0.0, 0, 50, 10)
    assert rects_overlap(oriented_rect(a, 0.0, 0), oriented_rect(a, 0.0, 20))          # mesma linha, sobrepostos
    assert not rects_overlap(oriented_rect(a, 0.0, 0), oriented_rect(a, 0.0, 60))      # depois do fim
    assert not rects_overlap(oriented_rect(a, 0.0, 5), oriented_rect(a, math.pi, 5))  # lados opostos
    assert rects_overlap(oriented_rect(a, 0.0, 5), oriented_rect(a, math.radians(5), 5))   # quase paralelos


def _fan_boxes(n=60, seed=1, span=1.2, radius=150.0):  # type: ignore[no-untyped-def]
    """Folhas espalhadas num arco (como as pontas de uma árvore), rótulos radiais apertados."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        a = rng.uniform(0, span)
        r = radius * rng.uniform(0.85, 1.0)
        out.append(LabelBox(f"f{i}", r * math.cos(a), r * math.sin(a), a + rng.uniform(-0.05, 0.05), 5.0,
                            rng.uniform(60, 120), 10.0))
    return out


def test_placement_removes_overlaps_and_is_deterministic():
    boxes = _fan_boxes()
    assert count_overlaps(boxes) > 50
    out = place_labels(boxes)
    assert count_overlaps(boxes, out) == 0 and all(p.resolved for p in out)
    again = place_labels([LabelBox(**vars(b)) for b in boxes])
    assert [(p.key, p.angle, p.offset, p.guide) for p in out] == [(p.key, p.angle, p.offset, p.guide) for p in again]
    shuffled = list(boxes)
    random.Random(9).shuffle(shuffled)                      # ordem de entrada não importa
    by_key = {p.key: p for p in place_labels(shuffled)}
    assert all((by_key[p.key].angle, by_key[p.key].offset) == (p.angle, p.offset) for p in out)
    assert any(p.guide for p in out)                         # os muito afastados ganham linha-guia
    assert all(p.offset >= b.offset for p, b in zip(out, boxes))   # só afasta, nunca aproxima


def test_free_labels_do_not_move():
    boxes = [LabelBox(str(i), 0, 0, i * math.pi / 4, 20, 30, 8) for i in range(8)]
    assert count_overlaps(boxes) == 0
    out = place_labels(boxes)
    assert [(p.angle, p.offset, p.guide) for p in out] == [(b.angle, b.offset, False) for b in boxes]


def test_500_labels_fast_enough():
    boxes = _fan_boxes(500, seed=5, span=2 * math.pi, radius=400.0)
    before = count_overlaps(boxes)
    t = time.perf_counter()
    out = place_labels(boxes)
    assert time.perf_counter() - t < 3.0
    after = count_overlaps(boxes, out)
    unresolved = sum(not p.resolved for p in out)
    assert before > 1000 and after == 0 and unresolved == 0, (before, after, unresolved)


# ------------------------------------------------------------------ desenho
@pytest.fixture
def draw(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    def _draw(tree, avoid=True, layout=LayoutKind.UNROOTED):  # type: ignore[no-untyped-def]
        scene = QGraphicsScene()
        st = RenderStyle(layout=layout)
        st.unrooted.avoid_overlap = avoid
        res = TreeRenderer(scene).render(tree, st)
        return scene, res

    return _draw


def label_overlaps(res) -> int:  # type: ignore[no-untyped-def]
    from PySide6.QtGui import QPainterPath

    polys = []
    for items in res.leaf_items.values():
        p = QPainterPath()
        p.addPolygon(items[0].mapToScene(items[0].boundingRect()))
        polys.append(p)
    return sum(1 for i in range(len(polys)) for j in range(i + 1, len(polys)) if polys[i].intersects(polys[j]))


def _branches(scene):  # type: ignore[no-untyped-def]
    return sorted((round(i.sceneBoundingRect().x(), 2), round(i.sceneBoundingRect().width(), 2))
                  for i in scene.items() if i.data(1) == "branches")


def test_example_collisions_before_and_after(draw):
    tree = load_tree(TREE)
    s0, r0 = draw(tree.copy(), avoid=False)
    s1, r1 = draw(tree.copy(), avoid=True)
    before, after = label_overlaps(r0), label_overlaps(r1)
    assert before >= 20 and after == 0
    assert r0.leaf_points == r1.leaf_points                  # folhas no mesmo lugar
    assert _branches(s0) == _branches(s1)                    # árvore igual
    guides = [i for i in s1.items() if i.data(1) == "label-guide"]
    assert guides and not [i for i in s0.items() if i.data(1) == "label-guide"]
    for g in guides:                                         # linha-guia começa na folha
        start = g.path().elementAt(0)
        assert min(math.hypot(start.x - p.x(), start.y - p.y()) for p in r1.leaf_points.values()) < 6


def test_dense_synthetic_tree(draw):
    tree = parse_newick_string(dense_newick(150))
    _s0, r0 = draw(tree.copy(), avoid=False)
    _s1, r1 = draw(tree.copy(), avoid=True)
    before, after = label_overlaps(r0), label_overlaps(r1)
    assert before > 100 and after == 0, (before, after)


def test_same_input_same_output(draw):
    tree = load_tree(TREE)
    a, _ = draw(tree.copy())
    b, _ = draw(tree.copy())
    assert same(signature(a), signature(b)) is None


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.SLANTED, LayoutKind.CIRCULAR, LayoutKind.FAN])
def test_other_layouts_unchanged(draw, layout):
    tree = load_tree(TREE)
    on, _ = draw(tree.copy(), True, layout)
    off, _ = draw(tree.copy(), False, layout)
    assert same(signature(on), signature(off)) is None
    assert not [i for i in on.items() if i.data(1) == "label-guide"]


def test_option_in_ui_presets_project_and_exports(qtbot, tmp_path, monkeypatch):
    import json

    from jabuti.presets import style_from_dict, style_to_dict
    from jabuti.views import errors
    from jabuti.views.export import export_pdf, export_png, export_svg, export_tiff
    from jabuti.views.main_window import MainWindow

    assert RenderStyle().unrooted.avoid_overlap is True
    st = RenderStyle()
    st.unrooted.avoid_overlap = False
    assert style_from_dict(style_to_dict(st)).unrooted.avoid_overlap is False
    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    w = MainWindow()
    qtbot.addWidget(w)
    w.open_tree(TREE)
    vt = w.viz_tab
    vt.layout_cb.setCurrentIndex(vt.layout_cb.findData("unrooted"))
    assert vt.avoid_overlap.isChecked() and vt.ur_box.isEnabled()
    w.render_live()
    assert label_overlaps(w.canvas.result) == 0
    for fn, name in ((export_svg, "f.svg"), (export_pdf, "f.pdf"), (export_png, "f.png"), (export_tiff, "f.tif")):
        assert fn(w.renderer.scene, tmp_path / name).stat().st_size > 0
    assert "label-guide" in {i.data(1) for i in w.renderer.scene.items()}
    vt.avoid_overlap.setChecked(False)
    w.render_live()
    assert label_overlaps(w.canvas.result) > 0
    path = w.project._write(tmp_path / "p.jabuti")
    assert json.loads(path.read_text())["view"]["style"]["unrooted"]["avoid_overlap"] is False
    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.open_project(path, wait=True) and not w2.viz_tab.avoid_overlap.isChecked()
    # lote: cada figura usa o estilo do projeto (com o ajuste ligado de novo)
    vt.avoid_overlap.setChecked(True)
    w.render_live()
    from jabuti.views.batch_export import BatchRequest

    rep = w.batch_export(BatchRequest([LayoutKind.UNROOTED], [("atual", None)], ["svg"], tmp_path / "lote",
                                      project="p"), show_progress=False)
    assert len(rep.generated) == 1
