"""Export SVG/PDF/PNG com diferentes estilos de linha (ligações e ramos)."""

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.parsers.newick import load_tree  # noqa: E402
from jabuti.style import GUIDE_KINDS, BranchStyle, GuideStyle, LayoutKind, RenderStyle  # noqa: E402

GUIDE_HEX = "#3366cc"


@pytest.fixture
def scene_for(qtbot, data_dir):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    holder = []

    def _make(style: RenderStyle, tree="iqtree_ufboot.treefile"):
        scene = QGraphicsScene()
        holder.append(scene)
        TreeRenderer(scene).render(load_tree(data_dir / tree), style)
        return scene

    return _make


def guide_groups(svg_text: str) -> list[str]:
    return [g for g in re.findall(r"<g [^>]*>", svg_text) if GUIDE_HEX in g]


def svg_for(scene_for, tmp_path, **guide):
    from jabuti.views.export import export_svg

    style = RenderStyle(layout=LayoutKind.CIRCULAR, guide=GuideStyle(color=GUIDE_HEX, **guide))
    name = "_".join(f"{k}{v}" for k, v in guide.items())
    return export_svg(scene_for(style), tmp_path / f"{name}.svg").read_text(encoding="utf-8")


def dasharray(group: str) -> str | None:
    m = re.search(r'stroke-dasharray="([^"]+)"', group)
    return m.group(1) if m else None


def test_each_guide_kind_exports_distinctly(scene_for, tmp_path):
    seen = {}
    for kind in GUIDE_KINDS:
        groups = guide_groups(svg_for(scene_for, tmp_path, kind=kind))
        if kind == "none":
            assert groups == []
            continue
        assert len(groups) == 1, kind
        seen[kind] = (dasharray(groups[0]), re.search(r'stroke-linecap="(\w+)"', groups[0]).group(1))
    assert seen["solid"][0] is None
    assert all(seen[k][0] for k in ("dash", "dots", "bigdots"))
    assert len({v for v in seen.values()}) == 4  # todos diferentes entre si
    assert seen["bigdots"][1] == "round"


def test_guide_opacity_width_and_color(scene_for, tmp_path):
    (g,) = guide_groups(svg_for(scene_for, tmp_path, kind="solid", opacity=0.4, width=1.7))
    assert float(re.search(r'stroke-opacity="([\d.]+)"', g).group(1)) == pytest.approx(0.4, abs=0.01)
    assert 'stroke-width="1.7"' in g


@pytest.mark.parametrize("kind", list(GUIDE_KINDS))
@pytest.mark.parametrize("fmt", ["pdf", "png"])
def test_pdf_png_for_each_guide_kind(scene_for, tmp_path, kind, fmt):
    from jabuti.views import export

    style = RenderStyle(layout=LayoutKind.CIRCULAR, guide=GuideStyle(kind=kind))
    out = getattr(export, f"export_{fmt}")(scene_for(style), tmp_path / f"{kind}.{fmt}")
    head = out.read_bytes()[:4]
    assert head == (b"%PDF" if fmt == "pdf" else b"\x89PNG")


def test_branch_cap_round_in_svg(scene_for, tmp_path):
    from jabuti.views.export import export_svg

    style = RenderStyle(branch=BranchStyle(cap="round", color="#aa1100", width=2.5))
    txt = export_svg(scene_for(style), tmp_path / "cap.svg").read_text(encoding="utf-8")
    groups = [g for g in re.findall(r"<g [^>]*>", txt) if "#aa1100" in g and "stroke-width" in g]
    assert any('stroke-linecap="round"' in g and 'stroke-width="2.5"' in g for g in groups)


def test_width_proportional_to_support(scene_for):
    style = RenderStyle(branch=BranchStyle(width_by_support=True, min_width=0.5, max_width=4.0))
    scene = scene_for(style)
    widths = sorted({i.pen().widthF() for i in scene.items() if i.data(1) == "branches"})
    assert widths[0] == pytest.approx(0.5)   # folhas / sem suporte
    assert widths[-1] == pytest.approx(4.0)  # suporte máximo (100)
    assert len(widths) >= 3


def test_width_by_support_without_supports_is_uniform(scene_for):
    style = RenderStyle(branch=BranchStyle(width_by_support=True, width=1.3))
    scene = scene_for(style, "small.nwk")
    assert {i.pen().widthF() for i in scene.items() if i.data(1) == "branches"} == {1.3}


def test_panel_controls_reach_style(qtbot):
    from jabuti.views.style_panel import StylePanel

    sp = StylePanel()
    qtbot.addWidget(sp)
    sp.guide_kind.setCurrentIndex(sp.guide_kind.findData("bigdots"))
    sp.guide_opacity.setValue(40)
    sp.branch_cap.setCurrentIndex(sp.branch_cap.findData("round"))
    sp.width_by_support.setChecked(True)
    with qtbot.waitSignal(sp.changed, timeout=500):
        sp.branch_width.setValue(2.0)
    style = sp.apply_to(RenderStyle())
    assert style.guide.kind == "bigdots" and style.guide.opacity == pytest.approx(0.4)
    assert style.branch.cap == "round" and style.branch.width_by_support and style.branch.width == 2.0
