"""Colunas de dados do painel Figura: modelo, tabelas, desenho, presets e GUI."""

import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.annotations import LeafColumn  # noqa: E402
from jabuti.models.datatables import DataSource, LeafMapping, numeric_column  # noqa: E402
from jabuti.models.tracks import (  # noqa: E402
    CLADE_STRIP,
    auto_range,
    bar_track,
    order_keys,
    parse_refs,
)
from jabuti.parsers.metadata import parse_table_text  # noqa: E402
from jabuti.parsers.newick import parse_newick_string  # noqa: E402
from jabuti.style import BarSpec, LayoutKind, RenderStyle  # noqa: E402

T = "((A:1,B:1):1,(C:1,(D:1,E:1):1):1);"
VALUES = {"A": 2.0, "B": 9.0, "C": 5.0, "D": 0.5}          # E sem dado


# ------------------------------------------------------------------ modelo
def test_parse_refs_separators_and_decimal_comma():
    assert parse_refs("4; 8") == [4.0, 8.0]
    assert parse_refs("4, 8") == [4.0, 8.0]
    assert parse_refs("2,5 10") == [2.5, 10.0]
    assert parse_refs("  ") == []
    with pytest.raises(ValueError, match="inválido"):
        parse_refs("4; oito")


def test_auto_range():
    assert auto_range([2, 9]) == (0.0, 9.0)
    assert auto_range([-3, 4]) == (-3.0, 4.0)
    assert auto_range([], None, None) == (0.0, 1.0)
    assert auto_range([2, 9], vmin=1, vmax=5) == (1, 5)
    assert auto_range([5, 5], vmin=5) == (5, 6.0)            # nunca eixo de largura zero


def test_bar_track_mean_frac_and_base():
    t = bar_track("bar:x", "x", VALUES, refs=[4, 8, 20])
    assert t.value_for(["E"]) is None
    assert t.value_for(["A", "B", "E"]) == pytest.approx(5.5)   # média ignora sem dado
    assert t.frac(9) == 1 and t.frac(-1) == 0 and t.base == 0
    assert t.visible_refs() == [4, 8]
    neg = bar_track("bar:y", "y", {"A": -2.0, "B": 2.0})
    assert neg.base == pytest.approx(0.5)


def test_order_keys():
    assert order_keys(["a", "b", "c"], ["c", "x", "a"]) == ["c", "a", "b"]
    assert order_keys(["a", "b", "c"], ["c"], hidden=["a"]) == ["c", "b"]


def test_leaf_mapping_auto_manual_and_unique():
    m = LeafMapping(keys=["LB400", "STM815", "zzz"],
                    leaves=["Paraburkholderia_xenovorans_LB400", "Paraburkholderia_phymatum_STM815"])
    m.auto_map()
    assert m.mapped() == {"LB400": "Paraburkholderia_xenovorans_LB400",
                          "STM815": "Paraburkholderia_phymatum_STM815"}
    assert m.unused_keys() == ["zzz"]
    m.set("zzz", "Paraburkholderia_xenovorans_LB400")    # a folha muda de dono
    assert m.mapping["LB400"] is None and m.mapping["zzz"] == "Paraburkholderia_xenovorans_LB400"
    m.set_leaves(m.leaves + ["outra"])                    # manual sobrevive a nova árvore
    assert m.mapping["zzz"] == "Paraburkholderia_xenovorans_LB400"
    assert m.mapping["STM815"] == "Paraburkholderia_phymatum_STM815"
    assert m.leaves_without() == ["outra"]


def test_data_source_numeric_columns_and_na():
    table = parse_table_text("id\tsize\tflag\tname\nA\t1.5\t0\tx\nB\tNA\t1\ty\nC\t3,5\t0\tz\n")
    src = DataSource("t.tsv", table)
    src.mapping.leaves = ["A", "B", "C"]
    src.mapping.auto_map()
    assert src.numeric_columns() == ["size", "flag"]      # 0/1 também serve para barras
    assert numeric_column(src.by_leaf(), "size") == {"A": 1.5, "C": 3.5}


# ------------------------------------------------------------------ desenho
@pytest.fixture
def draw(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    keep = []

    def _draw(style=None, columns=None, collapsed=None, clades=None):
        scene = QGraphicsScene()
        r = TreeRenderer(scene)
        res = r.render(parse_newick_string(T), style or RenderStyle(), clades, collapsed, columns)
        keep.append(scene)
        return scene, r, res

    return _draw


def tagged(scene, tag, key=None):
    return [i for i in scene.items() if i.data(1) == tag and (key is None or i.data(2) == key)]


def bars(**kw):
    return bar_track("bar:x", "tamanho", VALUES, **kw)


def strip():
    return LeafColumn("meta:h", "hab", {"A": "#ff0000", "B": "#00ff00"}, "#d9d9d9", kind="metadata", width=12)


def test_rect_bars_right_of_labels_with_refs_axis_and_missing(draw):
    scene, _, res = draw(RenderStyle(), [bars(refs=[4, 8], show_values=True)])
    label_right = max(i.sceneBoundingRect().right() for items in res.leaf_items.values() for i in items)
    (fill,) = tagged(scene, "bar", "bar:x")
    assert len(fill.path().toSubpathPolygons()) == 4          # A, B, C, D (E sem dado)
    assert fill.sceneBoundingRect().left() > label_right
    assert len(tagged(scene, "bar-missing", "bar:x")) == 1
    (refs,) = tagged(scene, "bar-reference", "bar:x")
    assert len(refs.path().toSubpathPolygons()) == 2
    assert refs.zValue() < fill.zValue()                      # referência atrás das barras
    assert sorted(i.text() for i in tagged(scene, "bar-value")) == ["0.5", "2", "5", "9"]
    axis_texts = {i.text() for i in tagged(scene, "bar-axis") if hasattr(i, "text")}
    assert {"0", "4", "8", "9"} <= axis_texts
    assert "tamanho" in {i.text() for i in tagged(scene, "column-header")}


def test_bar_length_proportional(draw):
    scene, _, _ = draw(RenderStyle(), [bars(vmin=0, vmax=10)])
    (fill,) = tagged(scene, "bar", "bar:x")
    widths = sorted(round(p.boundingRect().width(), 1) for p in fill.path().toSubpathPolygons())
    assert widths == [4.0, 16.0, 40.0, 72.0]                  # 80 px * (0.5, 2, 5, 9)/10


def test_tracks_do_not_overlap_and_follow_order(draw):
    t1, t2 = strip(), bars(show_values=True)
    scene, _, _ = draw(RenderStyle(), [t2, t1])
    bar_right = max(i.sceneBoundingRect().right() for i in tagged(scene, "bar") + tagged(scene, "bar-value"))
    strip_left = min(i.sceneBoundingRect().left() for i in tagged(scene, "metadata-strip"))
    assert strip_left > bar_right                             # barras primeiro, depois a faixa
    scene, _, _ = draw(RenderStyle(), [t1, t2])
    strip_right = max(i.sceneBoundingRect().right() for i in tagged(scene, "metadata-strip"))
    bar_left = min(i.sceneBoundingRect().left() for i in tagged(scene, "bar"))
    assert bar_left > strip_right


def test_clade_strip_position_follows_marker(draw):
    from jabuti.models.clades import Clade

    clades = [Clade("c", frozenset({"A", "B"}), None, True, "manual")]
    style = RenderStyle()
    style.clades.outer_strip = True
    scene, _, _ = draw(style, [bars(), CLADE_STRIP], clades=clades)
    strip_left = min(i.sceneBoundingRect().left() for i in tagged(scene, "clade-strip"))
    bar_right = max(i.sceneBoundingRect().right() for i in tagged(scene, "bar"))
    assert strip_left > bar_right


def _radii(item):
    pts = [p for poly in item.path().toSubpathPolygons() for p in poly]
    return min(math.hypot(p.x(), p.y()) for p in pts), max(math.hypot(p.x(), p.y()) for p in pts)


def test_circular_bars_inside_their_ring(draw):
    scene, r, res = draw(RenderStyle(layout=LayoutKind.CIRCULAR), [strip(), bars(refs=[4], show_values=True)])
    g = r.geometry
    r0, r1 = g.ring_bounds(1)
    lo, hi = _radii(tagged(scene, "bar", "bar:x")[0])
    assert r0 - 0.5 <= lo and hi <= r0 + 80 + 0.5
    assert g.ring_bounds(0)[1] < r0                           # anel da faixa por dentro
    assert r1 < g.label_radius                                # rótulos fora dos anéis (valores incluídos)
    assert tagged(scene, "bar-reference", "bar:x")


def test_collapsed_clade_uses_mean(draw):
    scene, _, _ = draw(RenderStyle(), [bars(vmin=0, vmax=10)], collapsed=[frozenset({"A", "B"})])
    (fill,) = tagged(scene, "bar", "bar:x")
    widths = sorted(round(p.boundingRect().width(), 1) for p in fill.path().toSubpathPolygons())
    assert 44.0 in widths                                     # média de A (2) e B (9) = 5.5


def test_bar_color_modes(draw):
    from jabuti.models.clades import Clade

    clades = [Clade("c", frozenset({"A", "B"}), "#123456", True, "manual")]
    scene, _, _ = draw(RenderStyle(), [bars(color_mode="clade")], clades=clades)
    colors = {i.brush().color().name() for i in tagged(scene, "bar")}
    assert "#123456" in colors and RenderStyle().clades.neutral_color in colors
    scene, _, _ = draw(RenderStyle(), [bars(color_mode="metadata", colors={"A": "#abcdef"}, color="#000000")])
    colors = {i.brush().color().name() for i in tagged(scene, "bar")}
    assert colors == {"#abcdef", "#000000"}


def test_svg_has_editable_text(draw, tmp_path):
    from jabuti.views.export import export_svg

    scene, _, _ = draw(RenderStyle(), [bars(show_values=True)])
    svg = export_svg(scene, tmp_path / "b.svg").read_text(encoding="utf-8")
    assert ">tamanho<" in svg and ">9<" in svg


# ------------------------------------------------------------------ presets
def test_preset_roundtrip_bars():
    from jabuti.presets import preset_from_dict, preset_to_dict

    st = RenderStyle()
    st.figure.bars = [BarSpec("bar1", "traits.tsv", "size", "clade", "#aabbcc", True, [-1.0, 4.0], -2.0, None, 120)]
    st.figure.track_order = ["bar:bar1", CLADE_STRIP]
    loaded = preset_from_dict(preset_to_dict(st))
    assert loaded.warnings == []
    assert loaded.style.figure == st.figure


def test_preset_invalid_bar_values_warn():
    from jabuti.presets import preset_from_dict

    data = {"version": 1, "style": {"figure": {"bars": [{"id": "b", "column": "x", "color_mode": "rainbow",
                                                          "refs": ["a"], "width": -5}]}}}
    loaded = preset_from_dict(data)
    (b,) = loaded.style.figure.bars
    assert b.color_mode == "single" and b.refs == [] and b.width == 80.0
    assert len(loaded.warnings) == 3


# ------------------------------------------------------------------ GUI
@pytest.fixture
def window(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    shown = []
    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    win = MainWindow()
    win.shown = shown
    qtbot.addWidget(win)
    win.tree_tab.load("examples/paraburkholderia_40.treefile")
    return win


def test_figure_panel_is_left_dock_and_collapses(window):
    from PySide6.QtCore import Qt

    assert window.dockWidgetArea(window.figure_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    window.figure_holder.set_collapsed(True)
    assert window.figure_holder.width() <= 30 and not window.figure_holder.scroll.isVisible()
    window.figure_holder.set_collapsed(False)
    assert window.figure_holder.minimumWidth() >= 300


def test_gui_load_table_async_and_bars(window, qtbot):
    fp = window.figure_panel
    with qtbot.waitSignal(fp.table_loaded, timeout=5000):
        fp.load_table("examples/traits.tsv", wait=False)
    assert not fp.is_loading()
    src = fp.sources["traits.tsv"]
    assert len(src.mapping.mapped()) == 40
    assert "40/40 folhas com dados" in fp.table_report.text()
    spec = fp.add_bar()
    assert spec.source == "traits.tsv" and spec.column == "genome_size_mb"
    window.render_live()
    assert tagged(window.canvas.tree_scene, "bar", "bar:bar1")
    # sem barras, nada é desenhado (tudo desligado por padrão)
    fp.remove_bar()
    window.render_live()
    assert not tagged(window.canvas.tree_scene, "bar")


def test_gui_bad_table_reports_error(window, tmp_path):
    bad = tmp_path / "vazia.tsv"
    bad.write_text("", encoding="utf-8")
    assert window.figure_panel.load_table(bad) is False
    assert window.shown and "vazio" in window.shown[0].lower()


def test_gui_manual_mapping_in_table(window, tmp_path):
    path = tmp_path / "t.tsv"
    path.write_text("genome\tv\nfoo\t3\nLMG2129\t5\n", encoding="utf-8")
    fp = window.figure_panel
    assert fp.load_table(path)
    src = fp.sources["t.tsv"]
    assert src.mapping.mapping["foo"] is None
    combo = fp.mapping_table.cellWidget(0, fp.mapping_table.col_leaf)
    combo.setCurrentIndex(combo.findData("Burkholderia_cepacia_ATCC25416"))
    combo.activated.emit(combo.currentIndex())
    assert src.mapping.mapping["foo"] == "Burkholderia_cepacia_ATCC25416"
    assert "✎" in fp.mapping_table.item(0, fp.mapping_table.col_status).text()


def test_gui_preset_with_missing_table_warns(window):
    from jabuti.presets import preset_from_dict

    st = RenderStyle()
    st.figure.bars = [BarSpec("bar1", "nao_carregada.tsv", "size")]
    warnings = window.apply_preset(preset_from_dict({"version": 1, "style": {
        "figure": {"bars": [{"id": "bar1", "source": "nao_carregada.tsv", "column": "size"}]}}}))
    assert any("nao_carregada.tsv" in w for w in warnings)
    assert "⚠" in window.figure_panel.bar_list.item(0).text()
    window.render_live()                                     # não quebra; só avisa
    assert "sem dados" in window.statusBar().currentMessage()


def test_gui_metadata_source_bars(window):
    window.metadata_tab.load("examples/metadata.tsv")
    fp = window.figure_panel
    fp.add_bar()
    spec = fp.bars[0]
    assert spec.source == "metadata" and spec.column == "gc_percent"
    window.render_live()
    assert tagged(window.canvas.tree_scene, "bar")


def test_gff_tab_uses_shared_mapping_table(window, data_dir):
    gt = window.gff_tab
    window.tree_tab.load(data_dir / "iqtree_ufboot.treefile")
    gt.load_files([data_dir / "gff" / "LB400.gff3"])
    combo = gt.table.cellWidget(0, gt.table.col_leaf)
    combo.setCurrentIndex(0)
    combo.activated.emit(0)
    assert gt.mapping["LB400"] is None
