"""Localização de assets (imagens) — funciona rodando do código e empacotado.

Com PyInstaller, os arquivos de dados ficam em ``sys._MEIPASS``; o spec deve
incluir ``datas=[("jabuti/assets", "jabuti/assets")]``. Instalado via pip, os
assets vão como package-data (ver ``pyproject.toml``).
"""

from __future__ import annotations

import sys
from pathlib import Path

LOGO = "logo_lgem.png"
# verde-escuro amostrado da logo do LGEM
BRAND_GREEN = "#003c1e"


def assets_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "jabuti" / "assets"
    return Path(__file__).resolve().parent / "assets"


def asset_path(name: str) -> Path:
    p = assets_dir() / name
    if not p.is_file():
        raise FileNotFoundError(f"Asset do Jabuti não encontrado: {p}")
    return p


def load_logo_pixmap(width: float, device_pixel_ratio: float = 1.0):  # type: ignore[no-untyped-def]
    """Logo escalada em tempo de execução (o arquivo original nunca é alterado).

    ``width`` em pixels lógicos; a imagem é gerada em ``width × dpr`` pixels
    físicos com ``SmoothTransformation`` para ficar nítida em telas retina.
    Devolve um QPixmap nulo se o arquivo não puder ser lido.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPixmap

    img = QImage(str(asset_path(LOGO)))
    if img.isNull():
        return QPixmap()
    dpr = max(float(device_pixel_ratio), 1.0)
    target = max(1, round(width * dpr))
    scaled = img.scaledToWidth(target, Qt.TransformationMode.SmoothTransformation)
    pm = QPixmap.fromImage(scaled)
    pm.setDevicePixelRatio(dpr)
    return pm
