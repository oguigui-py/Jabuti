"""Anotações do iTOL — Etapa 1: leitor, TREE_COLORS, LABELS, DATASET_COLORSTRIP, DATASET_STYLE."""

from __future__ import annotations

import glob
from pathlib import Path

import pytest

from jabuti.models.itol_apply import ItolEntry, Resolver, apply_itol, dataset_entries
from jabuti.parsers.itol import ItolError, parse_color, parse_itol, sniff_itol, split_line
from jabuti.parsers.newick import load_tree

TREE = "examples/paraburkholderia_40.treefile"
EXAMPLES = sorted(glob.glob("examples/itol/*.txt"))
A00, A09 = "Paraburkholderia_xenovorans_A00", "Paraburkholderia_hospita_A09"
A02 = "Paraburkholderia_tropica_A02"
ROB = "Robbsia_andropogonis_LMG2129"


@pytest.fixture
def tree():
    return load_tree(TREE)


def write(tmp_path: Path, text: str, name: str = "a.txt") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def run(tree, *datasets):  # type: ignore[no-untyped-def]
    return apply_itol([ItolEntry(f"itol:{i}", d) for i, d in enumerate(datasets)], tree)


# --------------------------------------------------------------------- leitor
def test_parse_color():
    assert parse_color("#FF0000") == ("#ff0000", 1.0)
    assert parse_color("#f00") == ("#ff0000", 1.0)
    assert parse_color("rgb(0, 128, 255)") == ("#0080ff", 1.0)
    assert parse_color("rgba(255,0,0,0.5)") == ("#ff0000", 0.5)
    assert parse_color("vermelho") is None


@pytest.mark.parametrize("sep,line,expected", [
    ("TAB", "a\tb c\t  #fff ", ["a", "b c", "#fff"]),
    ("COMMA", 'a, "b, c" ,#fff', ["a", "b, c", "#fff"]),
    ("SPACE", 'a   "b c"  #fff', ["a", "b c", "#fff"]),
])
def test_split_each_separator(sep, line, expected):
    assert split_line(line, sep) == expected


def test_examples_parse_without_warnings():
    assert len(EXAMPLES) >= 4
    kinds = {parse_itol(p).kind for p in EXAMPLES}
    assert kinds == {"TREE_COLORS", "LABELS", "DATASET_COLORSTRIP", "DATASET_STYLE"}
    for p in EXAMPLES:
        assert parse_itol(p).warnings == [], p
        assert sniff_itol(p)


def test_header_comments_bom_crlf_and_mixed_header_separator(tmp_path):
    text = ("﻿# comentário\r\n\r\nDATASET_COLORSTRIP\r\nSEPARATOR SPACE\r\nDATASET_LABEL Hab\r\n"
            "LABEL_ALIGN_TO_TREE,0\r\n# outro\r\nDATA\r\n#ID cor\r\nX #ff0000 \"rótulo com espaço\"\r\n")
    ds = parse_itol(write(tmp_path, text))
    assert ds.kind == "DATASET_COLORSTRIP" and ds.separator == "SPACE" and ds.label == "Hab"
    assert ds.options["LABEL_ALIGN_TO_TREE"] == ["0"]
    assert [r.fields for r in ds.rows] == [["X", "#ff0000", "rótulo com espaço"]]
    assert ds.rows[0].line == 10
    assert ds.warnings == []


def test_unknown_option_warns_with_line(tmp_path):
    ds = parse_itol(write(tmp_path, "DATASET_COLORSTRIP\nSEPARATOR TAB\nFOO_BAR\t1\nDATA\nX\t#fff\n"))
    assert ds.warnings == [(3, "opção desconhecida FOO_BAR (ignorada)")]
    assert len(ds.rows) == 1


def test_unsupported_type_is_listed_and_ignored(tmp_path, tree):
    ds = parse_itol(write(tmp_path, "DATASET_PIECHART\nSEPARATOR COMMA\nDATA\nX,1,2\n"))
    assert not ds.supported and "não é suportado" in ds.warnings[0][1]
    fx = run(tree, ds)
    assert fx.stats["itol:0"].ignored == 1 and not fx.columns


@pytest.mark.parametrize("text,needle", [
    ("", "vazio"),
    ("# só comentário\n\n", "vazio"),
    ("nome\tvalor\nA\t1\n", "Não parece"),
])
def test_unreadable_files_raise_with_file_and_line(tmp_path, text, needle):
    p = write(tmp_path, text, "ruim.txt")
    with pytest.raises(ItolError) as err:
        parse_itol(p)
    assert needle in str(err.value) and "ruim.txt" in str(err.value)
    assert not sniff_itol(p)


def test_missing_separator_is_guessed_with_warning(tmp_path):
    ds = parse_itol(write(tmp_path, "LABELS\nDATA\nA,Nome A\n"))
    assert ds.separator == "COMMA" and ds.rows[0].fields == ["A", "Nome A"]
    assert "SEPARATOR" in ds.warnings[0][1]


def test_malformed_lines_are_counted_not_fatal(tmp_path, tree):
    text = f"TREE_COLORS\nSEPARATOR TAB\nDATA\n{A02}\n{A02}\tlabel\tnão-é-cor\n{A02}\tfoo\t#ff0000\n{A02}\tlabel\t#ff0000\n"
    fx = run(tree, parse_itol(write(tmp_path, text)))
    st = fx.stats["itol:0"]
    assert st.applied == 1 and st.ignored == 3
    assert [line for line, _ in st.problems] == [4, 5, 6]


# --------------------------------------------------------------------- IDs
def test_resolver_ids(tree):
    r = Resolver(tree, [f"{A00}|{A09}", "CONTAINS==hospita"])
    (node,), tol, why = r.resolve(f"{A00}|{A09}")
    assert why is None and not tol and len(node.leaves()) == 10
    assert r.resolve(f"{A00}---{A09}")[0] == [node]
    nodes, _, _ = r.resolve("CONTAINS==hospita")
    assert sorted(n.name for n in nodes) == ["Paraburkholderia_hospita_A09", "Paraburkholderia_hospita_B29"]
    assert r.resolve("Nao_existe")[2] == "folha não encontrada na árvore: Nao_existe"
    assert "não encontrada" in r.resolve(f"{A00}|Nao_existe")[2]


def test_resolver_tolerant_and_hidden(tree):
    r = Resolver(tree, ["LMG2129", A09], hidden=[A09])
    nodes, tol, _ = r.resolve("LMG2129")
    assert nodes[0].name == ROB and tol


def test_missing_leaves_are_counted(tree):
    fx = run(tree, *[parse_itol(p) for p in EXAMPLES])
    ign = sum(s.ignored for s in fx.stats.values())
    assert ign == 2
    msgs = [m for s in fx.stats.values() for _, m in s.problems]
    assert any("Folha_inexistente_X1" in m for m in msgs)


# --------------------------------------------------------------------- tipos
def test_tree_colors(tree):
    fx = run(tree, parse_itol("examples/itol/tree_colors.txt"))
    assert [r.label for r in fx.ranges] == ["Grupo A", "Grupo B"]
    assert len(fx.ranges[0].node.leaves()) == 10
    assert fx.legends[0].title == "Faixas" and fx.legends[0].entries[0] == ("Grupo A", "#d8ecf8")
    rob = next(n for n in tree.leaves() if n.name == ROB)
    assert fx.edge_looks[rob].dashed and fx.edge_looks[rob].color == "#7f8c8d"
    clade = [n for n, look in fx.node_looks.items() if look.color == "#c0392b"]
    assert len(clade) == 1 and {l.name for l in clade[0].leaves()} == {
        "Burkholderia_cepacia_ATCC25416", "Burkholderia_cenocepacia_J2315"}
    assert fx.edge_looks[clade[0]].width_factor == 2.0
    looks = {leaf: g.look for g in fx.label_groups for leaf in g.leaves}
    assert looks[A02].text_color == "#1f6fb2" and looks[A02].bold and looks[A02].size_scale == 1.2
    bg = looks["Paraburkholderia_sabiae_A11"]
    assert bg.background == "#ffd600" and bg.background_alpha == pytest.approx(0.6)


def test_labels(tree):
    fx = run(tree, parse_itol("examples/itol/labels.txt"))
    assert fx.names[ROB] == "Robbsia andropogonis (grupo externo)"
    assert fx.names["Burkholderia_cepacia_ATCC25416"] == "B. cepacia, ATCC 25416"


def test_labels_internal_node_is_ignored(tmp_path, tree):
    fx = run(tree, parse_itol(write(tmp_path, f"LABELS\nSEPARATOR COMMA\nDATA\n{A00}|{A09},Clado\n")))
    assert not fx.names and "nó interno" in fx.stats["itol:0"].problems[0][1]


def test_colorstrip(tree):
    ds = parse_itol("examples/itol/colorstrip.txt")
    fx = run(tree, ds)
    (ic,) = fx.columns
    assert ic.key == "itol:0" and ic.column.kind == "metadata" and ic.column.width == 18
    assert ic.column.colors[A00] == "#4e79a7"
    assert ic.legend.title == "Habitat (sintético)"
    assert ic.legend.entries == [("solo", "#4e79a7"), ("rizosfera", "#59a14f"), ("clínico", "#e15759")]
    assert not ic.column.texts                         # SHOW_STRIP_LABELS desligado
    assert not fx.edge_looks                           # COLOR_BRANCHES desligado


def test_colorstrip_internal_ids_color_branches_and_strip_labels(tmp_path, tree):
    text = (f"DATASET_COLORSTRIP\nSEPARATOR COMMA\nDATASET_LABEL,X\nCOLOR_BRANCHES,1\nSHOW_STRIP_LABELS,1\n"
            f"DATA\n{A00}|{A09},#ff0000,grupo\n")
    fx = run(tree, parse_itol(write(tmp_path, text)))
    col = fx.columns[0].column
    assert len(col.colors) == 10 and col.texts[A00] == "grupo"
    assert fx.columns[0].legend.entries == [("grupo", "#ff0000")]
    mrca_node = next(n for n, look in fx.node_looks.items() if len(n.leaves()) == 10)
    assert fx.edge_looks[mrca_node].color == "#ff0000"


def test_dataset_style(tree):
    fx = run(tree, parse_itol("examples/itol/styles.txt"))
    looks = {leaf: g.look for g in fx.label_groups for leaf in g.leaves}
    m = looks["Paraburkholderia_mimosarum_A13"]
    assert m.text_color == "#2e8b57" and m.bold and m.italic and m.background == "#e6f4ea"
    cab = next(n for n in tree.leaves() if n.name == "Caballeronia_glathei_DSM50014")
    assert fx.edge_looks[cab].dashed and fx.edge_looks[cab].width_factor == 2.0
    assert any(look.width_factor == 1.5 for look in fx.node_looks.values())


def test_color_edit_and_legend_label(tree):
    ds = parse_itol("examples/itol/colorstrip.txt")
    assert ("#4e79a7", "solo") in dataset_entries(ds)
    e = ItolEntry("itol:h", ds, colors={"#4e79a7": "#000000"}, labels={"#4e79a7": "terra"}, title="Hab")
    fx = apply_itol([e], tree)
    ic = fx.columns[0]
    assert ic.column.colors[A00] == "#000000" and ic.column.header == "Hab"
    assert ic.legend.title == "Hab" and ("terra", "#000000") in ic.legend.entries


def test_later_dataset_wins(tmp_path, tree):
    a = parse_itol(write(tmp_path, f"TREE_COLORS\nSEPARATOR TAB\nDATA\n{A02}\tlabel\t#ff0000\n", "a.txt"))
    b = parse_itol(write(tmp_path, f"TREE_COLORS\nSEPARATOR TAB\nDATA\n{A02}\tlabel\t#00ff00\n", "b.txt"))
    looks = {leaf: g.look for g in run(tree, a, b).label_groups for leaf in g.leaves}
    assert looks[A02].text_color == "#00ff00"


def test_invisible_entry_has_no_effect(tree):
    e = ItolEntry("itol:x", parse_itol("examples/itol/tree_colors.txt"), visible=False)
    fx = apply_itol([e], tree)
    assert not fx.ranges and not fx.label_groups and fx.branch_looks is None


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
    win.tree_tab.load(TREE)
    return win


def _tags(win, tag):  # type: ignore[no-untyped-def]
    return [i for i in win.renderer.scene.items() if i.data(1) == tag]


def _signature(win):  # type: ignore[no-untyped-def]
    return sorted((str(i.data(1)), round(i.sceneBoundingRect().x(), 1), round(i.sceneBoundingRect().width(), 1))
                  for i in win.renderer.scene.items())


def test_gui_import_in_background_and_toggle(window, qtbot):
    window.generate()
    before = _signature(window)
    itol = window.figure_panel.itol
    assert itol.import_files(EXAMPLES, wait=False) is False   # não bloqueia
    qtbot.waitUntil(lambda: not itol.is_loading(), timeout=5000)
    assert len(itol.entries) == 4
    window.generate()
    assert _tags(window, "range-background")
    assert any(i.data(1) == "metadata-strip" for i in window.renderer.scene.items())
    assert "Problemas" in window.statusBar().currentMessage() or "aplicadas" in window.statusBar().currentMessage()
    assert "Folha_inexistente_X1" in itol.report.toPlainText()
    assert "colorstrip.txt:" in itol.report.toPlainText()
    for e in list(itol.entries):
        itol.set_visible(e.key, False)
    window.generate()
    assert _signature(window) == before                       # desligado = cena igual
    while itol.entries:
        itol.list.setCurrentRow(0)
        itol.remove_current()
    window.generate()
    assert _signature(window) == before


def test_gui_strip_in_track_order_and_all_layouts(window, tmp_path):
    from jabuti.style import LayoutKind
    from jabuti.views.export import export_png, export_svg

    fp = window.figure_panel
    fp.itol.import_files(EXAMPLES, wait=True)
    window.generate()
    assert "itol:Habitat" in fp.track_keys()
    orig = window.current_style
    for kind in LayoutKind:
        def cs(kind=kind):  # type: ignore[no-untyped-def]
            s = orig()
            s.layout = kind
            return s
        window.current_style = cs
        window.generate()
        assert not window.shown, kind
        export_svg(window.renderer.scene, tmp_path / f"{kind.value}.svg")
        export_png(window.renderer.scene, tmp_path / f"{kind.value}.png", dpi=72)
    window.current_style = orig
    fp.hidden_tracks = ["itol:Habitat"]
    window.generate()
    assert not any(i.data(1) == "metadata-strip" for i in window.renderer.scene.items())


def test_gui_user_groups_and_name_table_win(window):
    from jabuti.models.label_groups import LabelLook

    fp = window.figure_panel
    fp.itol.import_files(EXAMPLES, wait=True)
    window.style_panel.label_groups.add([A02], "selection", look=LabelLook(text_color="#123456"))
    fp.name_map = {ROB: "Da tabela"}
    window.generate()
    res = window.canvas.result
    assert res.label_groups[A02].look.text_color == "#123456"
    assert res.display[ROB] == "Da tabela"
    assert res.display["Caballeronia_glathei_DSM50014"] == "Caballeronia glathei"


def test_gui_drop_routes_itol_files(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "import_itol", lambda paths, wait=False: calls.append(paths))
    from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
    from PySide6.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(Path(p).resolve())) for p in EXAMPLES])
    ev = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    window.dropEvent(ev)
    assert len(calls) == 1 and len(calls[0]) == 4


def test_gui_preset_roundtrip(window):
    from jabuti.presets import style_from_dict, style_to_dict

    fp = window.figure_panel
    fp.itol.import_files(["examples/itol/colorstrip.txt"], wait=True)
    e = fp.itol.entries[0]
    e.title = "Meu habitat"
    e.colors["#4e79a7"] = "#111111"
    fp.itol.set_visible(e.key, False)
    style = style_from_dict(style_to_dict(window.current_style()))
    (pref,) = style.figure.itol
    assert pref.key == "itol:Habitat" and not pref.visible and pref.title == "Meu habitat"
    assert dict(zip(pref.orig_colors, pref.new_colors)) == {"#4e79a7": "#111111"}
    # reimportar o mesmo dataset depois de abrir o preset recupera os ajustes
    fp.itol.remove_current()
    fp.load_style(style)
    fp.itol.import_files(["examples/itol/colorstrip.txt"], wait=True)
    e2 = fp.itol.entries[0]
    assert e2.title == "Meu habitat" and not e2.visible and e2.color("#4e79a7") == "#111111"


def test_space_separator_joins_extra_fields_into_label(tmp_path, tree):
    text = f"DATASET_COLORSTRIP\nSEPARATOR SPACE\nDATA\n{A00} #ff0000 solo de mata\n"
    fx = run(tree, parse_itol(write(tmp_path, text)))
    assert fx.columns[0].legend.entries == [("solo de mata", "#ff0000")]
    fx = run(tree, parse_itol(write(tmp_path, f"LABELS\nSEPARATOR SPACE\nDATA\n{A00} Nome com espaço\n", "l.txt")))
    assert fx.names[A00] == "Nome com espaço"
