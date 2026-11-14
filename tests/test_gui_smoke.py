"""Smoke test da GUI (roda com QT_QPA_PLATFORM=offscreen no CI)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("pytestqt")

from jabuti.style import LayoutKind  # noqa: E402


@pytest.fixture
def window(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    shown: list[str] = []
    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    win = MainWindow()
    win.shown_errors = shown
    qtbot.addWidget(win)
    return win


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_load_generate_export(window, data_dir, tmp_path, layout):
    from jabuti.views.export import export_pdf, export_png, export_svg

    assert window.tree_tab.load(data_dir / "iqtree_ufboot.treefile")
    window.viz_tab.layout_cb.setCurrentIndex(window.viz_tab.layout_cb.findData(layout))
    sp = window.style_panel
    sp.support_mode.setCurrentIndex(sp.support_mode.findData("numbers"))
    window.generate()
    assert window.canvas.result is not None
    assert len(window.canvas.result.leaf_items) == 6

    assert window.canvas.search("tropica") == ["Paraburkholderia tropica Ppe8"]

    svg = export_svg(window.canvas.tree_scene, tmp_path / "t.svg")
    text = svg.read_text()
    assert "<svg" in text and "Paraburkholderia" in text
    assert "ffe066" not in text.lower()  # destaque da busca não é exportado
    assert export_pdf(window.canvas.tree_scene, tmp_path / "t.pdf").read_bytes()[:4] == b"%PDF"
    png = export_png(window.canvas.tree_scene, tmp_path / "t.png", dpi=150)
    assert png.read_bytes()[:4] == b"\x89PNG"
    assert window.shown_errors == []


def test_bad_file_shows_error_without_crashing(window, data_dir):
    assert not window.tree_tab.load(data_dir / "malformed_parens.nwk")
    assert window.shown_errors and "Parênteses" in window.shown_errors[0]
    assert window.tree is None


def test_rooting_via_gui(window, data_dir):
    window.tree_tab.load(data_dir / "small.nwk")
    window.tree_tab.rb_out.setChecked(True)
    window.tree_tab.outgroup.setCurrentText("E")
    window.tree_tab.apply_rooting()
    assert window.tree.find_leaf("E").parent is window.tree.root
    window.tree_tab.rb_mid.setChecked(True)
    window.tree_tab.apply_rooting()
    assert window.shown_errors == []


def test_style_panel_is_fixed_dock(window):
    from PySide6.QtWidgets import QDockWidget

    dock = window.style_dock
    assert dock.features() == QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
    assert not dock.isFloating()
    assert window.style_panel.legend.entries == []
    assert not window.style_panel.color_by.isEnabled()  # sem metadados ainda
    assert set(window.style_panel.sections) >= {"clades", "branches", "guides", "labels", "meta"}


def test_color_change_updates_canvas_immediately(window, data_dir):
    from PySide6.QtWidgets import QGraphicsPathItem

    window.tree_tab.load(data_dir / "small.nwk")
    sp = window.style_panel
    sp.branch_row.buttons["#b22222"].click()
    sp.label_row.buttons["#1f4e79"].click()
    window.render_live()  # o timer de debounce dispararia isto
    paths = [i for i in window.canvas.tree_scene.items() if isinstance(i, QGraphicsPathItem)]
    assert any(p.pen().color().name() == "#b22222" for p in paths)
    label = window.canvas.result.leaf_items["A"][0]
    assert label.brush().color().name() == "#1f4e79"
    sp.palette_buttons["Set2"].click()
    assert window.current_style().clades.palette == "Set2"


def test_reroot_in_gui_keeps_circular_alignment(window, data_dir):
    import math

    window.tree_tab.load(data_dir / "iqtree_ufboot.treefile")
    vt = window.viz_tab
    vt.layout_cb.setCurrentIndex(vt.layout_cb.findData(LayoutKind.CIRCULAR))
    assert vt.align_tips.isEnabled() and vt.align_tips.isChecked()
    for mode in ("mid", "out"):
        if mode == "mid":
            window.tree_tab.rb_mid.setChecked(True)
        else:
            window.tree_tab.rb_out.setChecked(True)
            window.tree_tab.outgroup.setCurrentText("Burkholderia_cepacia_ATCC25416")
        window.tree_tab.apply_rooting()
        pts = window.canvas.result.leaf_points.values()
        d = [math.hypot(p.x(), p.y()) for p in pts]
        assert max(d) - min(d) < 1e-6
        assert d[0] == pytest.approx(window.renderer.geometry.tip_ring)
    vt.layout_cb.setCurrentIndex(vt.layout_cb.findData(LayoutKind.RECTANGULAR))
    assert not vt.align_tips.isEnabled()
    assert window.shown_errors == []
