"""Ponto de entrada da aplicação."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QObject, QTimer


def splash_enabled(app) -> bool:  # type: ignore[no-untyped-def]
    """Abertura desligada com ``JABUTI_NO_SPLASH=1`` ou sem tela real (offscreen)."""
    if os.environ.get("JABUTI_NO_SPLASH", "").strip().lower() not in ("", "0", "false", "no"):
        return False
    return app.platformName() not in ("offscreen", "minimal")


class Launcher(QObject):
    """Mostra a abertura, constrói a janela principal enquanto ela aparece e
    troca para a janela principal sem piscar (ela surge por baixo do fade-out)."""

    def __init__(self, args: list[str], use_splash: bool, splash_ms: int | None = None) -> None:
        super().__init__()
        self.path = args[1] if len(args) > 1 else None
        self.use_splash = use_splash
        self.splash_ms = splash_ms
        self.window = None
        self.splash = None

    def start(self) -> None:
        if not self.use_splash:
            self.build()
            self.show_main()
            return
        from jabuti.views.splash import SplashScreen

        self.splash = SplashScreen(self.splash_ms)
        self.splash.closing.connect(self.show_main)
        self.splash.finished.connect(self._splash_gone)
        self.splash.start()
        # constrói depois do fade-in, para a abertura já estar desenhada na tela
        QTimer.singleShot(SplashScreen.FADE_IN_MS + 30, self.build)

    def build(self):  # type: ignore[no-untyped-def]
        if self.window is None:
            from jabuti.views.main_window import MainWindow

            self.window = MainWindow()
        return self.window

    def show_main(self) -> None:
        win = self.build()
        if win.isVisible():
            return
        win.show()
        win.raise_()
        win.activateWindow()
        if self.splash is not None:
            self.splash.raise_()          # o fade-out continua por cima
        if self.path:
            if self.use_splash:
                QTimer.singleShot(0, lambda: win.tree_tab.load(self.path))
            else:
                win.tree_tab.load(self.path)

    def _splash_gone(self) -> None:
        self.splash = None
        if self.window is not None:
            self.window.activateWindow()


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from jabuti.views.errors import install_excepthook

    args = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(args)
    app.setApplicationName("Jabuti")
    app.setOrganizationName("Jabuti")
    install_excepthook()
    launcher = Launcher(args, splash_enabled(app))
    launcher.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
