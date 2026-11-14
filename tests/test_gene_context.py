"""Contexto gênico: coordenadas relativas, espelhamento, cores e desenho."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.annotations import OTHER_GENE_COLOR, context_extent, gene_context  # noqa: E402
from jabuti.parsers.gff import GeneQuery, parse_gff3  # noqa: E402
from jabuti.style import LayoutKind  # noqa: E402

LB = "Paraburkholderia_xenovorans_LB400"
STM = "Paraburkholderia_phymatum_STM815"


def genomes():
    return {LB: parse_gff3("tests/data/gff/LB400.gff3"), STM: parse_gff3("tests/data/gff/STM815.gff3")}


def test_forward_anchor_relative_coords():
    tracks = gene_context(genomes(), GeneQuery("nifD", fields=("gene",)), 1, [])
    t = tracks[LB]
    assert [g.label for g in t] == ["nifH", "nifD", "nifK"]
    anchor = next(g for g in t if g.is_anchor)
    assert anchor.start == -anchor.end            # centrado em 0
    assert all(g.forward for g in t)
    assert t[0].end < anchor.start < anchor.end < t[2].start


def test_reverse_anchor_is_mirrored():
    # em STM815 o primeiro nifH está na fita "-": a janela é espelhada
    tracks = gene_context(genomes(), GeneQuery("nifH", fields=("gene",)), 2, [])
    t = tracks[STM]
    anchor = next(g for g in t if g.is_anchor)
    assert anchor.forward                         # o âncora sempre "para a direita"
    # original: nifH(-) BPHY_0002(-) nifH(+) → espelhado: vizinhos à esquerda, em ordem inversa
    assert [g.locus_tag for g in t] == ["BPHY_0003", "BPHY_0002", "BPHY_0001"]
    assert next(g for g in t if g.locus_tag == "BPHY_0002").forward   # mesma fita do âncora
    copy2 = next(g for g in t if not g.is_anchor and g.label == "nifH")
    assert not copy2.forward                      # fita oposta à do âncora
    assert copy2.end < anchor.start


def test_colors_from_queries():
    q_nif = GeneQuery("nif", fields=("gene",))
    tracks = gene_context(genomes(), GeneQuery("nifD", fields=("gene",)), 3,
                          [(q_nif, "#ff0000"), (GeneQuery("nodA"), "#00ff00")])
    colors = {g.label: g.color for g in tracks[LB]}
    assert colors["nifH"] == colors["nifK"] == "#ff0000"
    assert colors["BXE_0004"] == OTHER_GENE_COLOR


def test_genome_without_anchor_is_skipped():
    tracks = gene_context(genomes(), GeneQuery("nodA"), 2, [])
    assert set(tracks) == {LB}


def test_extent():
    tracks = gene_context(genomes(), GeneQuery("nifD", fields=("gene",)), 1, [])
    assert context_extent(tracks) > 0 and context_extent({}) == 0


# ------------------------------------------------------------------- GUI
@pytest.fixture
def window(qtbot, monkeypatch, data_dir):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    win = MainWindow()
    qtbot.addWidget(win)
    win.tree_tab.load(data_dir / "iqtree_ufboot.treefile")
    gt = win.gff_tab
    gt.load_files([data_dir / "gff" / "LB400.gff3", data_dir / "gff" / "STM815.gff3"])
    for q in ("nifH", "nodA"):
        gt.query_edit.setText(q)
        gt.add_query()
    return win


def context_items(win):
    return [i for i in win.canvas.tree_scene.items() if i.data(1) == "gene-context"]


def test_gui_context_toggle_and_anchor(window):
    gt = window.gff_tab
    assert [gt.ctx_anchor.itemText(i) for i in range(gt.ctx_anchor.count())] == ["nifH", "nodA"]
    window.render_live()
    assert context_items(window) == []
    gt.ctx_enabled.setChecked(True)
    window.render_live()
    arrows = [i for i in context_items(window) if i.data(2) and not hasattr(i, "text")]
    assert len(arrows) >= 5
    anchors = [i for i in arrows if i.pen().widthF() == pytest.approx(1.2)]
    assert len(anchors) == 2                      # um âncora por genoma com nifH
    assert any(g.title.startswith("Contexto de nifH") for g in window.style_panel.legend.groups)
    gt.ctx_anchor.setCurrentIndex(1)              # nodA: só LB400
    window.render_live()
    anchors = [i for i in context_items(window)
               if i.data(2) and not hasattr(i, "text") and i.pen().widthF() == pytest.approx(1.2)]
    assert len(anchors) == 1


def test_gui_context_right_of_heatmap(window):
    window.gff_tab.ctx_enabled.setChecked(True)
    window.render_live()
    scene = window.canvas.tree_scene
    heat_right = max(i.sceneBoundingRect().right() for i in scene.items() if i.data(1) == "heatmap")
    ctx_left = min(i.sceneBoundingRect().left() for i in context_items(window))
    assert ctx_left > heat_right


def test_gui_context_not_in_circular(window):
    window.gff_tab.ctx_enabled.setChecked(True)
    vt = window.viz_tab
    vt.layout_cb.setCurrentIndex(vt.layout_cb.findData(LayoutKind.CIRCULAR))
    window.generate()
    assert context_items(window) == []
    assert "retangular" in window.statusBar().currentMessage()


def test_gui_context_labels_toggle(window):
    window.gff_tab.ctx_enabled.setChecked(True)
    window.style_panel.ctx_width.setValue(1200)
    window.render_live()
    assert any(hasattr(i, "text") for i in context_items(window))
    window.style_panel.ctx_labels.setChecked(False)
    window.render_live()
    assert not any(hasattr(i, "text") for i in context_items(window))


@pytest.mark.parametrize("fmt", ["svg", "pdf", "png"])
def test_export_with_context(window, tmp_path, fmt):
    from jabuti.views import export

    window.gff_tab.ctx_enabled.setChecked(True)
    window.render_live()
    out = getattr(export, f"export_{fmt}")(window.canvas.tree_scene, tmp_path / f"c.{fmt}")
    assert out.stat().st_size > 0


def test_gui_context_labels_inside_arrows(window):
    window.gff_tab.ctx_enabled.setChecked(True)
    window.style_panel.ctx_width.setValue(1500)
    window.render_live()
    items = context_items(window)
    arrows = [i for i in items if not hasattr(i, "text") and i.data(2)]
    for t in (i for i in items if hasattr(i, "text")):
        box = t.sceneBoundingRect()
        assert any(a.sceneBoundingRect().contains(box) for a in arrows), t.text()
