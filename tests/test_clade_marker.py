"""Clados com fundo nos nomes (marca-texto): blocos mesclados, contraste, modo texto, migração."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from jabuti.models.clades import Clade, clades_by_k  # noqa: E402
from jabuti.models.color_rules import blend, contrast_ratio, readable_text  # noqa: E402
from jabuti.parsers.newick import load_tree, parse_newick_string  # noqa: E402
from jabuti.presets import preset_from_dict, preset_to_dict, style_from_dict, style_to_dict  # noqa: E402
from jabuti.style import LayoutKind, RenderStyle  # noqa: E402

TREE = "examples/paraburkholderia_40.treefile"
BIN = "((((A:1,B:1):1,C:2):1,(D:1,E:1):3):1,(F:1,(G:1,H:1):1):2);"
ALL_LAYOUTS = list(LayoutKind)


# ------------------------------------------------------------------ contraste
def test_contrast_helpers():
    assert blend("#000000", 0.5) == "#808080" and blend("#4e79a7", 1.0) == "#4e79a7"
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert readable_text("#ffe066") == "#202020"                    # amarelo claro: texto escuro
    assert readable_text("#1f3a93") == "#ffffff"                    # azul escuro: texto branco
    assert readable_text("#1f3a93", 0.35) == "#202020"              # o mesmo azul a 35%: claro
    assert readable_text("#1f3a93", 0.35, under="#000000") == "#ffffff"   # sobre fundo preto


# ------------------------------------------------------------------ desenho
@pytest.fixture
def render(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    def _render(tree, clades, layout=LayoutKind.RECTANGULAR, **cs):  # type: ignore[no-untyped-def]
        scene = QGraphicsScene()
        style = RenderStyle(layout=layout)
        for k, v in cs.items():
            setattr(style.clades, k, v)
        res = TreeRenderer(scene).render(tree, style, clades)
        return scene, res, style

    return _render


def _k_clades(tree, k=4):  # type: ignore[no-untyped-def]
    return [Clade(f"C{i}", s, None, True, "auto") for i, s in enumerate(clades_by_k(tree, k))]


def test_default_is_marker_with_one_block_per_clade(render):
    tree = load_tree(TREE)
    clades = _k_clades(tree)
    assert RenderStyle().clades.label_mode == "background"
    scene, res, _st = render(tree, clades)
    for rc in res.clades:
        names = [l.name for l in rc.node.leaves()]
        blocks = {id(res.label_backgrounds[n]) for n in names}
        assert len(blocks) == 1, rc.clade.name                     # bloco contínuo por clado
        bg = res.label_backgrounds[names[0]].brush().color()
        assert bg.name() == rc.color and bg.alphaF() == pytest.approx(0.35, abs=0.01)
        for n in names:                                             # texto escuro (padrão)
            assert res.leaf_items[n][0].brush().color().name() == "#202020"
    assert len({id(b) for b in res.label_backgrounds.values()}) == len(res.clades)


def test_neighbouring_blocks_have_no_white_gap(render):
    tree = load_tree(TREE)
    _scene, res, _st = render(tree, _k_clades(tree))
    rects = sorted({id(b): b.sceneBoundingRect() for b in res.label_backgrounds.values()}.values(),
                   key=lambda r: r.top())
    touching = 0
    for a, b in zip(rects, rects[1:]):
        if b.top() - a.bottom() < 6:                               # vizinhos na ordem das folhas
            assert b.top() <= a.bottom() + 1e-6                    # encostam (ou se sobrepõem)
            touching += 1
    assert touching >= 2


def test_same_colour_neighbours_merge_into_one_block(render):
    tree = parse_newick_string(BIN)
    clades = [Clade("ab", frozenset("ABC"), "#59a14f"), Clade("de", frozenset("DE"), "#59a14f"),
              Clade("fgh", frozenset("FGH"), "#e15759")]
    _scene, res, _st = render(tree, clades)
    assert res.label_backgrounds["A"] is res.label_backgrounds["E"]          # mesma cor, encostados
    assert res.label_backgrounds["A"] is not res.label_backgrounds["F"]


def test_dark_background_gets_white_text(render):
    tree = parse_newick_string(BIN)
    clades = [Clade("abc", frozenset("ABC"), "#1f3a93"), Clade("fgh", frozenset("FGH"), "#ffe066")]
    _scene, res, _st = render(tree, clades, label_background_alpha=1.0)
    assert res.leaf_items["A"][0].brush().color().name() == "#ffffff"
    assert res.leaf_items["F"][0].brush().color().name() == "#202020"


@pytest.mark.parametrize("layout", ALL_LAYOUTS)
def test_marker_in_every_layout(render, layout):
    tree = load_tree(TREE)
    clades = _k_clades(tree)
    _scene, res, _st = render(tree, clades, layout)
    covered = {n for rc in res.clades for n in (l.name for l in rc.node.leaves())}
    assert covered and covered <= set(res.label_backgrounds)
    assert all(res.leaf_items[n][0].brush().color().name() in ("#202020", "#ffffff") for n in covered)


def test_text_mode_keeps_old_behaviour(render):
    tree = load_tree(TREE)
    clades = _k_clades(tree)
    _scene, res, _st = render(tree, clades, label_mode="text")
    assert not res.label_backgrounds
    for rc in res.clades:
        for leaf in rc.node.leaves():
            assert res.leaf_items[leaf.name][0].brush().color().name() == rc.color


def test_svg_export_has_the_marker(render, tmp_path):
    from jabuti.views.export import export_svg

    tree = parse_newick_string(BIN)
    scene, _res, _st = render(tree, [Clade("abc", frozenset("ABC"), "#4e79a7")])
    text = export_svg(scene, tmp_path / "f.svg").read_text(encoding="utf-8").lower()
    assert 'fill="#4e79a7"' in text and "fill-opacity" in text


# ------------------------------------------------------------------ migração e persistência
@pytest.mark.parametrize("old,mode", [
    ({"color_labels": True, "label_background": False}, "text"),
    ({"color_labels": False, "label_background": True}, "background"),
    ({"color_labels": True, "label_background": True}, "background"),
    ({"color_labels": False, "label_background": False}, "none"),
    ({"color_labels": False}, "none"),
    ({}, "background"),
])
def test_old_presets_keep_their_look(old, mode):
    assert style_from_dict({"clades": {"palette": "Set2", **old}}).clades.label_mode == mode


def test_invalid_mode_warns_and_falls_back():
    warnings: list[str] = []
    assert style_from_dict({"clades": {"label_mode": "neon"}}, warnings).clades.label_mode == "background"
    assert any("label_mode" in w for w in warnings)


def test_preset_round_trip_and_panel(qtbot):
    from jabuti.views.style_panel import StylePanel

    st = RenderStyle()
    st.clades.label_mode = "text"
    assert style_from_dict(style_to_dict(st)).clades.label_mode == "text"
    assert "color_labels" not in style_to_dict(st)["clades"]
    panel = StylePanel()
    qtbot.addWidget(panel)
    assert panel.label_mode() == "background"                    # padrão do painel
    panel.load_style(preset_from_dict(preset_to_dict(st)).style)
    assert panel.label_mode_text.isChecked() and panel.apply_to(RenderStyle()).clades.label_mode == "text"
    panel.set_label_mode("none")
    assert not panel.label_mode_bg.isChecked() and not panel.label_mode_text.isChecked()
    panel.label_mode_bg.setChecked(True)
    assert panel.apply_to(RenderStyle()).clades.label_mode == "background"


def test_old_project_v1_migrates_and_new_project_round_trips(qtbot, tmp_path, monkeypatch):
    import shutil

    from jabuti.project import PROJECT_VERSION, read_project
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    shutil.copy(TREE, tmp_path / "t.treefile")
    old = {"format": "jabuti-project", "version": 1, "tree": {"file": {"rel": "t.treefile"}, "rooting": {"mode": "file"}},
           "view": {"app": "jabuti", "version": 1,
                    "style": {"clades": {"color_labels": True, "label_background": False}}}}
    p = tmp_path / "velho.jabuti"
    p.write_text(json.dumps(old), encoding="utf-8")
    data, notes = read_project(p)
    assert data["version"] == PROJECT_VERSION == 2 and data["view"]["style"]["clades"]["label_mode"] == "text"
    assert any("formato 1" in n for n in notes)
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.open_project(p, wait=True)
    assert w.style_panel.label_mode() == "text" and w.current_style().clades.label_mode == "text"
    w.style_panel.label_mode_bg.setChecked(True)
    w.render_live()
    out = w.project._write(tmp_path / "novo.jabuti")
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["version"] == 2 and saved["view"]["style"]["clades"]["label_mode"] == "background"
    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.open_project(out, wait=True) and w2.style_panel.label_mode() == "background"


def test_itol_export_uses_label_background(qtbot, monkeypatch):
    from jabuti.exporters.itol_export import plan_export
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    w = MainWindow()
    qtbot.addWidget(w)
    w.open_tree(TREE)
    w.style_panel.detect()
    w.generate()
    colors = next(f for f in plan_export(w._snapshot).files if f.kind == "TREE_COLORS").text
    assert "\tlabel_background\t" in colors
    w.style_panel.label_mode_text.setChecked(True)
    w.generate()
    colors = next(f for f in plan_export(w._snapshot).files if f.kind == "TREE_COLORS").text
    assert "\tlabel_background\t" not in colors
