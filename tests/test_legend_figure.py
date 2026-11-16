"""Legenda desenhada na figura: conteúdo, posição fora do desenho, export e presets."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.annotations import LeafColumn, LegendGroup  # noqa: E402
from jabuti.models.clades import Clade  # noqa: E402
from jabuti.parsers.newick import parse_newick_string  # noqa: E402
from jabuti.presets import preset_from_dict, preset_to_dict  # noqa: E402
from jabuti.style import LEGEND_POSITIONS, LayoutKind, LegendStyle, RenderStyle  # noqa: E402

BIN = "((((A:1,B:1)95/99:1,C:2)60/80:1,(D:1,E:1)99/100:3)90/97:1,(F:1,(G:1,H:1)40/50:1)85/96:2);"
CLADES = [Clade("abc", frozenset("ABC"), color="#4e79a7"), Clade("fgh", frozenset("FGH"), color="#e15759")]
GROUPS = [LegendGroup("Grupos de rótulos", [("Destaque", "#b7e4a3")]),
          LegendGroup("Habitat", [("solo", "#59a14f"), ("rizosfera", "#edc948")])]


@pytest.fixture
def render(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    def _render(layout=LayoutKind.RECTANGULAR, position="top-right", in_figure=True, columns=None, mode="background"):
        scene = QGraphicsScene()
        style = RenderStyle(layout=layout, legend=LegendStyle(in_figure, position))
        style.clades.label_mode = mode
        res = TreeRenderer(scene).render(parse_newick_string(BIN), style, CLADES, None, columns, legend=GROUPS)
        return scene, res

    return _render


def legend_items(scene):
    return [i for i in scene.items() if i.data(1) == "legend"]


def texts(items):
    return {i.text() for i in items if hasattr(i, "text")}


def bbox(items):
    from PySide6.QtCore import QRectF

    r = QRectF()
    for i in items:
        r = r.united(i.sceneBoundingRect())
    return r


def test_off_by_default(render):
    scene, _ = render(in_figure=False)
    assert legend_items(scene) == []
    assert RenderStyle().legend.in_figure is False


def test_content_matches_panel_legend(render):
    scene, _ = render()
    t = texts(legend_items(scene))
    assert {"Clados", "abc", "fgh", "Grupos de rótulos", "Destaque", "Habitat", "solo", "rizosfera"} <= t
    squares = [i for i in legend_items(scene) if not hasattr(i, "text")]
    colors = {s.brush().color().name() for s in squares}
    # marca-texto (padrão): a amostra do clado é a cor vista atrás dos nomes (35% sobre o branco)
    from jabuti.models.color_rules import blend

    assert {blend("#4e79a7", 0.35), blend("#e15759", 0.35), "#b7e4a3", "#59a14f", "#edc948"} == colors
    scene, _ = render(mode="text")                       # cor nas letras: a cor cheia, como antes
    squares = [i for i in legend_items(scene) if not hasattr(i, "text")]
    assert {"#4e79a7", "#e15759"} <= {s.brush().color().name() for s in squares}


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
@pytest.mark.parametrize("position", list(LEGEND_POSITIONS))
def test_legend_outside_drawing(render, layout, position):
    col = LeafColumn("gene:x", "geneX", {n: "#2b6cb0" for n in "ABCDEFGH"})
    scene, _ = render(layout, position, columns=[col])
    leg = legend_items(scene)
    others = [i for i in scene.items() if i.data(1) != "legend"]
    lb, ob = bbox(leg), bbox(others)
    assert not lb.intersects(ob)                       # não cobre árvore, heatmap nem escala
    assert any(i.data(1) == "scale-bar" for i in others) and any(i.data(1) == "heatmap" for i in others)
    if position.endswith("right"):
        assert lb.left() > ob.right()
    else:
        assert lb.right() < ob.left()
    if position.startswith("top"):
        assert lb.top() == pytest.approx(ob.top(), abs=0.5)
    else:
        assert lb.bottom() == pytest.approx(ob.bottom(), abs=0.5)
    assert scene.sceneRect().contains(lb)


@pytest.mark.parametrize("fmt", ["svg", "pdf", "png"])
def test_export_includes_legend(render, tmp_path, fmt):
    from jabuti.views import export

    scene, _ = render()
    out = getattr(export, f"export_{fmt}")(scene, tmp_path / f"t.{fmt}")
    assert out.stat().st_size > 0
    if fmt == "svg":
        text = out.read_text(encoding="utf-8")
        assert "rizosfera" in text and "#edc948" in text.lower()


def test_legend_style_in_preset():
    st = RenderStyle(legend=LegendStyle(True, "bottom-left"))
    loaded = preset_from_dict(preset_to_dict(st))
    assert loaded.style.legend == LegendStyle(True, "bottom-left") and loaded.warnings == []
    data = preset_to_dict(st)
    data["style"]["legend"]["position"] = "centro"
    loaded = preset_from_dict(data)
    assert loaded.style.legend.position == "top-right" and len(loaded.warnings) == 1


def test_gui_toggle_and_label_groups(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    win = MainWindow()
    qtbot.addWidget(win)
    win.tree_tab.load("examples/paraburkholderia_40.treefile")
    sp = win.style_panel
    sp.label_panel.create_group(win.tree.leaf_names()[:3], "selection", name="Meu destaque")
    win.render_live()
    assert legend_items(win.canvas.tree_scene) == []
    sp.legend_in_figure.setChecked(True)
    sp.legend_pos.setCurrentIndex(sp.legend_pos.findData("bottom-left"))
    win.render_live()
    items = legend_items(win.canvas.tree_scene)
    assert "Meu destaque" in texts(items)
    others = [i for i in win.canvas.tree_scene.items() if i.data(1) != "legend" and i.data(0) != "selection"]
    assert bbox(items).right() < bbox(others).left()
    assert win.collect_preset()["style"]["legend"] == {"in_figure": True, "position": "bottom-left"}
