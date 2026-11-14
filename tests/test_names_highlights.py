"""Etapa 3: nomes de exibição, destaque de linha inteira e clado a partir de lista."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.display_names import abbreviate_genus, compile_rules, display_names  # noqa: E402
from jabuti.models.document import RowHighlight  # noqa: E402
from jabuti.parsers.newick import parse_newick_string  # noqa: E402
from jabuti.style import LayoutKind, NameRules, RenderStyle  # noqa: E402

T = "((Cupriavidus_necator_H16:1,Cupriavidus_taiwanensis_LMG19424:1):1,(C:1,(D:1,E:1):1):1);"


# ------------------------------------------------------------------ nomes
def test_underscores_and_abbreviation():
    assert abbreviate_genus("Cupriavidus necator H16") == "C. necator H16"
    assert abbreviate_genus("Cupriavidus_necator") == "C._necator"
    assert abbreviate_genus("sp. 1") == "sp. 1"                     # sem gênero com maiúscula
    assert abbreviate_genus("Cupriavidus") == "Cupriavidus"         # só gênero: não abrevia
    out = display_names(["Cupriavidus_necator_H16"], NameRules(underscores=True, abbreviate_genus=True))
    assert out == {"Cupriavidus_necator_H16": "C. necator H16"}


def test_csv_then_rules_then_prefix_order():
    rules = NameRules(underscores=True, patterns=[r"LMG(\d+)"], replacements=[r"LMG \1"], mark_prefix="★ ")
    out = display_names(["a_b", "x_LMG5", "y"], rules, mapping={"a_b": "Nome_Novo"}, marked=["y"])
    assert out == {"a_b": "Nome Novo", "x_LMG5": "x LMG 5", "y": "★ y"}


def test_unchanged_names_left_out_and_bad_regex_ignored():
    rules = NameRules(patterns=["(", "z"], replacements=["", "Z"])
    _ok, errors = compile_rules(rules.patterns, rules.replacements)
    assert len(errors) == 1 and "inválida" in errors[0]
    assert display_names(["abc", "xyz"], rules) == {"xyz": "xyZ"}


def test_parse_name_table_warns_on_blank():
    from jabuti.models.display_names import parse_name_table
    from jabuti.parsers.metadata import parse_table_text

    table = parse_table_text("original,exibido\nA,Alfa\nB,\n")
    mapping, warns = parse_name_table(table)
    assert mapping == {"A": "Alfa"} and len(warns) == 1


@pytest.fixture
def draw(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    keep = []

    def _draw(style=None, **kw):
        scene = QGraphicsScene()
        res = TreeRenderer(scene).render(parse_newick_string(T), style or RenderStyle(), **kw)
        keep.append(scene)
        return scene, res

    return _draw


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_renderer_uses_display_name_but_keys_by_original(draw, layout):
    scene, res = draw(RenderStyle(layout=layout), names={"C": "Gamma longo"})
    (item,) = res.leaf_items["C"]
    assert item.text() == "Gamma longo" and item.data(3) == "C"
    assert res.display == {"C": "Gamma longo"}


def test_search_matches_original_and_display(draw):
    from jabuti.views.canvas import TreeCanvas

    canvas = TreeCanvas()
    _scene, res = draw(names={"C": "Gamma"})
    canvas.result = res
    assert canvas.search("gamma") == ["C"]
    assert canvas.search("C") == ["C"]                               # exato pelo original
    assert set(canvas.search("cupriavidus")) == {"Cupriavidus_necator_H16", "Cupriavidus_taiwanensis_LMG19424"}


# --------------------------------------------------------------- destaques
def tagged(scene, tag):
    return [i for i in scene.items() if i.data(1) == tag]


def test_highlight_contiguous_leaves_one_band_across_columns(draw):
    from jabuti.models.tracks import bar_track

    hl = RowHighlight(frozenset({"C", "D", "E"}), "#ff0000", 0.3, "#000000", 1.5)
    bars = bar_track("bar:x", "x", {"C": 1.0, "D": 2.0})
    scene, res = draw(columns=[bars], highlights=[hl])
    (band,) = tagged(scene, "row-highlight")                         # C, D, E vizinhas: uma faixa
    assert band.zValue() == -3 and band.pen().widthF() == 1.5
    assert band.brush().color().alphaF() == pytest.approx(0.3, abs=0.01)
    r = band.sceneBoundingRect()
    bar_right = max(i.sceneBoundingRect().right() for i in tagged(scene, "bar"))
    label = res.leaf_items["C"][0].sceneBoundingRect()
    assert r.left() <= label.left() and r.right() >= bar_right


def test_highlight_split_when_not_contiguous(draw):
    hl = RowHighlight(frozenset({"Cupriavidus_necator_H16", "C"}))
    scene, _ = draw(highlights=[hl])
    assert len(tagged(scene, "row-highlight")) == 2


def test_highlight_thickness_and_no_outline(draw):
    full, _ = draw(highlights=[RowHighlight(frozenset({"C"}), thickness=1.0)])
    half, _ = draw(highlights=[RowHighlight(frozenset({"C"}), outline=None, thickness=0.5)])
    (a,), (b,) = tagged(full, "row-highlight"), tagged(half, "row-highlight")
    assert b.path().boundingRect().height() == pytest.approx(a.path().boundingRect().height() / 2)
    assert b.pen().style().name == "NoPen"


def test_highlight_circular_is_sector_outside_tips(draw):
    scene, res = draw(RenderStyle(layout=LayoutKind.CIRCULAR), highlights=[RowHighlight(frozenset({"D"}))])
    (band,) = tagged(scene, "row-highlight")
    label = res.leaf_items["D"][0].sceneBoundingRect().center()
    assert band.path().contains(label)                              # o rótulo fica dentro do setor
    assert not band.path().contains(res.leaf_points["C"])           # e a vizinha fora


def test_preset_roundtrip_marked_and_highlights():
    from jabuti.models.clades import CladeSet
    from jabuti.models.document import TreeEdits
    from jabuti.presets import preset_from_dict, preset_to_dict

    edits = TreeEdits(marked={"C"}, highlights=[RowHighlight(frozenset("DE"), "#00ff00", 0.5, None, 2.0, 0.6)])
    st = RenderStyle()
    st.figure.names = NameRules(True, [r"_(\d+)"], [r" \1"], True, "* ")
    loaded = preset_from_dict(preset_to_dict(st, CladeSet(), edits))
    assert loaded.warnings == []
    assert loaded.edits.marked == {"C"} and loaded.edits.highlights == edits.highlights
    assert loaded.style.figure.names == st.figure.names
    bad = preset_from_dict({"version": 1, "edits": {"highlights": [{"leaves": ["A"], "color": "red",
                                                                     "thickness": 3}]}})
    assert bad.edits.highlights[0].color == "#ffe066" and len(bad.warnings) == 2


# ------------------------------------------------------------ clado por lista
def test_clade_from_names_tolerant_matching():
    from jabuti.models.clades import clade_from_names

    tree = parse_newick_string(T)
    leaves, unknown, extras = clade_from_names(tree, ["H16", "LMG19424", "zzz"])
    assert leaves == {"Cupriavidus_necator_H16", "Cupriavidus_taiwanensis_LMG19424"}
    assert unknown == ["zzz"] and extras == []
    leaves, _u, extras = clade_from_names(tree, ["C", "D"])
    assert extras == ["E"] and leaves == {"C", "D", "E"}
    assert clade_from_names(tree, ["nada"])[0] == frozenset()


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


def test_gui_rules_and_name_table(window, tmp_path):
    fp = window.figure_panel
    fp.opt_underscores.setChecked(True)
    fp.opt_abbrev.setChecked(True)
    window.render_live()
    item = window.canvas.result.leaf_items["Paraburkholderia_tropica_A02"][0]
    assert item.text() == "P. tropica A02"
    path = tmp_path / "nomes.csv"
    path.write_text("original,exibido\nParaburkholderia_tropica_A02,Minha_tropica\nnao_existe,X\n", encoding="utf-8")
    assert fp.load_name_table(path)
    assert "nao_existe" in fp.names_report.text()
    window.render_live()
    assert window.canvas.result.leaf_items["Paraburkholderia_tropica_A02"][0].text() == "M. tropica"
    window.search_box.setText("tropica_A02")                        # original continua na busca
    window.do_search()
    assert window.canvas.selected == ["Paraburkholderia_tropica_A02"]
    data = window.collect_preset()
    assert "nao_existe" not in str(data)                            # a tabela (dados) fica fora do preset


def test_gui_mark_and_highlight_selection(window):
    fp = window.figure_panel
    sel = ["Paraburkholderia_tropica_A02", "Paraburkholderia_unamae_A03"]
    window.canvas.set_selection(sel)
    fp.mark_selected(True)
    fp.highlight_selected()
    window.render_live()
    assert window.canvas.result.leaf_items[sel[0]][0].text().startswith("★ ")
    assert len(tagged(window.canvas.tree_scene, "row-highlight")) == 1
    fp.hl_alpha.setValue(80)
    assert window.style_panel.edits.highlights[0].alpha == 0.8
    fp.remove_highlight()
    window.render_live()
    assert not tagged(window.canvas.tree_scene, "row-highlight")


def test_gui_clade_from_list(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    fp = window.figure_panel
    fp.list_edit.setPlainText("A10\nA11\n# comentário\nA12\tqualquer coisa\nA13\nxyz\n")
    fp.list_name.setText("Grupo")
    fp._create_clade_from_list()
    clade = window.style_panel.clade_set.clades[-1]
    assert clade.name == "Grupo" and len(clade.leaves) == 4
    assert "xyz" in fp.list_report.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    n = len(window.style_panel.clade_set.clades)
    fp.list_edit.setPlainText("A00\nB35")                             # não monofilético
    fp._create_clade_from_list()
    assert len(window.style_panel.clade_set.clades) == n and "Cancelado" in fp.list_report.text()
