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
    window.viz_tab.show_support.setChecked(True)
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
