"""Ponto de entrada da aplicação."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QEvent, QObject, QTimer

from jabuti import __version__


def splash_enabled(app) -> bool:  # type: ignore[no-untyped-def]
    """Abertura desligada com ``JABUTI_NO_SPLASH=1`` ou sem tela real (offscreen)."""
    if os.environ.get("JABUTI_NO_SPLASH", "").strip().lower() not in ("", "0", "false", "no"):
        return False
    return app.platformName() not in ("offscreen", "minimal")


class Launcher(QObject):
    """Mostra a abertura, constrói a janela principal enquanto ela aparece e
    troca para a janela principal sem piscar (ela surge por baixo do fade-out)."""

    def __init__(self, args: list[str], use_splash: bool, splash_ms: int | None = None,
                 itol: list[str] | None = None) -> None:
        super().__init__()
        self.paths: list[str] = [a for a in args[1:2] if a]   # árvore/projeto da linha de comando
        self.itol = list(itol or [])
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
        if self.paths:
            if self.use_splash:
                QTimer.singleShot(0, self._open_files)
            else:
                self._open_files()

    @property
    def path(self) -> str | None:
        return self.paths[0] if self.paths else None

    def _open_files(self) -> None:
        win = self.build()
        paths, self.paths = self.paths, []
        if not paths:
            return
        # na abertura não há o que salvar: abre direto (sem perguntar)
        if win.open_paths(paths, ask=False) and self.itol:
            win.import_itol(self.itol, wait=False)
            self.itol = []

    def open_file(self, path: str) -> None:
        """Arquivo entregue pelo sistema (duplo clique / "Abrir com" no macOS).

        Antes da janela aparecer, entra na fila e abre junto com ela; com o app já
        aberto, substitui a figura atual (perguntando se há alterações não salvas)."""
        if self.window is not None and self.window.isVisible():
            self.window.open_paths([path])
            self.window.raise_()
            self.window.activateWindow()
        else:
            self.paths.append(path)

    def _splash_gone(self) -> None:
        self.splash = None
        if self.window is not None:
            self.window.activateWindow()


class FileOpenFilter(QObject):
    """Recebe o ``QFileOpenEvent`` do macOS (duplo clique em .jabuti/.nwk…, "Abrir com",
    arrastar para o ícone do Dock) e repassa ao ``Launcher``."""

    def __init__(self, launcher: Launcher) -> None:
        super().__init__()
        self.launcher = launcher

    def eventFilter(self, obj, event) -> bool:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.type() == QEvent.Type.FileOpen:
            path = event.file() or event.url().toLocalFile()
            if path:
                self.launcher.open_file(path)
                return True
        return False


def run(tree: str | None = None, itol: list[str] | None = None, splash: bool = True) -> int:
    """Abre a janela (com a abertura animada, salvo ``splash=False``) e roda o laço do Qt."""
    from PySide6.QtWidgets import QApplication

    from jabuti.logs import get_logger, setup_logging
    from jabuti.views.errors import install_excepthook

    from jabuti import macos

    if sys.platform == "darwin":
        macos.set_app_name("Jabuti")          # menu superior: "Jabuti" em vez de "Python"
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Jabuti")
    app.setOrganizationName("Jabuti")
    app.setApplicationVersion(__version__)
    try:
        from jabuti.resources import app_icon

        app.setWindowIcon(app_icon())        # janelas e barra de tarefas (Windows/Linux)
    except Exception:  # noqa: BLE001
        pass
    if sys.platform == "darwin":                # o Dock ignora o setWindowIcon: AppKit direto
        from jabuti.resources import JABUTI_ICON, assets_dir

        macos.set_dock_icon(assets_dir() / JABUTI_ICON)
    setup_logging()
    get_logger().info("Jabuti %s iniciado", __version__)
    install_excepthook()
    launcher = Launcher(["jabuti", tree] if tree else ["jabuti"], splash and splash_enabled(app), itol=itol)
    file_open = FileOpenFilter(launcher)
    app.installEventFilter(file_open)
    launcher.start()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    """Compatibilidade: ``main([prog, árvore])``; a linha de comando completa está em ``jabuti.cli``."""
    from jabuti.cli import main as cli_main

    args = sys.argv if argv is None else argv
    return cli_main(list(args[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
