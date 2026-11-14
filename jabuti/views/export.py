"""Exportação da cena para SVG, PDF e PNG."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSize, QSizeF
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
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
    """Destaques de busca não vão para o arquivo exportado."""
    items = [it for it in scene.items() if it.data(0) == "highlight" and it.isVisible()]
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


def export_png(scene: QGraphicsScene, path: str | Path, dpi: int = 300) -> Path:
    src = _source(scene)
    p = Path(path)
    scale = dpi / 72.0
    w, h = int(src.width() * scale), int(src.height() * scale)
    max_side = 30000
    if max(w, h) > max_side:
        raise ExportError(
            f"Imagem grande demais ({w}×{h} px). Reduza o DPI ou use SVG/PDF."
        )
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    if img.isNull():
        raise ExportError("Memória insuficiente para essa resolução. Reduza o DPI.")
    img.fill(QColor(0, 0, 0, 0))  # a cena pinta o fundo (ou não, se transparente)
    img.setDotsPerMeterX(int(dpi / 0.0254))
    img.setDotsPerMeterY(int(dpi / 0.0254))
    painter = QPainter(img)
    try:
        _render(scene, painter, QRectF(0, 0, w, h), src)
    finally:
        painter.end()
    if not img.save(str(p), "PNG"):
        raise ExportError(f"Não foi possível salvar {p}")
    return p
