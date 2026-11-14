"""Metadados: cores (categoria/gradiente), rótulos/ramos, faixas, aba e presets."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.annotations import GRADIENT, gradient_color, metadata_colors, metadata_column  # noqa: E402
from jabuti.models.clades import Clade  # noqa: E402
from jabuti.parsers.newick import parse_newick_string  # noqa: E402
from jabuti.style import LayoutKind, MetadataStyle, RenderStyle  # noqa: E402

PAL = ["#111111", "#222222", "#333333"]
ROWS = {
    "A": {"hab": "soil", "gc": "60"},
    "B": {"hab": "soil", "gc": "62"},
    "C": {"hab": "nodule", "gc": "64"},
    "D": {"hab": "NA", "gc": "66"},
    "E": {"hab": "clinical", "gc": "n/a"},
}


def test_categorical_by_frequency():
    colors, legend = metadata_colors(ROWS, "hab", PAL)
    assert colors["A"] == colors["B"] == PAL[0]            # soil (2) primeiro
    assert colors["E"] == PAL[1] and colors["C"] == PAL[2]  # clinical < nodule (empate: alfabético)
    assert "D" not in colors                                 # NA = ausente
    assert [e[0] for e in legend.entries] == ["soil (2)", "clinical (1)", "nodule (1)"]


def test_numeric_gradient():
    colors, legend = metadata_colors(ROWS, "gc", PAL)
    assert colors["A"] == GRADIENT[0] and colors["D"] == GRADIENT[-1]
    assert "E" not in colors
    assert [e[0] for e in legend.entries] == ["60", "63", "66"]


def test_too_many_categories_warns():
    rows = {str(i): {"x": f"c{i}"} for i in range(5)}
    _, legend = metadata_colors(rows, "x", PAL)
    assert legend.entries[-1][0].startswith("⚠")


def test_gradient_endpoints():
    assert gradient_color(0) == GRADIENT[0] and gradient_color(1) == GRADIENT[-1]
    assert gradient_color(-5) == GRADIENT[0] and gradient_color(9) == GRADIENT[-1]


def test_metadata_column():
    col, _ = metadata_column(ROWS, "hab", PAL, "#eeeeee", width=20)
    assert col.kind == "metadata" and col.width == 20
    assert col.color_for("D") == "#eeeeee"


# ------------------------------------------------------------------ desenho
T = "((A:1,B:1):1,(C:1,(D:1,E:1):1):1);"


@pytest.fixture
def draw(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    keep = []

    def _draw(style=None, meta=None, columns=None, clades=None):
        scene = QGraphicsScene()
        res = TreeRenderer(scene).render(parse_newick_string(T), style or RenderStyle(), clades, None,
                                         columns, meta)
        keep.append(scene)
        return scene, res

    return _draw


META = {"A": "#aa0000", "B": "#aa0000", "C": "#00aa00"}


def branch_colors(scene):
    return {i.pen().color().name() for i in scene.items() if i.data(1) == "branches"}


def test_meta_labels_override_clades(draw):
    clades = [Clade("ab", frozenset("AB"), color="#0000ff")]
    _, res = draw(RenderStyle(), META, clades=clades)
    assert res.leaf_items["A"][0].brush().color().name() == "#aa0000"
    assert res.leaf_items["D"][0].brush().color().name() == "#8a8a8a"  # sem metadado: regra dos clados (neutro)


def test_meta_labels_off(draw):
    _, res = draw(RenderStyle(metadata=MetadataStyle(color_labels=False)), META)
    assert res.leaf_items["A"][0].brush().color().name() == "#202020"


def test_meta_branches_propagate_uniform(draw):
    scene, _ = draw(RenderStyle(metadata=MetadataStyle(color_branches=True)), META)
    colors = branch_colors(scene)
    assert {"#aa0000", "#00aa00", "#202020"} <= colors
    # o conector do nó (A,B) é vermelho (ambas as folhas iguais); a raiz é mista -> cor base
    scene2, _ = draw(RenderStyle(metadata=MetadataStyle(color_branches=True)), {"A": "#aa0000", "B": "#aa0000"})
    assert branch_colors(scene2) == {"#aa0000", "#202020"}


def test_meta_branches_off_by_default(draw):
    scene, _ = draw(RenderStyle(), META)
    assert branch_colors(scene) == {"#202020"}


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_metadata_strip_drawn(draw, layout):
    col, _ = metadata_column(ROWS, "hab", PAL, "#eeeeee", width=20)
    scene, _ = draw(RenderStyle(layout=layout), columns=[col])
    items = [i for i in scene.items() if i.data(1) == "metadata-strip"]
    assert {i.brush().color().name() for i in items} == {PAL[0], PAL[1], PAL[2], "#eeeeee"}


# --------------------------------------------------------------------- GUI
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


def test_gui_load_guess_key_and_report(window):
    mt = window.metadata_tab
    assert mt.load("examples/metadata.tsv")
    assert mt.key_column() == "genome"
    assert len(mt.by_leaf()) == 40
    assert "40/40 folhas" in mt.report.text()
    sp = window.style_panel
    assert sp.color_by.isEnabled() and sp.meta_strips.count() == 4
    assert "gc_percent (numérica)" in [sp.color_by.itemText(i) for i in range(sp.color_by.count())]


def test_gui_color_by_and_strips(window):
    window.metadata_tab.load("examples/metadata.tsv")
    sp = window.style_panel
    sp.color_by.setCurrentIndex(sp.color_by.findData("habitat"))
    sp.set_strip_checked("gc_percent", True)
    sp.set_strip_checked("symbiont", True)
    window.render_live()
    titles = [g.title for g in sp.legend.groups]
    assert titles[:3] == ["Cor: habitat", "Faixa: symbiont", "Faixa: gc_percent"]  # ordem da tabela
    keys = {i.data(2) for i in window.canvas.tree_scene.items() if i.data(1) == "metadata-strip"}
    assert keys == {"meta:gc_percent", "meta:symbiont"}
    label_colors = {it.brush().color().name() for items in window.canvas.result.leaf_items.values() for it in items}
    assert len(label_colors) >= 3


def test_gui_partial_match_report(window, tmp_path):
    p = tmp_path / "m.tsv"
    p.write_text("strain\thab\nA00\tsoil\nA01\tnodule\nZZZ\tsoil\n")
    mt = window.metadata_tab
    mt.load(p)
    assert mt.key_column() == "strain"
    assert "2/40 folhas" in mt.report.text() and "Sem metadados (38)" in mt.report.text()
    assert "ZZZ" in mt.report.text()


def test_gui_bad_metadata_shows_error(window, tmp_path):
    p = tmp_path / "bad.tsv"
    p.write_text("uma_coluna\nvalor\n")
    assert not window.metadata_tab.load(p)
    assert window.shown and "pelo menos 2 colunas" in window.shown[-1]


def test_gui_strips_and_heatmap_order(window):
    import glob

    window.metadata_tab.load("examples/metadata.tsv")
    window.gff_tab.load_files(sorted(glob.glob("examples/gff/*.gff3"))[:5])
    window.gff_tab.query_edit.setText("nifH")
    window.gff_tab.add_query()
    sp = window.style_panel
    sp.set_strip_checked("habitat", True)
    columns, _, _ = window.annotation_columns(window.current_style())
    assert [c.key for c in columns] == ["meta:habitat", "gene:nifH"]


def test_gui_metadata_in_preset_and_pending(window, tmp_path, qtbot):
    window.metadata_tab.load("examples/metadata.tsv")
    sp = window.style_panel
    sp.color_by.setCurrentIndex(sp.color_by.findData("habitat"))
    sp.set_strip_checked("gc_percent", True)
    sp.meta_branches.setChecked(True)
    saved = window.collect_preset(include_tree_state=False)
    assert saved["style"]["metadata"]["strips"] == ["gc_percent"]

    from jabuti.presets import preset_from_dict
    from jabuti.views.main_window import MainWindow

    other = MainWindow()
    qtbot.addWidget(other)
    other.tree_tab.load("examples/paraburkholderia_40.treefile")
    other.apply_preset(preset_from_dict(saved))       # antes de abrir a tabela
    other.metadata_tab.load("examples/metadata.tsv")  # escolhas pendentes aplicadas agora
    st = other.current_style()
    assert st.metadata.color_by == "habitat" and st.metadata.strips == ["gc_percent"]
    assert st.metadata.color_branches
