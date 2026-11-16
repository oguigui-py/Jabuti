"""Exportação em lote: nomes, 2 layouts × 2 formatos, cancelar, erro num item, pulados e estado intacto."""

from __future__ import annotations

import copy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from jabuti.exporters.batch import (  # noqa: E402
    DEFAULT_TEMPLATE,
    TemplateError,
    check_template,
    file_name,
    plan_batch,
    visual_style,
)
from jabuti.style import LayoutKind, RenderStyle  # noqa: E402
from scene_baseline import same, signature  # noqa: E402

TREE = "examples/paraburkholderia_40.treefile"
R, C, U = LayoutKind.RECTANGULAR, LayoutKind.CIRCULAR, LayoutKind.UNROOTED


# ------------------------------------------------------------------ modelo
def test_template_checks_and_names():
    check_template(DEFAULT_TEMPLATE)
    for bad, needle in (("", "vazio"), ("{nome}.{ext}", "desconhecido"), ("a/{layout}", "/"), ("{layout", "inválido")):
        with pytest.raises(TemplateError, match=needle):
            check_template(bad)
    assert file_name(DEFAULT_TEMPLATE, "meu projeto", C, "atual", "tiff") == "meu projeto_circular_atual.tif"
    assert file_name("{layout}", "p", U, "x", "png") == "nao_enraizada.png"          # extensão garantida
    assert file_name("{projeto}.{ext}", 'a/b:c*', R, "x", "svg") == "a_b_c_.svg"


def test_plan_order_and_unique_names(tmp_path):
    plan = plan_batch("p", [R, C], ["atual", "escuro"], ["svg", "png"], DEFAULT_TEMPLATE, tmp_path)
    assert len(plan.items) == 8 and plan.items[0].path.name == "p_retangular_atual.svg"
    plan = plan_batch("p", [R, C], ["atual"], ["svg"], "figura.{ext}", tmp_path)       # sem campo variável
    assert [i.path.name for i in plan.items] == ["figura.svg", "figura_2.svg"]
    with pytest.raises(TemplateError, match="layout"):
        plan_batch("p", [], ["atual"], ["svg"], DEFAULT_TEMPLATE, tmp_path)


def test_visual_style_keeps_project_data():
    cur = RenderStyle()
    cur.metadata.color_by = "habitat"
    cur.metadata.strips = ["symbiont"]
    cur.figure.track_order = ["meta:symbiont"]
    preset = RenderStyle()
    preset.branch.color = "#aa0000"
    preset.figure.track_order = []
    preset.metadata.color_by = None
    out = visual_style(cur, preset, C)
    assert out.branch.color == "#aa0000" and out.layout == C
    assert out.metadata.color_by == "habitat" and out.metadata.strips == ["symbiont"]
    assert out.figure.track_order == ["meta:symbiont"]
    assert visual_style(cur, None, U).layout == U and cur.layout == R                 # não altera o original


# ------------------------------------------------------------------ janela
@pytest.fixture
def window(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    shown: list[str] = []
    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    w = MainWindow()
    w.shown = shown
    qtbot.addWidget(w)
    assert w.open_tree(TREE)
    w.figure_panel.itol.import_files(["examples/itol/colorstrip.txt", "examples/itol/binary.txt"], wait=True)
    w.generate()
    return w


def _request(tmp_path, layouts, formats, presets=None, **kw):  # type: ignore[no-untyped-def]
    from jabuti.views.batch_export import BatchRequest

    return BatchRequest(layouts=layouts, presets=presets or [("atual", None)], formats=formats,
                        dest=tmp_path / "lote", project="arvore", **kw)


def _state(w) -> tuple:  # type: ignore[no-untyped-def]
    return (json.dumps(w.collect_preset(), sort_keys=True), signature(w.renderer.scene), w.windowTitle(),
            w.isWindowModified(), w.viz_tab.layout_cb.currentData())


def test_two_layouts_two_formats_and_state_restored(window, tmp_path):
    before = _state(window)
    report = window.batch_export(_request(tmp_path, [R, C], ["svg", "png"]), show_progress=False)
    names = sorted(p.name for p in (tmp_path / "lote").iterdir())
    assert names == ["arvore_circular_atual.png", "arvore_circular_atual.svg",
                     "arvore_retangular_atual.png", "arvore_retangular_atual.svg"]
    assert len(report.generated) == 4 and not report.failed and not report.skipped
    for p in report.generated:
        head = p.read_bytes()[:200]
        assert head.startswith(b"\x89PNG") if p.suffix == ".png" else b"<svg" in p.read_bytes()[:2000]
    # o SVG circular é de fato circular (diferente do retangular)
    assert (tmp_path / "lote" / "arvore_circular_atual.svg").read_bytes() != \
        (tmp_path / "lote" / "arvore_retangular_atual.svg").read_bytes()
    after = _state(window)
    assert after[0] == before[0] and same(after[1], before[1]) is None and after[2:] == before[2:]
    assert "4 gerado(s)" in window.shown[-1]


def test_cancel_in_the_middle(window, tmp_path):
    from jabuti.views.batch_export import BatchRunner

    runner = BatchRunner(window, _request(tmp_path, [R, C], ["svg", "pdf"]), show_progress=False)
    done = []
    real = runner.export_one
    runner.export_one = lambda scene, fmt, path: (real(scene, fmt, path), done.append(path))
    runner.is_canceled = lambda: len(done) >= 2
    before = _state(window)
    report = runner.run()
    assert report.cancelled and report.not_run == 2 and len(report.generated) == 2
    assert len(list((tmp_path / "lote").iterdir())) == 2
    assert "Cancelado: 2" in report.summary()
    after = _state(window)
    assert after[0] == before[0] and same(after[1], before[1]) is None


def test_error_in_one_item_does_not_stop_the_rest(window, tmp_path, monkeypatch):
    from jabuti.views import batch_export

    def broken_pdf(scene, path):  # type: ignore[no-untyped-def]
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(batch_export, "export_pdf", broken_pdf)
    report = window.batch_export(_request(tmp_path, [R, C], ["svg", "pdf"]), show_progress=False)
    assert len(report.generated) == 2 and len(report.failed) == 2
    assert all(n.endswith(".pdf") for n, _why in report.failed)
    assert "No space left" in report.failed[0][1]
    assert "com erro" in window.shown[-1]


def test_render_error_marks_its_items_and_continues(window, tmp_path, monkeypatch):
    real = window.render_to_scene

    def flaky(style, scene):  # type: ignore[no-untyped-def]
        if style.layout == C:
            raise RuntimeError("falha no circular")
        return real(style, scene)
    monkeypatch.setattr(window, "render_to_scene", flaky)
    report = window.batch_export(_request(tmp_path, [C, R], ["svg"]), show_progress=False)
    assert [p.name for p in report.generated] == ["arvore_retangular_atual.svg"]
    assert report.failed == [("arvore_circular_atual.svg", "erro ao desenhar: falha no circular")]


def test_too_large_images_are_skipped_with_reason(window, tmp_path):
    report = window.batch_export(_request(tmp_path, [C], ["svg", "png"], png_dpi=2400), show_progress=False)
    assert [p.name for p in report.generated] == ["arvore_circular_atual.svg"]
    assert len(report.skipped) == 1 and "grande demais" in report.skipped[0][1]
    assert not (tmp_path / "lote" / "arvore_circular_atual.png").exists()


def test_existing_files_overwrite_skip_or_cancel(window, tmp_path):
    from jabuti.views.batch_export import BatchRunner

    (tmp_path / "lote").mkdir()
    old = tmp_path / "lote" / "arvore_retangular_atual.svg"
    old.write_text("antigo", encoding="utf-8")
    req = _request(tmp_path, [R, C], ["svg"])
    r = BatchRunner(window, req, show_progress=False)
    r.confirm_overwrite = lambda existing: None
    assert r.run() is None and old.read_text(encoding="utf-8") == "antigo"
    r = BatchRunner(window, req, show_progress=False)
    r.confirm_overwrite = lambda existing: "skip"
    rep = r.run()
    assert old.read_text(encoding="utf-8") == "antigo" and rep.skipped == [("arvore_retangular_atual.svg", "já existia (pulado)")]
    assert [p.name for p in rep.generated] == ["arvore_circular_atual.svg"]
    r = BatchRunner(window, req, show_progress=False)
    r.confirm_overwrite = lambda existing: "overwrite"
    assert len(r.run().generated) == 2 and "<svg" in old.read_text(encoding="utf-8")


def test_preset_changes_only_visual(window, tmp_path):
    preset = copy.deepcopy(window.current_style())
    preset.branch.color = "#c0ffee"
    preset.figure.hidden_tracks = ["tudo"]                 # não pode valer no lote
    before = _state(window)
    report = window.batch_export(_request(tmp_path, [R], ["svg"], presets=[("atual", None), ("verde", preset)]),
                                 show_progress=False)
    a = (tmp_path / "lote" / "arvore_retangular_atual.svg").read_text(encoding="utf-8")
    b = (tmp_path / "lote" / "arvore_retangular_verde.svg").read_text(encoding="utf-8")
    assert len(report.generated) == 2
    assert "#c0ffee" in b.lower() and "#c0ffee" not in a.lower()
    # as colunas do projeto continuam no desenho do preset (hidden_tracks do preset não vale)
    from PySide6.QtWidgets import QGraphicsScene

    from jabuti.exporters.batch import visual_style

    scene = QGraphicsScene()
    window.render_to_scene(visual_style(window.current_style(), preset, R), scene)
    tags = {i.data(1) for i in scene.items()}
    assert "binary" in tags
    assert window.current_style().branch.color != "#c0ffee"
    assert _state(window)[0] == before[0]


def test_dialog_defaults_preview_and_validation(window, qtbot):
    from jabuti.views.batch_export import BatchDialog

    dlg = BatchDialog(window)
    qtbot.addWidget(dlg)
    req = dlg.request()
    assert req.layouts == [R] and req.formats == ["svg"] and req.presets == [("atual", None)]
    assert req.project == "paraburkholderia_40" and "paraburkholderia_40_retangular_atual.svg" in dlg.preview.text()
    dlg.layout_boxes[C].setChecked(True)
    dlg.format_boxes["png"].setChecked(True)
    assert "(4 arquivos)" in dlg.preview.text() and dlg.ok.isEnabled()
    dlg.template.setText("{nome}.{ext}")
    assert not dlg.ok.isEnabled() and "desconhecido" in dlg.preview.text()
    dlg.template.setText(DEFAULT_TEMPLATE)
    for cb in dlg.format_boxes.values():
        cb.setChecked(False)
    assert not dlg.ok.isEnabled() and "formato" in dlg.preview.text()
    dlg.add_preset("escuro", RenderStyle())
    assert dlg.preset_list.count() == 2


def test_menu_action_and_no_tree(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    shown = []
    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.actions_by_name["batch"].text() == "Exportar em lote…"
    assert w.batch_export() is None and "Abra uma árvore" in shown[-1]
