"""Heatmap de genes: modelo, desenho (colunas/anéis), aba GFF e export."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.annotations import (  # noqa: E402
    MIXED_COLOR,
    LeafColumn,
    presence_columns,
    presence_matrix,
)
from jabuti.parsers.gff import GeneQuery, parse_gff3  # noqa: E402
from jabuti.parsers.newick import parse_newick_string  # noqa: E402
from jabuti.style import HeatmapStyle, LayoutKind, RenderStyle  # noqa: E402

GFF = "tests/data/gff"
P, A, M = "#2b6cb0", "#ffffff", "#d9d9d9"


def genomes():
    return {"Paraburkholderia_xenovorans_LB400": parse_gff3(f"{GFF}/LB400.gff3"),
            "Paraburkholderia_phymatum_STM815": parse_gff3(f"{GFF}/STM815.gff3")}


def test_presence_matrix_counts_copies():
    m = presence_matrix(genomes(), [GeneQuery("nifH"), GeneQuery("nodA")])
    assert m["nifH"] == {"Paraburkholderia_xenovorans_LB400": 1, "Paraburkholderia_phymatum_STM815": 2}
    assert m["nodA"]["Paraburkholderia_phymatum_STM815"] == 0


def test_presence_columns_colors_and_missing():
    m = presence_matrix(genomes(), [GeneQuery("nodA")])
    (col,) = presence_columns(m, P, A, M, show_counts=True)
    assert col.color_for("Paraburkholderia_xenovorans_LB400") == P
    assert col.color_for("Paraburkholderia_phymatum_STM815") == A
    assert col.color_for("folha_sem_gff") == M       # sem dado ≠ ausente


def test_counts_text_only_above_one():
    (col,) = presence_columns(presence_matrix(genomes(), [GeneQuery("nifH")]), P, A, M, show_counts=True)
    assert col.texts == {"Paraburkholderia_phymatum_STM815": "2"}


def test_group_color_mixed():
    col = LeafColumn("k", "h", {"a": P, "b": P, "c": A})
    assert col.color_for_group(["a", "b"]) == P
    assert col.color_for_group(["a", "c"]) == MIXED_COLOR


# ------------------------------------------------------------------ desenho
T = "((A:1,B:1):1,(C:1,(D:1,E:1):1):1);"


@pytest.fixture
def draw(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    keep = []

    def _draw(style=None, columns=None, collapsed=None):
        scene = QGraphicsScene()
        r = TreeRenderer(scene)
        res = r.render(parse_newick_string(T), style or RenderStyle(), None, collapsed, columns)
        keep.append(scene)
        return scene, r, res

    return _draw


def cols():
    return [LeafColumn("gene:x", "geneX", {"A": P, "B": A, "C": P, "D": A}, M, {"C": "3"}),
            LeafColumn("gene:y", "geneY", {"A": A, "B": A, "C": A, "D": A, "E": A}, M)]


def cells(scene, key):
    return {i.brush().color().name(): i for i in scene.items() if i.data(1) == "heatmap" and i.data(2) == key}


def n_rects(item):
    return len(item.path().toSubpathPolygons())


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_columns_drawn_with_missing(draw, layout):
    scene, _, _ = draw(RenderStyle(layout=layout), cols())
    x = cells(scene, "gene:x")
    assert set(x) == {P, A, M}
    assert n_rects(x[P]) == 2 and n_rects(x[A]) == 2 and n_rects(x[M]) == 1   # E sem dado
    assert n_rects(cells(scene, "gene:y")[A]) == 5


def test_rect_headers_and_counts(draw):
    scene, _, _ = draw(RenderStyle(heatmap=HeatmapStyle(show_headers=True)), cols())
    headers = sorted(i.text() for i in scene.items() if i.data(1) == "column-header")
    assert headers == ["geneX", "geneY"]
    texts = [i.text() for i in scene.items() if i.data(1) == "heatmap" and hasattr(i, "text")]
    assert texts == ["3"]
    scene, _, _ = draw(RenderStyle(heatmap=HeatmapStyle(show_headers=False)), cols())
    assert not [i for i in scene.items() if i.data(1) == "column-header"]


def test_rect_columns_right_of_labels(draw):
    scene, _, res = draw(RenderStyle(), cols())
    label_right = max(i.sceneBoundingRect().right() for items in res.leaf_items.values() for i in items)
    x0 = min(i.sceneBoundingRect().left() for i in scene.items() if i.data(1) == "heatmap" and not hasattr(i, "text"))
    assert x0 > label_right


def test_circular_rings_in_reserved_area(draw):
    scene, r, _ = draw(RenderStyle(layout=LayoutKind.CIRCULAR), cols())
    g = r.geometry
    assert len(g.ring_widths) == 2
    assert g.tip_ring < g.ring_bounds(0)[0] < g.ring_bounds(0)[1] < g.ring_bounds(1)[0] <= g.rings_end < g.label_radius
    # o anel da coluna y fica fora do anel da coluna x
    ry = cells(scene, "gene:y")[A].path().boundingRect()
    rx = cells(scene, "gene:x")[P].path().boundingRect()
    assert ry.width() > rx.width()


def test_collapsed_cell_mixed(draw):
    scene, _, _ = draw(RenderStyle(), cols(), [frozenset("CDE")])
    x = cells(scene, "gene:x")
    assert MIXED_COLOR in x                          # C=presente, D=ausente, E=sem dado
    assert n_rects(cells(scene, "gene:y")[A]) == 3   # A, B e o colapsado (todos ausentes)


def test_no_borders(draw):
    from PySide6.QtCore import Qt

    scene, _, _ = draw(RenderStyle(heatmap=HeatmapStyle(borders=False)), cols())
    assert all(i.pen().style() == Qt.PenStyle.NoPen for i in cells(scene, "gene:x").values())


@pytest.mark.parametrize("fmt", ["svg", "pdf", "png"])
def test_export_with_heatmap(draw, tmp_path, fmt):
    from jabuti.views import export

    scene, _, _ = draw(RenderStyle(layout=LayoutKind.CIRCULAR), cols())
    out = getattr(export, f"export_{fmt}")(scene, tmp_path / f"h.{fmt}")
    if fmt == "svg":
        assert P in out.read_text(encoding="utf-8").lower()


# ---------------------------------------------------------------- aba GFF
@pytest.fixture
def window(qtbot, monkeypatch, data_dir):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    shown = []
    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    win = MainWindow()
    win.shown = shown
    qtbot.addWidget(win)
    win.tree_tab.load(data_dir / "iqtree_ufboot.treefile")
    return win


def test_gui_load_and_automap(window, data_dir):
    gt = window.gff_tab
    n = gt.load_files([data_dir / "gff" / "LB400.gff3", data_dir / "gff" / "STM815.gff3"])
    assert n == 2
    assert gt.mapping == {"LB400": "Paraburkholderia_xenovorans_LB400",
                          "STM815": "Paraburkholderia_phymatum_STM815"}
    assert "4 folha(s) sem GFF" in gt.summary.text()


def test_gui_bad_files_reported_without_dialog(window, data_dir):
    gt = window.gff_tab
    n = gt.load_files([data_dir / "gff" / "broken.gff3", data_dir / "gff" / "LB400.gff3",
                       data_dir / "gff" / "nao_existe.gff3"])
    assert n == 1
    assert window.shown == []                        # nada modal
    assert gt.problems_box.isVisibleTo(gt)
    text = gt.problems.toPlainText()
    assert "broken.gff3" in text and "nao_existe.gff3" in text
    assert "2 erro(s)" in gt.problems_box.title()


def test_gui_same_file_twice_is_one_genome(window, data_dir):
    gt = window.gff_tab
    gt.load_files([data_dir / "gff" / "LB400.gff3", data_dir / "gff" / "LB400.gff3"])
    gt.load_files([data_dir / "gff" / "LB400.gff3"])
    assert [g.name for g in gt.genomes] == ["LB400"]


def test_gui_same_name_other_folder_gets_suffix(window, data_dir, tmp_path):
    import shutil

    other = tmp_path / "outra"
    other.mkdir()
    shutil.copy(data_dir / "gff" / "LB400.gff3", other / "LB400.gff3")
    gt = window.gff_tab
    gt.load_files([data_dir / "gff" / "LB400.gff3", other / "LB400.gff3"])
    assert [g.name for g in gt.genomes] == ["LB400", "LB400_2"]
    assert gt.mapping["LB400_2"] is None             # a folha já foi usada


def test_gui_manual_mapping_moves_leaf(window, data_dir):
    gt = window.gff_tab
    gt.load_files([data_dir / "gff" / "LB400.gff3", data_dir / "gff" / "STM815.gff3"])
    gt.set_mapping("STM815", "Paraburkholderia_xenovorans_LB400")
    assert gt.mapping == {"LB400": None, "STM815": "Paraburkholderia_xenovorans_LB400"}
    assert "STM815" in gt.manual
    gt.auto_map(reset=True)
    assert gt.mapping["LB400"] == "Paraburkholderia_xenovorans_LB400"


def test_gui_queries_render_heatmap(window, data_dir):
    gt = window.gff_tab
    gt.load_files([data_dir / "gff" / "LB400.gff3", data_dir / "gff" / "STM815.gff3"])
    for text in ("nifH", "nodA"):
        gt.query_edit.setText(text)
        gt.add_query()
    window.render_live()
    keys = {i.data(2) for i in window.canvas.tree_scene.items() if i.data(1) == "heatmap"}
    assert keys == {"gene:nifH", "gene:nodA"}
    assert "nifH  —  2/2 genomas" in gt.query_list.item(0).text()
    assert gt.preview.rowCount() == 1 and gt.preview.item(0, 1).text() == "BXE_0005"  # nodA selecionada
    titles = [g.title for g in window.style_panel.legend.groups]
    assert "Heatmap de genes" in titles
    gt.query_list.setCurrentRow(1)
    gt.move_query(-1)
    assert [q.title for q in gt.queries] == ["nodA", "nifH"]
    gt.remove_query()
    window.render_live()
    keys = {i.data(2) for i in window.canvas.tree_scene.items() if i.data(1) == "heatmap"}
    assert keys == {"gene:nifH"}


def test_gui_duplicate_and_bad_regex(window, data_dir):
    gt = window.gff_tab
    gt.load_files([data_dir / "gff" / "LB400.gff3"])
    gt.query_edit.setText("nifH")
    gt.add_query()
    gt.query_edit.setText("nifH")
    gt.add_query()
    assert len(gt.queries) == 1
    gt.f_regex.setChecked(True)
    gt.query_edit.setText("nif[")
    gt.add_query()
    assert len(gt.queries) == 1 and "regular inválida" in window.shown[-1]


def test_gui_circular_ring_legend(window, data_dir):
    gt = window.gff_tab
    gt.load_files([data_dir / "gff" / "LB400.gff3"])
    gt.query_edit.setText("nifH")
    gt.add_query()
    vt = window.viz_tab
    vt.layout_cb.setCurrentIndex(vt.layout_cb.findData(LayoutKind.CIRCULAR))
    window.generate()
    titles = [g.title for g in window.style_panel.legend.groups]
    assert any(t.startswith("Anéis") for t in titles)


def test_gui_mapping_survives_reroot(window, data_dir):
    gt = window.gff_tab
    gt.load_files([data_dir / "gff" / "LB400.gff3"])
    window.tree_tab.rb_mid.setChecked(True)
    window.tree_tab.apply_rooting()
    assert gt.mapping["LB400"] == "Paraburkholderia_xenovorans_LB400"


def test_heatmap_style_in_preset():
    from jabuti.presets import style_from_dict, style_to_dict

    st = RenderStyle(heatmap=HeatmapStyle(present_color="#2e7d32", show_counts=True, cell_width=1.5))
    assert style_from_dict(style_to_dict(st)) == st


def test_rect_headers_do_not_overlap(draw):
    narrow = [LeafColumn(f"gene:{i}", f"cabecalho_longo_{i}", {"A": P}, M, width=10) for i in range(4)]
    scene, _, _ = draw(RenderStyle(), narrow)
    boxes = sorted((i.sceneBoundingRect() for i in scene.items() if i.data(1) == "column-header"),
                   key=lambda b: b.left())
    assert len(boxes) == 4
    for a, b in zip(boxes, boxes[1:]):
        assert a.right() <= b.left() + 0.5
