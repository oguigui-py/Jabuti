"""Rede de segurança dos testes: diálogo modal não interceptado falha (não trava o CI)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


def test_unintercepted_dialogs_fail_instead_of_hanging(qtbot):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    box = QMessageBox(QMessageBox.Icon.Warning, "Alterações não salvas", "Salvar?")
    with pytest.raises(AssertionError, match="Salvar"):
        box.exec()
    with pytest.raises(AssertionError, match="QMessageBox.question"):
        QMessageBox.question(None, "Pergunta", "Sim?")
    with pytest.raises(AssertionError, match="getSaveFileName"):
        QFileDialog.getSaveFileName(None, "Salvar", "", "*")


def test_close_does_not_prompt_in_tests_on_any_platform(qtbot, monkeypatch, tmp_path):
    """Na plataforma "windows" do CI, prompts_enabled() seria True: o conftest desliga."""
    import shutil

    from PySide6.QtGui import QGuiApplication

    import jabuti.views.main_window as mw

    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    shutil.copy("examples/paraburkholderia_40.treefile", tmp_path / "t.treefile")
    w = mw.MainWindow()
    qtbot.addWidget(w)
    assert w.ask_on_close is False
    w.open_tree(tmp_path / "t.treefile")
    w.style_panel.ladder.setCurrentIndex(w.style_panel.ladder.findData("asc"))
    w.render_live()
    assert w.project.is_dirty() and w.close()                   # fecha sem perguntar


def test_real_app_still_prompts_with_a_screen(monkeypatch):
    from PySide6.QtGui import QGuiApplication

    import jabuti.views.main_window as mw

    monkeypatch.undo()                                          # tira o desligamento do conftest
    for plat, expected in (("windows", True), ("cocoa", True), ("xcb", True), ("offscreen", False), ("minimal", False)):
        monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda p=plat: p))
        assert mw.prompts_enabled() is expected, plat
