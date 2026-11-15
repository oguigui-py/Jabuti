"""Localização de assets (imagens) — funciona rodando do código e empacotado.

Com PyInstaller, os arquivos de dados ficam em ``sys._MEIPASS``; o spec deve
incluir ``datas=[("jabuti/assets", "jabuti/assets")]``. Instalado via pip, os
assets vão como package-data (ver ``pyproject.toml``).
"""

from __future__ import annotations

import sys
from pathlib import Path

LGEM_LOGO = "logo_lgem.png"           # Laboratório de Genômica Eco-evolutiva Microbiana
JABUTI_LOGO = "jabuti_logo.png"       # desenho da tartaruga, fundo transparente (2048×2048)
JABUTI_LOGO_SVG = "jabuti_logo.svg"
JABUTI_ICON = "jabuti_icone_1024.png"  # ícone do app (fundo off-white, cantos arredondados)
LOGO = LGEM_LOGO                      # compatibilidade
# verde-escuro amostrado da logo do LGEM
BRAND_GREEN = "#003c1e"
# verde-escuro da logo do Jabuti (contorno da tartaruga, no SVG)
JABUTI_GREEN = "#0f3d24"


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


def _alpha_bounds(img):  # type: ignore[no-untyped-def]
    """Retângulo com os pixels não transparentes (amostrado; sem tocar no arquivo)."""
    from PySide6.QtCore import QRect

    w, h = img.width(), img.height()
    step = max(1, min(w, h) // 512)
    xs, ys = [], []
    for y in range(0, h, step):
        for x in range(0, w, step):
            if img.pixelColor(x, y).alpha() > 8:
                xs.append(x)
                ys.append(y)
    if not xs:
        return QRect(0, 0, w, h)
    x0, y0 = max(min(xs) - step, 0), max(min(ys) - step, 0)
    x1, y1 = min(max(xs) + step, w - 1), min(max(ys) + step, h - 1)
    return QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def load_pixmap(name: str, width: float, device_pixel_ratio: float = 1.0, trim: bool = False):  # type: ignore[no-untyped-def]
    """Asset escalado só na exibição (o arquivo original nunca é alterado).

    ``width`` em pixels lógicos; a imagem é gerada em ``width × dpr`` pixels físicos com
    ``SmoothTransformation`` (nítida em telas retina). ``trim`` recorta, em memória, as bordas
    totalmente transparentes. Devolve um QPixmap nulo se o arquivo não puder ser lido.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPixmap

    img = QImage(str(asset_path(name)))
    if img.isNull():
        return QPixmap()
    if trim and img.hasAlphaChannel():
        img = img.copy(_alpha_bounds(img))
    dpr = max(float(device_pixel_ratio), 1.0)
    target = max(1, round(width * dpr))
    scaled = img.scaledToWidth(target, Qt.TransformationMode.SmoothTransformation)
    pm = QPixmap.fromImage(scaled)
    pm.setDevicePixelRatio(dpr)
    return pm


def app_icon():  # type: ignore[no-untyped-def]
    """Ícone da janela e do aplicativo (vários tamanhos a partir do PNG de 1024 px)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon, QImage, QPixmap

    icon = QIcon()
    img = QImage(str(asset_path(JABUTI_ICON)))
    if img.isNull():
        return icon
    for size in (16, 32, 64, 128, 256, 512, 1024):
        icon.addPixmap(QPixmap.fromImage(img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation)))
    return icon


def load_logo_pixmap(width: float, device_pixel_ratio: float = 1.0):  # type: ignore[no-untyped-def]
    """Logo do LGEM escalada (compatibilidade; use ``load_pixmap``)."""
    return load_pixmap(LGEM_LOGO, width, device_pixel_ratio)


def readme_path() -> Path | None:
    """README.md junto do código (ou empacotado ao lado dos assets); None se não houver."""
    for base in (assets_dir().parent.parent, assets_dir().parent):
        p = base / "README.md"
        if p.is_file():
            return p
    return None
