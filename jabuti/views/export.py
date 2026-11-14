"""Exportação da cena para SVG, PDF e PNG."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSize, QSizeF
from PySide6.QtGui import QColor, QImage, QImageWriter, QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import QGraphicsScene


class ExportError(Exception):
    pass


def _source(scene: QGraphicsScene) -> QRectF:
    rect = scene.sceneRect()
    if rect.isEmpty():
        raise ExportError("Nada para exportar: gere a visualização primeiro.")
    return rect


def _hidden_highlights(scene: QGraphicsScene) -> list:
    """Destaques de busca e a seleção não vão para o arquivo exportado."""
    items = [it for it in scene.items() if it.data(0) in ("highlight", "selection") and it.isVisible()]
    for it in items:
        it.setVisible(False)
    return items


def _render(scene: QGraphicsScene, painter: QPainter, target: QRectF, source: QRectF) -> None:
    hidden = _hidden_highlights(scene)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        scene.render(painter, target, source)
    finally:
        for it in hidden:
            it.setVisible(True)


def export_svg(scene: QGraphicsScene, path: str | Path, title: str = "Jabuti tree") -> Path:
    src = _source(scene)
    p = Path(path)
    gen = QSvgGenerator()
    gen.setFileName(str(p))
    gen.setSize(QSize(int(src.width()), int(src.height())))
    gen.setViewBox(QRectF(0, 0, src.width(), src.height()))
    gen.setTitle(title)
    gen.setDescription("Gerado por Jabuti")
    painter = QPainter()
    if not painter.begin(gen):
        raise ExportError(f"Não foi possível escrever em {p}")
    try:
        _render(scene, painter, QRectF(0, 0, src.width(), src.height()), src)
    finally:
        painter.end()
    return p


def export_pdf(scene: QGraphicsScene, path: str | Path) -> Path:
    src = _source(scene)
    p = Path(path)
    writer = QPdfWriter(str(p))
    writer.setResolution(72)  # 1 unidade de cena = 1 pt
    writer.setPageSize(QPageSize(QSizeF(src.width(), src.height()), QPageSize.Unit.Point))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
    writer.setTitle("Jabuti tree")
    writer.setCreator("Jabuti")
    painter = QPainter()
    if not painter.begin(writer):
        raise ExportError(f"Não foi possível escrever em {p}")
    try:
        _render(scene, painter, QRectF(0, 0, src.width(), src.height()), src)
    finally:
        painter.end()
    return p


MAX_SIDE = 30000            # px por lado
MAX_BYTES = 2_000_000_000   # ~2 GB de imagem na memória (4 bytes por pixel)


def _raster(scene: QGraphicsScene, dpi: int) -> QImage:
    """Imagem da cena na resolução pedida (1 unidade de cena = 1 pt = 1/72")."""
    src = _source(scene)
    scale = dpi / 72.0
    w, h = int(src.width() * scale), int(src.height() * scale)
    if max(w, h) > MAX_SIDE:
        raise ExportError(
            f"Imagem grande demais ({w}×{h} px a {dpi} dpi; o limite é {MAX_SIDE} px por lado). "
            "Reduza o DPI ou use SVG/PDF."
        )
    if w * h * 4 > MAX_BYTES:
        raise ExportError(
            f"Imagem grande demais para a memória ({w}×{h} px ≈ {w * h * 4 / 1e9:.1f} GB a {dpi} dpi). "
            "Reduza o DPI ou use SVG/PDF."
        )
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    if img.isNull():
        raise ExportError("Memória insuficiente para essa resolução. Reduza o DPI.")
    img.fill(QColor(0, 0, 0, 0))  # a cena pinta o fundo (ou não, se transparente)
    img.setDotsPerMeterX(round(dpi / 0.0254))
    img.setDotsPerMeterY(round(dpi / 0.0254))
    painter = QPainter(img)
    try:
        _render(scene, painter, QRectF(0, 0, w, h), src)
    finally:
        painter.end()
    return img


def export_png(scene: QGraphicsScene, path: str | Path, dpi: int = 300) -> Path:
    p = Path(path)
    img = _raster(scene, dpi)
    if not img.save(str(p), "PNG"):
        raise ExportError(f"Não foi possível salvar {p}")
    return p


def export_tiff(scene: QGraphicsScene, path: str | Path, dpi: int = 600, lzw: bool = True) -> Path:
    """TIFF (padrão 600 dpi com compressão LZW, como pedem as revistas)."""
    p = Path(path)
    img = _raster(scene, dpi)
    writer = QImageWriter(str(p), b"tiff")
    writer.setCompression(1 if lzw else 0)       # plugin TIFF do Qt: 1 = LZW
    if not writer.write(img):
        raise ExportError(f"Não foi possível salvar {p}: {writer.errorString()}")
    return p
