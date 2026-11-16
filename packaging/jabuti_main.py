"""Ponto de entrada do executável (PyInstaller): o mesmo que ``python -m jabuti``."""

from jabuti.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
