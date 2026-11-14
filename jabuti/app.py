"""Ponto de entrada da aplicação."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from jabuti.views.errors import install_excepthook
    from jabuti.views.main_window import MainWindow

    args = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(args)
    app.setApplicationName("Jabuti")
    app.setOrganizationName("Jabuti")
    install_excepthook()
    win = MainWindow()
    win.show()
    if len(args) > 1:
        win.tree_tab.load(args[1])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
