"""Tela de abertura, assets e identidade visual."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jabuti import resources  # noqa: E402


def test_logo_asset_is_original_png():
    from PySide6.QtGui import QImage

    p = resources.asset_path(resources.LOGO)
    assert p.parent.name == "assets" and p.parent.parent.name == "jabuti"
    img = QImage(str(p))
    assert not img.isNull()
    assert (img.width(), img.height()) == (3861, 2318)
    assert img.hasAlphaChannel()


def test_asset_path_under_pyinstaller(tmp_path, monkeypatch):
    target = tmp_path / "jabuti" / "assets"
    target.mkdir(parents=True)
    (target / "x.png").write_bytes(b"\x89PNG")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resources.asset_path("x.png") == target / "x.png"


def test_missing_asset_raises_clear_error():
    with pytest.raises(FileNotFoundError, match="nao_existe.png"):
        resources.asset_path("nao_existe.png")


@pytest.mark.parametrize("dpr", [1.0, 2.0])
def test_logo_scaled_at_runtime_for_retina(qtbot, dpr):
    pm = resources.load_logo_pixmap(360, dpr)
    assert pm.width() == round(360 * dpr)
    assert pm.devicePixelRatio() == dpr
    assert pm.width() / pm.devicePixelRatio() == pytest.approx(360)


def test_splash_opens_animates_and_closes(qtbot):
    from jabuti.views.splash import SplashScreen

    s = SplashScreen(duration_ms=700)
    qtbot.addWidget(s)
    with qtbot.waitSignals([s.closing, s.finished], timeout=4000, order="strict"):
        s.start()
        assert s.isVisible()
        assert not s.logo.isNull()
    assert s.frames >= 3                      # houve quadros de animação
    assert not s.isVisible()


@pytest.mark.parametrize("how", ["click", "key"])
def test_splash_skip(qtbot, how):
    from PySide6.QtCore import Qt

    from jabuti.views.splash import SplashScreen

    s = SplashScreen(duration_ms=60_000)
    qtbot.addWidget(s)
    s.start()
    with qtbot.waitSignal(s.finished, timeout=3000):
        if how == "click":
            qtbot.mouseClick(s, Qt.MouseButton.LeftButton)
        else:
            qtbot.keyClick(s, Qt.Key.Key_Space)


def test_motifs_change_over_time(qtbot):
    """O fundo é animado: quadros em instantes diferentes diferem."""
    from PySide6.QtGui import QImage, QPainter

    from jabuti.views.splash import CARD_H, CARD_W, SplashScreen

    s = SplashScreen()
    qtbot.addWidget(s)

    def frame(t):
        img = QImage(CARD_W, CARD_H, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        s.paint_motifs(p, t)
        p.end()
        return img

    assert frame(0.3) != frame(2.5)


def test_no_splash_env(qtbot, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from jabuti.app import Launcher, splash_enabled

    app = QApplication.instance()
    monkeypatch.setenv("JABUTI_NO_SPLASH", "1")
    assert splash_enabled(app) is False
    launcher = Launcher(["jabuti"], splash_enabled(app))
    launcher.start()
    qtbot.addWidget(launcher.window)
    assert launcher.splash is None
    assert launcher.window.isVisible()


def test_launcher_with_splash_then_loads_tree(qtbot, data_dir):
    from jabuti.app import Launcher

    launcher = Launcher(["jabuti", str(data_dir / "small.nwk")], use_splash=True, splash_ms=700)
    launcher.start()
    assert launcher.splash is not None and launcher.splash.isVisible()
    qtbot.waitUntil(lambda: launcher.window is not None and launcher.window.isVisible(), timeout=4000)
    qtbot.addWidget(launcher.window)
    qtbot.waitUntil(lambda: launcher.splash is None, timeout=4000)
    qtbot.waitUntil(lambda: launcher.window.tree is not None, timeout=4000)


def test_main_window_title_and_brand(qtbot):
    from PySide6.QtCore import QPoint

    from jabuti.views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    assert w.windowTitle() == "Jabuti"
    label = w.brand_label
    assert label.text() == "Jabuti" and label.font().bold()
    pos = label.mapTo(w, QPoint(0, 0))
    assert pos.x() < 40 and pos.y() < 80     # canto superior esquerdo
