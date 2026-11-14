"""Presets pela GUI: salvar/carregar, meu padrão, restaurar padrão."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti.style import LayoutKind  # noqa: E402

EX = "examples/paraburkholderia_40.treefile"


@pytest.fixture
def make_window(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    shown: list[str] = []
    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)

    def _make(load=True):
        win = MainWindow()
        win.shown = shown
        qtbot.addWidget(win)
        if load:
            win.tree_tab.load(EX)
        return win

    return _make


def customize(win):
    sp, vt = win.style_panel, win.viz_tab
    vt.layout_cb.setCurrentIndex(vt.layout_cb.findData(LayoutKind.CIRCULAR))
    vt.spacing.setValue(2.2)
    sp.mode.setCurrentIndex(sp.mode.findData("k"))
    sp.k_spin.setValue(4)
    sp.detect()
    sp.palette_buttons["Paired"].click()
    sp.opt_background.setChecked(True)
    sp.opt_strip.setChecked(True)
    sp.strip_width.setValue(18)
    sp.guide_kind.setCurrentIndex(sp.guide_kind.findData("dash"))
    sp.guide_opacity.setValue(55)
    sp.branch_cap.setCurrentIndex(sp.branch_cap.findData("round"))
    sp.font_bold.setChecked(True)
    sp.font_italic.setChecked(False)
    sp.tip_shape.setCurrentIndex(sp.tip_shape.findData("square"))
    sp.support_mode.setCurrentIndex(sp.support_mode.findData("symbols"))
    sp.scale_pos.setCurrentIndex(sp.scale_pos.findData("top-left"))
    sp.ladder.setCurrentIndex(sp.ladder.findData("desc"))
    sp.bg_row.buttons["#fbf7ee"].click()
    burk = frozenset({"Burkholderia_cepacia_ATCC25416", "Burkholderia_cenocepacia_J2315"})
    sp.add_manual_clade(burk, "Burkholderia")
    sp.clade_set.clades[0].color = "#abcdef"   # cor individual fora das amostras
    win.render_live()


def scene_signature(win):
    items = win.canvas.tree_scene.items()
    tags = sorted(str(i.data(1)) for i in items)
    return len(items), tags, win.style_panel.legend.entries


def test_round_trip_restores_controls_and_drawing(make_window):
    win = make_window()
    customize(win)
    saved = win.collect_preset()
    before = scene_signature(win)

    win.on_preset_action("restore")
    win.style_panel.clear_auto()
    win.style_panel.load_tree_state(None, None)
    win.render_live()
    assert scene_signature(win) != before

    from jabuti.presets import preset_from_dict

    warnings = win.apply_preset(preset_from_dict(saved))
    assert warnings == []
    assert win.collect_preset() == saved
    assert scene_signature(win) == before


def test_save_and_load_via_dialogs(make_window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    win = make_window()
    customize(win)
    target = tmp_path / "meu.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    win.on_preset_action("save")
    assert target.exists()

    other = make_window()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))
    other.on_preset_action("load")
    assert other.collect_preset() == win.collect_preset()
    assert other.shown == []


def test_user_default_loaded_on_start(make_window, isolated_config):
    win = make_window()
    customize(win)
    win.on_preset_action("save_default")
    assert (isolated_config / "default_preset.json").exists()

    fresh = make_window(load=False)
    st = fresh.current_style()
    assert st.layout == LayoutKind.CIRCULAR and st.clades.palette == "Paired"
    assert st.label.bold and st.symbols.shape == "square"
    assert fresh.style_panel.clade_set.clades == []      # padrão pessoal não traz clados
    assert fresh.style_panel.edits.ladderize == "none"   # nem edições
    assert fresh.style_panel.forget_default_btn.isEnabled()

    fresh.on_preset_action("forget_default")
    assert not (isolated_config / "default_preset.json").exists()


def test_restore_default_keeps_clades(make_window):
    win = make_window()
    customize(win)
    n = len(win.style_panel.clade_set.clades)
    win.on_preset_action("restore")
    st = win.current_style()
    assert st.layout == LayoutKind.RECTANGULAR and st.clades.palette == "Tableau 10"
    assert st.label.italic and not st.label.bold and st.background == "#ffffff"
    assert len(win.style_panel.clade_set.clades) == n
    assert win.style_panel.edits.ladderize == "desc"


def test_preset_from_other_tree_marks_missing(make_window, tmp_path):
    from jabuti.models.clades import Clade, CladeSet
    from jabuti.presets import preset_to_dict, save_preset
    from jabuti.style import RenderStyle

    p = save_preset(tmp_path / "x.json",
                    preset_to_dict(RenderStyle(), CladeSet([Clade("fantasma", frozenset({"nao", "existe"}))])))
    win = make_window()
    from jabuti.presets import load_preset

    win.apply_preset(load_preset(p))
    (rc,) = win.canvas.result.clades
    assert not rc.valid and "ausente" in rc.problem


def test_bad_preset_file_shows_error(make_window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    bad = tmp_path / "bad.json"
    bad.write_text("{ nada")
    win = make_window()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(bad), ""))
    win.on_preset_action("load")
    assert win.shown and "JSON inválido" in win.shown[-1]


def test_custom_color_gets_swatch(qtbot):
    from jabuti.views.widgets.swatches import SwatchRow

    row = SwatchRow()
    qtbot.addWidget(row)
    row.set_color("#ABCDEF")
    assert row.color() == "#abcdef" and "#abcdef" in row.buttons
