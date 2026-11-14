"""Etapa 4: suporte em níveis, TIFF (LZW, DPI) e resumo da árvore."""

import os
import struct

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.models.support import band_counts, level_labels, level_of, tree_summary, value_name  # noqa: E402
from jabuti.parsers.newick import parse_newick_string  # noqa: E402
from jabuti.style import LayoutKind, RenderStyle  # noqa: E402

T = "((A:1,B:1)99/100:1,((C:1,D:1)50/80:1,(E:1,F:1)90/60:1)85/96:1);"


def test_level_labels_and_bins():
    assert level_labels([95, 70]) == ["≥95", "70–94", "<70"]
    assert level_labels([70, 95]) == ["≥95", "70–94", "<70"]          # ordem não importa
    assert level_labels([0.9]) == ["≥0.9", "<0.9"]
    assert [level_of(v, [95, 70]) for v in (100, 95, 94.9, 70, 69)] == [0, 0, 1, 1, 2]
    assert band_counts([100, 80, 50, 96], [95, 70]) == [2, 1, 1]


def test_value_names():
    assert value_name(0, 2) == "SH-aLRT" and value_name(1, 2) == "UFBoot" and value_name(-1, 2) == "UFBoot"
    assert value_name(-1, 1) == "bootstrap/UFBoot"


def test_tree_summary_two_values():
    text = tree_summary(parse_newick_string(T), hidden=2)
    assert "Folhas: 6 (+2 oculta(s)" in text
    assert "UFBoot (4 nós): ≥95: 2 · 70–94: 1 · <70: 1" in text
    assert "SH-aLRT (4 nós): ≥80: 3 · <80: 1" in text
    assert "SH-aLRT ≥80 e UFBoot ≥95: 2 nós" in text


def test_tree_summary_single_and_none():
    one = tree_summary(parse_newick_string("((A,B)99,(C,D)40);"))
    assert "bootstrap/UFBoot" in one and "≥95: 1" in one and "<70: 1" in one
    assert "Sem valores de suporte" in tree_summary(parse_newick_string("((A,B),(C,D));"))


@pytest.mark.parametrize("layout", [LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR])
def test_level_circles_colored_by_band(qapp, layout):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    st = RenderStyle(layout=layout)
    st.figure.support_levels.enabled = True
    st.figure.support_levels.index = 1
    scene = QGraphicsScene()
    TreeRenderer(scene).render(parse_newick_string(T), st)
    items = {i.data(2): i for i in scene.items() if i.data(1) == "support-level"}
    counts = {k: len(i.path().toSubpathPolygons()) for k, i in items.items()}
    assert counts == {0: 2, 1: 1, 2: 1}                    # UFBoot 100, 96 | 80 | 60
    assert items[0].brush().color().name() == "#2f9e44"
    st.figure.support_levels.index = 0                     # SH-aLRT: 99, 85, 90 ≥ 70… 50 < 70
    scene = QGraphicsScene()
    TreeRenderer(scene).render(parse_newick_string(T), st)
    counts = {i.data(2): len(i.path().toSubpathPolygons()) for i in scene.items() if i.data(1) == "support-level"}
    assert counts == {0: 1, 1: 2, 2: 1}


def test_levels_off_draws_nothing(qapp):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    scene = QGraphicsScene()
    TreeRenderer(scene).render(parse_newick_string(T), RenderStyle())
    assert not [i for i in scene.items() if i.data(1) == "support-level"]


# ------------------------------------------------------------------ TIFF
def tiff_tags(path):
    b = path.read_bytes()
    e = "<" if b[:2] == b"II" else ">"
    off = struct.unpack(e + "I", b[4:8])[0]
    n = struct.unpack(e + "H", b[off:off + 2])[0]
    tags = {}
    for i in range(n):
        t, typ, cnt, val = struct.unpack(e + "HHII", b[off + 2 + 12 * i:off + 14 + 12 * i])
        if typ == 3 and cnt == 1:                          # SHORT ocupa os 2 primeiros bytes do campo
            val = (val & 0xFFFF) if e == "<" else (val >> 16)
        if typ == 5:                                       # RATIONAL: ponteiro para num/den
            num, den = struct.unpack(e + "II", b[val:val + 8])
            val = num / den
        tags[t] = val
    return tags


@pytest.fixture
def scene(qapp):
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.views.tree_renderer import TreeRenderer

    sc = QGraphicsScene()
    TreeRenderer(sc).render(parse_newick_string(T), RenderStyle())
    return sc


def test_tiff_600dpi_lzw(scene, tmp_path):
    from jabuti.views.export import export_tiff

    p = export_tiff(scene, tmp_path / "f.tif")
    tags = tiff_tags(p)
    assert tags[259] == 5                                  # Compression = LZW
    assert tags[282] == pytest.approx(600, abs=0.5) and tags[296] == 2   # 600 por polegada
    w = scene.sceneRect().width()
    assert tags[256] == int(w * 600 / 72)


def test_tiff_without_compression_and_custom_dpi(scene, tmp_path):
    from jabuti.views.export import export_tiff

    tags = tiff_tags(export_tiff(scene, tmp_path / "g.tiff", dpi=300, lzw=False))
    assert tags[259] == 1 and tags[282] == pytest.approx(300, abs=0.5)


def test_tiff_size_limit_message(scene, tmp_path):
    from jabuti.views.export import ExportError, export_tiff

    with pytest.raises(ExportError, match="Reduza o DPI"):
        export_tiff(scene, tmp_path / "x.tif", dpi=20000)


def test_preset_roundtrip_levels():
    from jabuti.presets import preset_from_dict, preset_to_dict
    from jabuti.style import SupportLevels

    st = RenderStyle()
    st.figure.support_levels = SupportLevels(True, 0, [90.0, 50.0], ["#000000", "#111111", "#222222"], 9.0, False)
    loaded = preset_from_dict(preset_to_dict(st))
    assert loaded.warnings == [] and loaded.style.figure.support_levels == st.figure.support_levels


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


def test_gui_levels_legend_and_summary_copy(window):
    from PySide6.QtWidgets import QApplication

    fp = window.figure_panel
    fp.lv_enabled.setChecked(True)
    fp.lv_cutoffs.setText("90; 80; 70")
    fp.lv_cutoffs.editingFinished.emit()
    assert fp.lv_colors_layout.count() == 5               # 4 cores + espaço
    window.render_live()
    (legend,) = [g for g in window.style_panel.legend.groups if g.title.startswith("Suporte")]
    assert legend.title == "Suporte (UFBoot)" and [t for t, _c in legend.entries] == ["≥90", "80–89", "70–79", "<70"]
    assert "UFBoot (36 nós)" in fp.summary_text.toPlainText()
    fp.copy_summary()
    assert QApplication.clipboard().text().startswith("Folhas: 40")
    window.canvas.set_selection(["Burkholderia_cepacia_ATCC25416"])
    fp.hide_selected()
    window.render_live()
    assert fp.summary_text.toPlainText().startswith("Folhas: 39 (+1 oculta")


def test_gui_export_tiff(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    target = tmp_path / "arvore"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    window.viz_tab.tiff_dpi.setValue(150)
    window.export("tiff")
    out = tmp_path / "arvore.tiff"
    assert out.exists() and tiff_tags(out)[282] == pytest.approx(150, abs=0.5)
