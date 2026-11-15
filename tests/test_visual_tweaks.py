"""Bloco 2: formas reais na legenda, texto sobre ramos (orientação/halo) e barras em escala log."""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QGraphicsSimpleTextItem  # noqa: E402

from jabuti.exporters.itol_export import plan_export  # noqa: E402
from jabuti.models.itol_apply import ItolEntry, apply_itol  # noqa: E402
from jabuti.models.tracks import bar_track, log_range  # noqa: E402
from jabuti.parsers.itol import parse_itol  # noqa: E402
from jabuti.parsers.newick import load_tree  # noqa: E402
from jabuti.presets import style_from_dict, style_to_dict  # noqa: E402
from jabuti.style import BranchTextStyle, LayoutKind, RenderStyle  # noqa: E402
from jabuti.views.tree_renderer import TAG_LEGEND, branch_text_pose, shape_path  # noqa: E402

TREE = "examples/paraburkholderia_40.treefile"
SYMBOL, BINARY, TEXT = "examples/itol/symbol.txt", "examples/itol/binary.txt", "examples/itol/text.txt"


def _apply(*paths):  # type: ignore[no-untyped-def]
    tree = load_tree(TREE)
    return apply_itol([ItolEntry(f"itol:{i}", parse_itol(p)) for i, p in enumerate(paths)], tree)


@pytest.fixture
def window(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    shown = []
    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    win = MainWindow()
    win.shown = shown
    qtbot.addWidget(win)
    win.tree_tab.load(TREE)
    return win


def _with_style(window, **changes):  # type: ignore[no-untyped-def]
    orig = window.current_style

    def cs():  # type: ignore[no-untyped-def]
        s = orig()
        for k, v in changes.items():
            if k == "branch_text":
                s.figure.branch_text = v
            elif k == "legend":
                s.legend.in_figure = v
            else:
                setattr(s, k, v)
        return s
    window.current_style = cs
    window.generate()
    window.current_style = orig


# ------------------------------------------------------------------ legenda com formas
def test_legend_shapes_from_itol():
    fx = _apply(SYMBOL, BINARY)
    sym = next(c.legend for c in fx.columns if c.label.startswith("iTOL símbolos"))
    binl = next(c.legend for c in fx.columns if c.label.startswith("iTOL presença"))
    assert sym.shapes == [(2, True), (3, True), (11, True)]
    assert binl.shapes == [(1, True), (2, True), (3, True), (4, True)]


def test_legend_shape_invert_is_hollow(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("DATASET_SYMBOL\nSEPARATOR TAB\nDATASET_LABEL\tx\nCOLOR\t#000000\nLEGEND_TITLE\tT\n"
                 "LEGEND_SHAPES\t2\t4\nLEGEND_COLORS\t#ff0000\t#00ff00\nLEGEND_LABELS\ta\tb\n"
                 "LEGEND_SHAPE_INVERT\t1\t0\nDATA\nParaburkholderia_xenovorans_A00\t2\t10\t#ff0000\t1\t-1\n",
                 encoding="utf-8")
    ds = parse_itol(p)
    assert not ds.warnings
    fx = _apply(p)
    assert fx.columns[0].legend.shapes == [(2, False), (4, True)]


def _same_path(a, b) -> bool:  # type: ignore[no-untyped-def]
    if a.elementCount() != b.elementCount():
        return False
    e0, f0 = a.elementAt(0), b.elementAt(0)
    dx, dy = e0.x - f0.x, e0.y - f0.y
    return all(abs(a.elementAt(i).x - b.elementAt(i).x - dx) < 1e-6 and abs(a.elementAt(i).y - b.elementAt(i).y - dy)
               < 1e-6 for i in range(a.elementCount()))


def test_scene_legend_draws_real_shapes(window, tmp_path):
    from jabuti.views.export import export_svg

    window.figure_panel.itol.import_files([SYMBOL, BINARY], wait=True)
    _with_style(window, legend=True)
    marks = [i for i in window.renderer.scene.items() if i.data(1) == TAG_LEGEND and i.data(3) is not None]
    shapes = {tuple(i.data(3)) for i in marks}
    assert {(2, True), (3, True), (11, True), (4, True)} <= shapes
    size = max(window.current_style().label.size * 0.9, 4) * 1.15
    for item in marks:
        shape, _filled = item.data(3)
        assert _same_path(item.path(), shape_path(shape, QPointF(0, 0), size)), shape
    # o mesmo desenho vai para o arquivo (SVG sai da cena)
    export_svg(window.renderer.scene, tmp_path / "f.svg")
    assert (tmp_path / "f.svg").stat().st_size > 0


def test_export_keeps_legend_shapes(window, tmp_path):
    window.figure_panel.itol.import_files([SYMBOL, BINARY], wait=True)
    window.generate()
    plan = plan_export(window._snapshot)
    out = {}
    for f in plan.files:
        if f.kind in ("DATASET_SYMBOL", "DATASET_BINARY"):
            p = tmp_path / f.name
            p.write_text(f.text, encoding="utf-8")
            ds = parse_itol(p)
            assert not ds.warnings, ds.warnings
            got = next((c.legend.shapes for c in _apply(p).columns if c.legend is not None), None)
            if got is not None:                    # (símbolos sobre ramos: arquivo sem legenda)
                out[f.kind] = got
    assert out["DATASET_SYMBOL"] == [(2, True), (3, True), (11, True)]
    assert out["DATASET_BINARY"] == [(1, True), (2, True), (3, True), (4, True)]


# ------------------------------------------------------------------ texto sobre o ramo
def _scene_points(pos, origin, rot, w, h):  # type: ignore[no-untyped-def]
    t = QGraphicsSimpleTextItem("x")
    t.setTransformOriginPoint(origin)
    t.setRotation(rot)
    t.setPos(pos)
    return t.mapToScene(QPointF(w / 2, h)), t.mapToScene(QPointF(w / 2, 0)), t.mapToScene(QPointF(0, h / 2))


@pytest.mark.parametrize("deg", [0, 30, 89, 90, 135, 180, 225, 270, 300])
def test_along_is_parallel_upright_and_offset(deg):
    a = QPointF(0, 0)
    b = QPointF(100 * math.cos(math.radians(deg)), 100 * math.sin(math.radians(deg)))
    p = (a + b) * 0.5
    w, h = 40.0, 10.0
    pos, origin, rot = branch_text_pose(a, b, p, w, h, "along", 3.0)
    assert -90 < rot <= 90                                     # nunca de ponta-cabeça
    assert (rot - deg) % 180 == pytest.approx(0, abs=1e-6) or (rot - deg) % 180 == pytest.approx(180, abs=1e-6)
    base, top, _ = _scene_points(pos, origin, rot, w, h)
    assert math.hypot(base.x() - p.x(), base.y() - p.y()) == pytest.approx(3.0)
    assert math.hypot(top.x() - p.x(), top.y() - p.y()) == pytest.approx(13.0)   # texto do lado de fora


@pytest.mark.parametrize("deg", [0, 45, 120, 200, 290])
def test_tangent_is_perpendicular_and_starts_at_offset(deg):
    a = QPointF(10, 10)
    b = a + QPointF(80 * math.cos(math.radians(deg)), 80 * math.sin(math.radians(deg)))
    p = (a + b) * 0.5
    pos, origin, rot = branch_text_pose(a, b, p, 30.0, 8.0, "tangent", 2.5)
    assert -90 < rot <= 90
    assert (rot - deg - 90) % 180 == pytest.approx(0, abs=1e-6) or (rot - deg - 90) % 180 == pytest.approx(180, abs=1e-6)
    *_, start = _scene_points(pos, origin, rot, 30.0, 8.0)
    assert math.hypot(start.x() - p.x(), start.y() - p.y()) == pytest.approx(2.5)


def test_horizontal_is_the_old_placement():
    p = QPointF(50, 20)
    pos, origin, rot = branch_text_pose(QPointF(0, 0), QPointF(30, 70), p, 20.0, 6.0, "horizontal", 1.0)
    assert rot == 0 and pos == QPointF(40, 13) and origin == QPointF(10, 6)


def _branch_texts(window):  # type: ignore[no-untyped-def]
    # textos sobre ramos: os da coluna externa não têm halo nem pai; os dos ramos vêm de "marks"
    marks = {m.text for m in window._snapshot.marks if m.kind == "text"}
    return [i for i in window.renderer.scene.items()
            if isinstance(i, QGraphicsSimpleTextItem) and i.data(1) == "itol-text" and i.text() in marks]


def test_branch_text_modes_in_circular(window):
    window.figure_panel.itol.import_files([TEXT], wait=True)
    _with_style(window, layout=LayoutKind.CIRCULAR, branch_text=BranchTextStyle("along", 2.0, True))
    texts = _branch_texts(window)
    assert len(texts) == 2
    assert any(abs(t.rotation()) > 1 for t in texts)                 # acompanham os ramos
    assert all(-90 < t.rotation() <= 90 for t in texts)
    assert all(any(c.data(0) == "halo" for c in t.childItems()) for t in texts)
    _with_style(window, layout=LayoutKind.CIRCULAR, branch_text=BranchTextStyle("horizontal", 1.0, False))
    texts = _branch_texts(window)
    assert all(t.rotation() == 0 and not t.childItems() for t in texts)
    assert not window.shown


def test_branch_text_panel_roundtrip(window):
    it = window.figure_panel.itol
    it.set_branch_text(BranchTextStyle("tangent", 4.5, False))
    st = window.figure_panel.apply_to(RenderStyle())
    assert st.figure.branch_text == BranchTextStyle("tangent", 4.5, False)
    window.figure_panel.load_style(style_from_dict(style_to_dict(st)))
    assert it.branch_text() == BranchTextStyle("tangent", 4.5, False)


# ------------------------------------------------------------------ barras em log
def test_log_bar_fraction_range_and_nonpositive():
    t = bar_track("b", "x", {"a": 1.0, "b": 10.0, "c": 100.0, "d": 0.0, "e": -3.0}, log=True)
    assert (t.vmin, t.vmax) == (1.0, 100.0)
    assert t.frac(10.0) == pytest.approx(0.5) and t.frac(1.0) == 0 and t.frac(100.0) == 1
    assert t.base == 0.0 and t.nonpositive == 2
    assert t.value_for(["d"]) is None and t.value_for(["e"]) is None
    assert t.value_for(["a", "d"]) == 1.0                                 # ≤ 0 não entra na média
    assert t.axis_ticks() == [1.0, 10.0, 100.0]
    assert log_range([0.03, 7.0]) == (0.01, 10.0)
    assert log_range([5.0], vmin=-1, vmax=2.0) == (1.0, 2.0)            # mínimo ≤ 0 do usuário: automático
    assert log_range([], None, None) == (1.0, 10.0)
    lin = bar_track("b", "x", {"a": 1.0, "b": 10.0})
    assert not lin.log and lin.frac(10.0) == 1.0 and lin.nonpositive == 0


def test_log_scale_itol_roundtrip(window, tmp_path):
    p = tmp_path / "bar.txt"
    p.write_text("DATASET_SIMPLEBAR\nSEPARATOR TAB\nDATASET_LABEL\tcopias\nCOLOR\t#336699\nLOG_SCALE\t1\nDATA\n"
                 "Paraburkholderia_xenovorans_A00\t1000\nParaburkholderia_hospita_A09\t2\n"
                 "Paraburkholderia_tropica_A02\t0\n", encoding="utf-8")
    window.figure_panel.itol.import_files([p], wait=True)
    window.generate()
    track = next(t for b in window._snapshot.blocks for t in b.tracks if getattr(t, "log", False))
    assert track.nonpositive == 1 and (track.vmin, track.vmax) == (1.0, 1000.0)
    assert "LOG_SCALE: 1 valor" in window.figure_panel.itol.report.toPlainText()
    f = next(f for f in plan_export(window._snapshot).files if f.kind == "DATASET_SIMPLEBAR")
    assert "LOG_SCALE\t1" in f.text.splitlines()
    out = tmp_path / "out.txt"
    out.write_text(f.text, encoding="utf-8")
    assert _apply(out).columns[0].column.log


def test_log_bars_from_panel_note_and_preset(window, tmp_path):
    fp = window.figure_panel
    table = tmp_path / "t.tsv"
    table.write_text("genome\tcopias\nLMG2129\t0\nDSM50014\t5\nA00\t500\n", encoding="utf-8")
    fp.load_table(str(table), wait=True)
    spec = fp.add_bar()
    assert spec.column == "copias"
    fp.bar_log.setChecked(True)
    assert spec.log
    window.generate()
    track = next(t for b in window._snapshot.blocks for t in b.tracks if getattr(t, "log", False))
    assert track.nonpositive == 1 and track.vmin == 1.0 and track.vmax == 1000.0
    assert any("escala log: 1 valor" in n for n in window._render_notes)
    # preset de ida e volta
    back = style_from_dict(style_to_dict(window.current_style()))
    assert back.figure.bars[0].log is True
    fp.bar_log.setChecked(False)
    assert not spec.log
    fp.load_style(back)
    fp.bar_list.setCurrentRow(0)
    assert fp.bar_log.isChecked()


# ------------------------------------------------------------------ texto x símbolo no mesmo ponto
def test_symbol_clearance_geometry():
    from jabuti.views.tree_renderer import symbol_clearance

    p = QPointF(0, 0)
    assert symbol_clearance(p, 20.0, []) == 0.0
    assert symbol_clearance(p, 20.0, [(QPointF(5, 0), 10.0)]) == 5.0          # dentro do texto
    assert symbol_clearance(p, 20.0, [(QPointF(40, 0), 10.0)]) == 0.0         # longe
    assert symbol_clearance(p, 20.0, [(QPointF(3, 0), 6.0), (QPointF(-2, 0), 12.0)]) == 6.0   # o maior


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR, LayoutKind.UNROOTED])
@pytest.mark.parametrize("orientation", ["along", "tangent", "horizontal"])
def test_branch_text_moves_off_coinciding_symbol(window, layout, orientation):
    from PySide6.QtGui import QPainterPath

    # "clado A" (texto) e o círculo vermelho (símbolo) estão na posição 0,5 do mesmo ramo
    window.figure_panel.itol.import_files([SYMBOL, TEXT], wait=True)
    _with_style(window, layout=layout, branch_text=BranchTextStyle(orientation, 2.0, False))
    text = next(t for t in _branch_texts(window) if t.text() == "clado A")
    assert text.data(3) > 0                                                   # foi afastado
    poly = QPainterPath()
    poly.addPolygon(text.mapToScene(text.boundingRect()))
    symbols = [i for i in window.renderer.scene.items() if i.data(1) == "itol-symbol"]
    assert not any(i.mapToScene(i.path()).intersects(poly) for i in symbols)
    assert not window.shown
