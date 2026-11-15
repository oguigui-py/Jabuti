"""Exportação para o iTOL: Newick, datasets nos templates oficiais e ida e volta."""

from __future__ import annotations

import glob
import os
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from jabuti.exporters.itol_export import (  # noqa: E402
    README_FILE,
    TREE_FILE,
    node_id,
    plan_export,
    write_export,
)
from jabuti.models.color_rules import ColorRules  # noqa: E402
from jabuti.models.tracks import BarTrack, StackedTrack  # noqa: E402
from jabuti.parsers.itol import parse_itol  # noqa: E402
from jabuti.parsers.newick import parse_newick_string, write_newick  # noqa: E402

TREE = "examples/paraburkholderia_40.treefile"
ITOL_EXAMPLES = sorted(glob.glob("examples/itol/*.txt"))


def _sig(tree):  # type: ignore[no-untyped-def]
    return [(n.name, n.length, tuple(n.supports), len(n.children)) for n in tree.root.traverse_preorder()]


# ------------------------------------------------------------------ Newick
def test_write_newick_roundtrip_file():
    from jabuti.parsers.newick import load_tree

    t = load_tree(TREE)
    assert _sig(parse_newick_string(write_newick(t))) == _sig(t)


def test_write_newick_quotes_supports_and_lengths():
    t = parse_newick_string("(('it''s here':2.5,b:1)90/88:0.1,(c,d)1e-3:3,e:0);")
    text = write_newick(t)
    assert "'it''s here':2.5" in text and ")90/88:0.1" in text and "e:0" in text
    assert _sig(parse_newick_string(text)) == _sig(t)
    assert text.endswith(";\n")


def test_node_id_is_mrca_of_first_and_last_leaf():
    from jabuti.models.clades import mrca

    t = parse_newick_string("((a,(b,c)),(d,e));")
    for n in t.root.traverse_preorder():
        if not n.is_leaf:
            a, b = node_id(n).split("|")
            assert mrca(t, frozenset({a, b})) is n


# ------------------------------------------------------------------ janela
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


def _reimport(qtbot, folder):  # type: ignore[no-untyped-def]
    """Janela nova com a árvore exportada e todos os datasets gerados."""
    from jabuti.views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.tree_tab.load(str(folder / TREE_FILE))
    win.import_itol(sorted(str(p) for p in folder.glob("[0-9]*.txt")), wait=True)
    win.generate()
    return win


def _leafset(n):  # type: ignore[no-untyped-def]
    return frozenset(l.name for l in n.leaves())


def _compare_looks(a, b) -> list:  # type: ignore[no-untyped-def]
    r1 = ColorRules(a.tree, a.style, a.clades, a.meta_colors, a.branch_looks, a.groups)
    r2 = ColorRules(b.tree, b.style, b.clades, b.meta_colors, b.branch_looks, b.groups)
    other = {_leafset(n): n for n in b.tree.root.traverse_preorder()}
    bad = []
    for n in a.tree.root.traverse_preorder():
        m = other[_leafset(n)]
        if n.parent is not None and r1.edge_pen(n) != r2.edge_pen(m):
            bad.append(("ramo", node_id(n), r1.edge_pen(n), r2.edge_pen(m)))
        if not n.is_leaf and r1.node_pen(n) != r2.node_pen(m):
            bad.append(("conector", node_id(n), r1.node_pen(n), r2.node_pen(m)))
        if n.is_leaf:
            p, q = r1.label_paint(n), r2.label_paint(m)
            if (p.color, p.bold, p.italic, p.size_scale, p.background) != \
                    (q.color, q.bold, q.italic, q.size_scale, q.background):
                bad.append(("rótulo", n.name, p, q))
    return bad


def _columns(snap) -> dict:  # type: ignore[no-untyped-def]
    """Valores de cada coluna por tipo, independentes das chaves internas."""
    out: dict[str, list] = {"strip": [], "bar": [], "stacked": [], "heat": [], "binary": []}
    for b in snap.blocks:
        for t in b.tracks:
            if isinstance(t, BarTrack):
                out["bar"].append(dict(t.values))
            elif isinstance(t, StackedTrack):
                out["stacked"].append((list(t.colors), {k: [v or 0 for v in vs] for k, vs in t.values.items()}))
            elif getattr(t, "kind", None) == "metadata" or t == "clade-strip":
                if t != "clade-strip":
                    out["strip"].append(dict(t.colors))
            elif t.kind == "matrix":
                out["heat"].append((t.header, dict(t.values)))
            elif t.kind == "genes":
                out["binary"].append((t.header, {k: v > 0 for k, v in t.values.items()}))
            elif t.kind == "binary" and not t.shape_colors:
                out["binary"].append((t.header, {k: f for k, (_s, f) in t.shapes.items()}))
    return out


def test_roundtrip_imported_itol_examples(window, qtbot, tmp_path):
    window.import_itol(ITOL_EXAMPLES, wait=True)
    out = window.export_itol(str(tmp_path / "exp"), as_zip=False)
    a = window._snapshot
    b = _reimport(qtbot, out)._snapshot
    assert _compare_looks(a, b) == []
    assert a.names == b.names and any(a.names[k] != k for k in a.names)
    assert sorted(map(_leafset, a.collapsed)) == sorted(map(_leafset, b.collapsed)) != []
    assert [blk.label for blk in a.blocks] == [blk.label for blk in b.blocks]
    assert _columns(a) == _columns(b)
    ma = sorted((m.kind, node_id(m.node), round(m.frac, 3), m.color, m.text) for m in a.marks)
    mb = sorted((m.kind, node_id(m.node), round(m.frac, 3), m.color, m.text) for m in b.marks)
    assert ma == mb and ma


def test_roundtrip_edited_itol_colors_and_titles(window, qtbot, tmp_path):
    """O que sai é a versão atual do dataset importado (cor e título editados)."""
    window.import_itol(["examples/itol/colorstrip.txt"], wait=True)
    entry = window.figure_panel.itol.entries[0]
    old = next(iter(entry.dataset.rows)).fields[1]
    from jabuti.parsers.itol import parse_color

    orig = parse_color(old)[0]
    entry.colors[orig] = "#123456"
    entry.title = "Habitat editado"
    window.figure_panel.itol.changed.emit()
    out = window.export_itol(str(tmp_path / "exp"), as_zip=False)
    text = next(p for p in out.glob("*faixa*")).read_text()
    assert "DATASET_LABEL\tHabitat editado" in text and "#123456" in text and orig not in text.split("DATA\n")[1]


def test_roundtrip_jabuti_features(window, qtbot, tmp_path):
    """Clados com fundo, grupos de rótulo, metadados, barras, empilhadas, matriz, genes,
    colapso, folha oculta e ramo encurtado."""
    from PySide6.QtCore import Qt

    sp, fp = window.style_panel, window.figure_panel
    sp.detect()
    sp.opt_background.setChecked(True)
    sp.opt_label_bg.setChecked(True)
    names = window.tree.leaf_names()
    sp.label_panel.style_leaves(names[5:8], text_color="#aa0000", bold=True)
    window.metadata_tab.load("examples/metadata.tsv")
    sp.color_by.setCurrentIndex(sp.color_by.findData("habitat"))
    sp.meta_branches.setChecked(True)
    sp.set_strip_checked("symbiont", True)
    assert fp.load_table("examples/traits.tsv")
    fp.add_bar()
    fp.add_stacked()
    for i in range(fp.st_series.count()):
        item = fp.st_series.item(i)
        if item.data(Qt.ItemDataRole.UserRole) in ("genome_size_mb", "n_contigs"):
            item.setCheckState(Qt.CheckState.Unchecked)
    assert fp.load_table("examples/cazy_counts.tsv")
    fp.add_matrix()
    fp.mx_top.setValue(4)
    window.gff_tab.load_files(sorted(glob.glob("examples/gff/*.gff3"))[:6])
    window.gff_tab.query_edit.setText("nifH")
    window.gff_tab.add_query()
    fp.name_map = {names[0]: "Outgroup renomeado"}
    fp.hide_leaves([names[-1]])
    tree = window.display_tree or window.tree
    inner = next(n for n in tree.root.traverse_preorder() if not n.is_leaf and 2 < len(n.leaves()) < 6)
    sp.collapse(_leafset(inner))
    long = max((n for n in tree.root.traverse_preorder() if n.parent is not None and n.length),
               key=lambda n: n.length)
    sp.edits.set_short(_leafset(long), long.length / 3)
    window.render_live()

    out = window.export_itol(str(tmp_path / "exp"), as_zip=False)
    plan_warnings = (out / README_FILE).read_text()
    assert "encurtado" in plan_warnings and "oculta" in plan_warnings
    a = window._snapshot
    from jabuti.parsers.newick import load_tree

    exported = load_tree(out / TREE_FILE)
    assert names[-1] not in exported.leaf_names() and len(exported.leaves()) == len(names) - 1
    lens = {_leafset(n): n.length for n in exported.root.traverse_preorder()}
    assert lens[_leafset(long)] == pytest.approx(long.length)          # comprimento original
    b = _reimport(qtbot, out)._snapshot
    assert _compare_looks(a, b) == []
    assert b.names[names[0]] == "Outgroup renomeado"
    assert sorted(map(_leafset, a.collapsed)) == sorted(map(_leafset, b.collapsed))
    ca, cb = _columns(a), _columns(b)
    assert ca["strip"] and ca["strip"] == cb["strip"]
    assert ca["bar"] and ca["bar"] == cb["bar"]
    assert ca["stacked"] and ca["stacked"] == cb["stacked"]
    assert len(ca["heat"]) == 4 and ca["heat"] == cb["heat"]
    assert ca["binary"] and ca["binary"] == cb["binary"]
    # a faixa de clados e os fundos de clado viram COLORSTRIP e "range"
    colors = (out / "01_tree_colors.txt").read_text()
    assert "\trange\t" in colors and "\tlabel_background\t" in colors
    assert len(b.ranges) == sum(1 for rc in a.clades if rc.valid and rc.clade.visible)


# ------------------------------------------------------------ templates oficiais
# Campos obrigatórios do cabeçalho e nº mínimo de campos por linha de dados, conforme os
# templates de https://itol.embl.de/help (conferidos manualmente; o teste não usa rede).
REQUIRED = {
    "TREE_COLORS": ((), 3),
    "LABELS": ((), 2),
    "COLLAPSE": ((), 1),
    "DATASET_COLORSTRIP": (("DATASET_LABEL", "COLOR"), 2),
    "DATASET_SIMPLEBAR": (("DATASET_LABEL", "COLOR"), 2),
    "DATASET_MULTIBAR": (("DATASET_LABEL", "COLOR", "FIELD_COLORS", "FIELD_LABELS"), 2),
    "DATASET_HEATMAP": (("DATASET_LABEL", "COLOR", "FIELD_LABELS"), 2),
    "DATASET_BINARY": (("DATASET_LABEL", "COLOR", "FIELD_SHAPES", "FIELD_LABELS"), 2),
    "DATASET_STYLE": (("DATASET_LABEL", "COLOR"), 4),
    "DATASET_SYMBOL": (("DATASET_LABEL", "COLOR", "MAXIMUM_SIZE"), 6),
    "DATASET_TEXT": (("DATASET_LABEL", "COLOR"), 2),
}
NFIELDS = {"DATASET_MULTIBAR": "FIELD_LABELS", "DATASET_HEATMAP": "FIELD_LABELS", "DATASET_BINARY": "FIELD_LABELS"}


def check_template(text: str) -> str:
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    kind = lines[0].strip()
    assert kind in REQUIRED, kind
    opts, min_fields = REQUIRED[kind]
    data = lines.index("DATA")
    head = {l.split("\t")[0]: l.split("\t")[1:] for l in lines[1:data]}
    if kind == "COLLAPSE":
        assert not any(l.startswith("SEPARATOR") for l in lines)
    else:
        assert lines[1] == "SEPARATOR TAB"
    for o in opts:
        assert head.get(o), (kind, o)
    if kind in NFIELDS:
        n = len(head[NFIELDS[kind]])
        if kind == "DATASET_BINARY":
            assert len(head["FIELD_SHAPES"]) == n
        if "FIELD_COLORS" in head:
            assert len(head["FIELD_COLORS"]) == n
    if "LEGEND_COLORS" in head:
        assert len(head["LEGEND_COLORS"]) == len(head["LEGEND_LABELS"]) == len(head["LEGEND_SHAPES"])
    rows = lines[data + 1:]
    assert rows
    for r in rows:
        fields = r.split("\t")
        assert len(fields) >= min_fields, (kind, r)
        if kind in NFIELDS:
            assert len(fields) - 1 == n, (kind, r)
    return kind


def test_generated_files_follow_official_templates(window, tmp_path):
    window.import_itol(ITOL_EXAMPLES, wait=True)
    window.style_panel.detect()
    window.style_panel.opt_background.setChecked(True)
    window.render_live()
    out = window.export_itol(str(tmp_path / "exp"), as_zip=False)
    kinds = set()
    for p in sorted(out.glob("[0-9]*.txt")):
        kinds.add(check_template(p.read_text()))
        ds = parse_itol(p)
        assert ds.supported and ds.warnings == [], (p.name, ds.warnings)
    assert {"TREE_COLORS", "LABELS", "COLLAPSE", "DATASET_COLORSTRIP", "DATASET_SIMPLEBAR",
            "DATASET_MULTIBAR", "DATASET_HEATMAP", "DATASET_BINARY", "DATASET_STYLE", "DATASET_SYMBOL",
            "DATASET_TEXT"} <= kinds


def test_reimported_files_have_no_problems(window, qtbot, tmp_path):
    window.import_itol(ITOL_EXAMPLES, wait=True)
    out = window.export_itol(str(tmp_path / "exp"), as_zip=False)
    win = _reimport(qtbot, out)
    fx = win.itol_effects(win.current_style())
    problems = {k: s.problems for k, s in fx.stats.items() if s.problems or s.ignored}
    assert problems == {}


# ------------------------------------------------------------------ interface
def test_export_button_folder_and_zip(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    window.import_itol(["examples/itol/colorstrip.txt"], wait=True)
    seen = []

    def fake_exec(box):  # type: ignore[no-untyped-def]
        seen.append(box.informativeText())
        wanted = fake_exec.choice
        box._chosen = next(b for b in box.buttons() if b.text() == wanted)
        return 0

    fake_exec.choice = "Salvar pasta…"
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box._chosen)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    window.figure_panel.itol.export_btn.click()
    folder = tmp_path / "paraburkholderia_40_itol"
    assert (folder / TREE_FILE).exists() and (folder / README_FILE).exists()
    assert "DATASET_COLORSTRIP" in seen[-1] and "arvore.nwk" in seen[-1]

    fake_exec.choice = "Salvar .zip…"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "x.zip"), ""))
    window.export_itol()
    with zipfile.ZipFile(tmp_path / "x.zip") as z:
        names = z.namelist()
    assert f"x/{TREE_FILE}" in names and f"x/{README_FILE}" in names

    fake_exec.choice = "Cancelar"
    assert window.export_itol() is None


def test_export_without_tree_reports(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    shown = []
    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    win = MainWindow()
    qtbot.addWidget(win)
    assert win.export_itol() is None and "Abra uma árvore" in shown[-1]


def test_readme_lists_files_and_not_exported(window, tmp_path):
    window.import_itol(ITOL_EXAMPLES, wait=True)
    plan = plan_export((window.generate(), window._snapshot)[1])
    out = write_export(plan, tmp_path / "e")
    readme = (out / README_FILE).read_text()
    for f in plan.files:
        assert f.name in readme
    assert "O QUE NÃO FOI EXPORTADO" in readme and "layout" in readme and "legenda" in readme
