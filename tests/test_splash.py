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


# ------------------------------------------------------------------ logo do Jabuti
def test_jabuti_logo_has_alpha_and_transparent_background():
    from PySide6.QtGui import QImage

    p = resources.asset_path(resources.JABUTI_LOGO)
    img = QImage(str(p))
    assert p.parent.name == "assets" and not img.isNull() and img.hasAlphaChannel()
    assert (img.width(), img.height()) == (2048, 2048)
    w, h = img.width(), img.height()
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 5)):
        assert img.pixelColor(x, y).alpha() == 0          # sem fundo branco
    icon = QImage(str(resources.asset_path(resources.JABUTI_ICON)))
    assert (icon.width(), icon.height()) == (1024, 1024)
    assert resources.asset_path(resources.JABUTI_LOGO_SVG).read_text(encoding="utf-8").lstrip().startswith("<svg")


@pytest.mark.parametrize("dpr", [1.0, 2.0])
def test_trim_is_in_memory_and_respects_dpr(qtbot, dpr):
    import hashlib

    p = resources.asset_path(resources.JABUTI_LOGO)
    before = hashlib.sha1(p.read_bytes()).hexdigest()
    pm = resources.load_pixmap(resources.JABUTI_LOGO, 300, dpr, trim=True)
    assert pm.width() == round(300 * dpr) and pm.devicePixelRatio() == dpr
    assert 1.7 < pm.width() / pm.height() < 1.9                # recortado (o original é quadrado)
    full = resources.load_pixmap(resources.JABUTI_LOGO, 300, dpr)
    assert full.width() == full.height()
    assert hashlib.sha1(p.read_bytes()).hexdigest() == before  # arquivo intacto


def test_splash_shows_jabuti_logo_name_and_ptbr_credits(qtbot):
    from jabuti.views import splash

    assert splash.APP_NAME == "Jabuti"
    assert splash.CREDIT_1 == "Produzido pelo Laboratório de Genômica Eco-evolutiva Microbiana"
    assert splash.CREDIT_2 == "Desenvolvido por Guilherme Gonçalves"
    s = splash.SplashScreen(10_000)
    qtbot.addWidget(s)
    s._prepare_layers()
    assert not s.logo.isNull() and s.logo.toImage().hasAlphaChannel()
    lay = s._layout
    assert lay["name_y"] > lay["top"] + lay["logo_h"] - 1 and lay["credits_y"] > lay["name_y"]
    assert lay["credits_y"] < splash.MARGIN + splash.CARD_H - 40       # cabe no cartão
    # a árvore animada fica na faixa da esquerda (fora do halo da logo)
    assert max(b.x1 for b in s._branches) <= splash.CARD_W * splash.TREE_ZONE + 0.5


def test_window_and_app_icon(qtbot):
    from jabuti.views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    assert not w.windowIcon().isNull()
    icon = resources.app_icon()
    assert not icon.isNull() and icon.actualSize(__import__("PySide6.QtCore", fromlist=["x"]).QSize(64, 64)).width() == 64


def test_about_dialog_logos_and_credits(qtbot):
    from jabuti.views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    d = w.about_dialog()
    qtbot.addWidget(d)
    text = d.text()
    assert "Produzido pelo Laboratório de Genômica Eco-evolutiva Microbiana" in text
    assert "Desenvolvido por Guilherme Gonçalves" in text and "Jabuti" in text and "Versão" in text
    assert not d.logo.pixmap().isNull() and not d.lgem.pixmap().isNull()
    assert d.lgem.pixmap().height() / d.lgem.pixmap().devicePixelRatio() < 50       # pequena
    assert d.minimumHeight() >= d.layout().totalHeightForWidth(d.width()) - 1


def test_no_english_credits_anywhere_in_the_interface():
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for f in (root / "jabuti").rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "Produced by" not in text and "Designed by" not in text, f
    help_text = subprocess.run([sys.executable, "-m", "jabuti", "--help"], capture_output=True, text=True,
                               cwd=root, timeout=60).stdout
    assert "Produzido pelo Laboratório" in help_text and "Desenvolvido por Guilherme" in help_text
    assert "Produced" not in help_text and "Designed" not in help_text


def test_assets_are_packaged():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    toml = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert '"assets/*.png"' in toml and '"assets/*.svg"' in toml
    assert {"jabuti_logo.png", "jabuti_logo.svg", "jabuti_icone_1024.png", "logo_lgem.png"} <= \
        {p.name for p in (root / "jabuti" / "assets").iterdir()}
    stray = [p for p in root.rglob("jabuti_logo*") if "assets" not in p.parts and ".venv" not in p.parts]
    assert not stray, stray
