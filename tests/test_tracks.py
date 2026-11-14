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
    axis = [i for i in tagged(scene, "bar-axis") if hasattr(i, "text")]
    assert {"0", "4", "9"} <= {i.text() for i in axis}      # "8" encostaria no máximo: omitido
    rects = sorted((i.sceneBoundingRect() for i in axis), key=lambda r: r.left())
    assert all(a.right() <= b.left() for a, b in zip(rects, rects[1:]))
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


# ------------------------------------------------------------ empilhadas
SERIES = {"GH": {"A": 6.0, "B": 2.0, "C": 1.0}, "GT": {"A": 4.0, "B": None or 0.0, "C": 3.0}}


def stacked(**kw):
    from jabuti.models.tracks import stacked_track

    return stacked_track("stacked:s", "CAZy", ["GH", "GT"], ["#ff0000", "#0000ff"], SERIES, **kw)


def test_stacked_model_max_mean_and_missing():
    t = stacked()
    assert t.vmax == 10.0                                    # maior soma (A)
    assert t.stack_for(["A"]) == [6.0, 4.0]
    assert t.stack_for(["D"]) is None                        # sem dado em nenhuma série
    assert t.stack_for(["A", "C"]) == [3.5, 3.5]             # média por série no colapsado
    assert stacked(vmax=20).vmax == 20


def test_stacked_partial_series_counts_as_zero():
    from jabuti.models.tracks import stacked_track

    t = stacked_track("k", "h", ["x", "y"], ["#000000", "#111111"], {"x": {"A": 2.0}, "y": {"B": 3.0}})
    assert t.stack_for(["A"]) == [2.0, 0.0]


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_stacked_segments_per_series(draw, layout):
    scene, _, _ = draw(RenderStyle(layout=layout), [stacked()])
    segs = {i.data(3): i for i in tagged(scene, "stacked-bar", "stacked:s")}
    assert set(segs) == {"GH", "GT"}
    assert segs["GH"].brush().color().name() == "#ff0000"
    assert len(segs["GH"].path().toSubpathPolygons()) == 3  # A, B, C
    assert len(segs["GT"].path().toSubpathPolygons()) == 2  # B tem GT = 0
    assert tagged(scene, "bar-missing", "stacked:s")         # D e E sem dado


def test_stacked_rect_lengths(draw):
    scene, _, _ = draw(RenderStyle(), [stacked()])
    segs = {i.data(3): i for i in tagged(scene, "stacked-bar")}
    gh = sorted(round(p.boundingRect().width(), 1) for p in segs["GH"].path().toSubpathPolygons())
    assert gh == [10.0, 20.0, 60.0]                          # 100 px * (1, 2, 6)/10
    # GT de A começa onde GH de A termina
    a_gh = max(segs["GH"].path().toSubpathPolygons(), key=lambda p: p.boundingRect().width()).boundingRect()
    a_gt = [p.boundingRect() for p in segs["GT"].path().toSubpathPolygons()
            if abs(p.boundingRect().center().y() - a_gh.center().y()) < 1][0]
    assert a_gt.left() == pytest.approx(a_gh.right())


def test_axis_labels_stay_inside_columns(draw):
    scene, _, _ = draw(RenderStyle(), [bars(), stacked()])
    by_key = {}
    for i in tagged(scene, "bar-axis"):
        if hasattr(i, "text"):
            by_key.setdefault(i.data(2), []).append(i.sceneBoundingRect())
    right_bar = max(r.right() for r in by_key["bar:x"])
    left_stacked = min(r.left() for r in by_key["stacked:s"])
    assert right_bar < left_stacked


def test_preset_roundtrip_stacked():
    from jabuti.presets import preset_from_dict, preset_to_dict
    from jabuti.style import StackedSpec

    st = RenderStyle()
    st.figure.stacked = [StackedSpec("stk1", "t.tsv", "CAZy", ["GH", "GT"], ["#ff0000", "#0000ff"], 300.0, 90)]
    loaded = preset_from_dict(preset_to_dict(st))
    assert loaded.warnings == [] and loaded.style.figure.stacked == st.figure.stacked
    bad = preset_from_dict({"style": {"figure": {"stacked": [{"colors": ["vermelho"]}]}}})
    assert bad.style.figure.stacked[0].colors == [] and any("colors" in w for w in bad.warnings)


def test_gui_stacked_series_and_legend(window):
    from PySide6.QtCore import Qt

    fp = window.figure_panel
    assert fp.load_table("examples/traits.tsv")
    spec = fp.add_stacked()
    for i in range(fp.st_series.count()):
        item = fp.st_series.item(i)
        if item.data(Qt.ItemDataRole.UserRole) in ("genome_size_mb", "n_contigs"):
            item.setCheckState(Qt.CheckState.Unchecked)
    assert spec.columns == ["GH", "GT", "CE", "AA", "CBM", "PL"]
    fp.st_series.setCurrentRow(2)                             # GH
    fp.st_color.set_color("#123456", emit=True)
    assert spec.colors[0] == "#123456"
    fp.st_name.setText("CAZy")
    fp.st_name.editingFinished.emit()
    window.render_live()
    scene = window.canvas.tree_scene
    assert {i.data(3) for i in tagged(scene, "stacked-bar")} == set(spec.columns)
    groups = window.style_panel.legend.groups
    (series,) = [g for g in groups if g.title == "Séries: CAZy"]
    assert series.entries[0] == ("GH", "#123456")


# ------------------------------------------------------------------ matriz
MATRIX = {"A": {"GH13": "10", "GH2": "0", "GT4": "3", "CE1": "NA"},
          "B": {"GH13": "1", "GH2": "100", "GT4": "3", "CE1": "1"},
          "C": {"GH13": "5", "GH2": "2", "GT4": "0", "CE1": "0"}}


def test_natural_key_order():
    from jabuti.models.tracks import natural_key

    assert sorted(["GT10", "GH13", "GH2", "GT4", "CBM50"], key=natural_key) == ["CBM50", "GH2", "GH13", "GT4", "GT10"]


def test_select_features_top_and_manual():
    from jabuti.models.tracks import select_features

    feats = ["GH13", "GH2", "GT4", "CE1"]
    assert select_features(MATRIX, feats, "top", [], 2) == ["GH2", "GH13"]       # somas 102 e 16
    assert select_features(MATRIX, feats, "manual", ["GT4", "GH13", "xx"], 0) == ["GH13", "GT4"]


def test_color_scales():
    from jabuti.models.colormaps import COLORMAPS, ColorScale

    lin = ColorScale("viridis", 0, 100, "linear")
    assert lin.color(0) == COLORMAPS["viridis"][0] and lin.color(100) == COLORMAPS["viridis"][-1]
    assert lin.fraction(50) == pytest.approx(0.5)
    log = ColorScale("viridis", 0, 100, "log1p")
    assert log.fraction(9) == pytest.approx(math.log(10) / math.log(101))
    sq = ColorScale("viridis", 0, 100, "sqrt")
    assert sq.fraction(25) == pytest.approx(0.5)
    assert [round(v, 6) for _f, v in sq.ticks(3)] == [0, 25, 100]
    assert ColorScale("viridis", 5, 5).fraction(5) == 0                         # sem divisão por zero


def test_matrix_columns_missing_values_and_texts():
    from jabuti.models.tracks import matrix_columns

    cols, cs = matrix_columns("matrix:m", MATRIX, ["CE1", "GH2"], "Blues", show_values=True, width=14,
                              header_rotation=45)
    ce1 = cols[0]
    assert ce1.key == "matrix:m:CE1" and ce1.kind == "matrix" and ce1.header_rotation == 45
    assert "A" not in ce1.colors and ce1.color_for("A") == "#d9d9d9"           # NA = sem dado
    assert ce1.texts == {"B": "1", "C": "0"}
    assert cs.vmin == 0 and cs.vmax == 100


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_matrix_drawn_with_gene_heatmap(draw, layout):
    from jabuti.models.tracks import matrix_columns

    leaves = {k: {"GH13": str(i)} for i, k in enumerate("ABCDE")}
    cols, _ = matrix_columns("matrix:m", leaves, ["GH13"], "viridis", show_values=True)
    gene = LeafColumn("gene:x", "nifH", {"A": "#2b6cb0"}, "#d9d9d9")
    scene, _, _ = draw(RenderStyle(layout=layout), [gene, *cols])
    assert tagged(scene, "heatmap", "gene:x") and tagged(scene, "matrix", "matrix:m:GH13")
    texts = sorted(i.text() for i in scene.items() if i.data(1) == "heatmap" and hasattr(i, "text"))
    assert texts == ["0", "1", "2", "3", "4"]
    assert all(i.zValue() > 0 for i in scene.items() if i.data(1) == "heatmap" and hasattr(i, "text"))


@pytest.mark.parametrize("rotation", [0, 45, 90])
def test_matrix_headers_rotation_no_overlap(draw, rotation):
    from jabuti.models.tracks import matrix_columns

    leaves = {k: {f: "1" for f in ("GH1", "GH2", "GH3")} for k in "ABCDE"}
    cols, _ = matrix_columns("matrix:m", leaves, ["GH1", "GH2", "GH3"], "viridis", width=40,
                             header_rotation=rotation)
    scene, _, res = draw(RenderStyle(), cols)
    heads = [i for i in tagged(scene, "column-header")]
    assert len(heads) == 3
    assert {round(i.rotation()) for i in heads} == {{0: 0, 45: -45, 90: -90}[rotation]}
    tree_top = min(i.sceneBoundingRect().top() for i in tagged(scene, "matrix"))
    assert all(i.sceneBoundingRect().bottom() <= tree_top for i in heads)       # acima das colunas
    if rotation == 0:
        rects = sorted((i.sceneBoundingRect() for i in heads), key=lambda r: r.left())
        assert all(a.right() <= b.left() for a, b in zip(rects, rects[1:]))


def test_narrow_horizontal_headers_fall_back_to_vertical(draw):
    from jabuti.models.tracks import matrix_columns

    leaves = {k: {"Peptidase_S8": "1", "Peptidase_M23": "2"} for k in "ABCDE"}
    cols, _ = matrix_columns("matrix:m", leaves, ["Peptidase_S8", "Peptidase_M23"], "viridis", width=10,
                             header_rotation=0)
    scene, _, res = draw(RenderStyle(), cols)
    assert {round(i.rotation()) for i in tagged(scene, "column-header")} == {-90}
    assert any("0°" in n for n in res.notes)


def test_colorbar_legend_in_figure_and_svg(draw, tmp_path):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.models.annotations import LegendGroup
    from jabuti.views.export import export_svg
    from jabuti.views.tree_renderer import TreeRenderer

    style = RenderStyle()
    style.legend.in_figure = True
    scene = QGraphicsScene()
    group = LegendGroup("CAZy", [("sem dado", "#d9d9d9"), ("só texto", None)], "colorbar",
                        ["#000000", "#ffffff"], [(0.0, "0"), (1.0, "75")])
    TreeRenderer(scene).render(parse_newick_string(T), style, legend=[group])
    texts = {i.text() for i in tagged(scene, "legend") if hasattr(i, "text")}
    assert {"CAZy", "0", "75", "sem dado", "só texto"} <= texts
    grads = [i for i in tagged(scene, "legend") if hasattr(i, "brush") and i.brush().gradient() is not None]
    assert len(grads) == 1
    svg = export_svg(scene, tmp_path / "c.svg").read_text(encoding="utf-8")
    assert "linearGradient" in svg and ">75<" in svg


def test_preset_roundtrip_matrix():
    from jabuti.presets import preset_from_dict, preset_to_dict
    from jabuti.style import MatrixSpec

    st = RenderStyle()
    st.figure.matrices = [MatrixSpec("mtx1", "cazy.tsv", "CAZy", "manual", ["GH2", "GH13"], 5, "sqrt",
                                     "magma", -1.0, 50.0, 45, True, 1.5)]
    loaded = preset_from_dict(preset_to_dict(st))
    assert loaded.warnings == [] and loaded.style.figure.matrices == st.figure.matrices
    bad = preset_from_dict({"version": 1, "style": {"figure": {"matrices": [{"colormap": "jet", "header_rotation": 30,
                                                               "scale": "log10"}]}}})
    m = bad.style.figure.matrices[0]
    assert (m.colormap, m.header_rotation, m.scale) == ("viridis", 90, "linear") and len(bad.warnings) == 3


def test_gui_matrix_top_n_and_legend(window):
    fp = window.figure_panel
    assert fp.load_table("examples/cazy_counts.tsv")
    spec = fp.add_matrix()
    fp.mx_top.setValue(5)
    fp.mx_scale.setCurrentIndex(fp.mx_scale.findData("log1p"))
    window.render_live()
    keys = {i.data(2) for i in tagged(window.canvas.tree_scene, "matrix")}
    assert len(keys) == 5 and all(k.startswith("matrix:mtx1:") for k in keys)
    (bar,) = [g for g in window.style_panel.legend.groups if g.kind == "colorbar"]
    assert "log" in bar.title and bar.ticks[0][1] == "0"
    # escolha manual
    fp.mx_select.setCurrentIndex(fp.mx_select.findData("manual"))
    fp.mx_features.item(0).setCheckState(fp.mx_features.item(0).checkState().Checked)
    assert spec.features == [fp.mx_features.item(0).data(256)]
    window.render_live()
    assert len({i.data(2) for i in tagged(window.canvas.tree_scene, "matrix")}) == 1
