"""Gera packaging/jabuti.icns (macOS) e packaging/jabuti.ico (Windows) a partir de
jabuti/assets/jabuti_icone_1024.png, sem dependências além do PySide6.

    python scripts/make_icons.py

* .icns: iconset com todos os tamanhos (16…512 em 1x e 2x) + ``iconutil`` (só no macOS).
  O desenho ocupa a grade de 824 px dentro do quadro de 1024 px, como os ícones do macOS,
  para ficar do mesmo tamanho que os vizinhos no Dock.
* .ico: 16, 24, 32, 48, 64, 128 e 256 px, cada um em PNG dentro do .ico (formato aceito
  desde o Windows Vista), quadro inteiro.

O PNG original nunca é alterado; as reduções usam suavização (SmoothTransformation).
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402

from jabuti.resources import JABUTI_ICON, asset_path  # noqa: E402

OUT = ROOT / "packaging"
ICNS_SIZES = (16, 32, 128, 256, 512)          # cada um em 1x e 2x
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
MAC_GRID = 824 / 1024                          # área do desenho no quadro do macOS


def scaled(src: QImage, size: int, content: float = 1.0) -> QImage:
    """Quadro ``size``×``size`` transparente com o ícone reduzido a ``content`` do lado."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    inner = max(1, round(size * content))
    small = src.scaled(inner, inner, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    off = (size - inner) // 2
    p.drawImage(QRect(off, off, inner, inner), small)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not img.save(buf, "PNG"):
        raise RuntimeError("falha ao gerar PNG")
    return bytes(ba.data())


def write_ico(src: QImage, path: Path, sizes=ICO_SIZES) -> Path:  # type: ignore[no-untyped-def]
    """ICO com uma imagem PNG por tamanho (cabeçalho ICONDIR + ICONDIRENTRY)."""
    blobs = [png_bytes(scaled(src, s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, blob in zip(sizes, blobs):
        dim = 0 if s >= 256 else s                 # 0 = 256 no formato ICO
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))
    return path


def write_icns(src: QImage, path: Path) -> Path | None:
    """Iconset completo + iconutil. Devolve None fora do macOS (sem iconutil)."""
    tool = shutil.which("iconutil")
    if tool is None:
        print("iconutil não encontrado (só existe no macOS): .icns não gerado")
        return None
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "jabuti.iconset"
        iconset.mkdir()
        for s in ICNS_SIZES:
            for scale, suffix in ((1, ""), (2, "@2x")):
                px = s * scale
                scaled(src, px, MAC_GRID).save(str(iconset / f"icon_{s}x{s}{suffix}.png"), "PNG")
        subprocess.run([tool, "-c", "icns", str(iconset), "-o", str(path)], check=True)
    return path


_APP: list = []                                # mantém o QGuiApplication vivo


def main() -> int:
    _APP.append(QGuiApplication.instance() or QGuiApplication(sys.argv[:1]))
    src = QImage(str(asset_path(JABUTI_ICON)))
    if src.isNull() or src.width() < 1024:
        print(f"ícone de origem inválido: {asset_path(JABUTI_ICON)}")
        return 1
    OUT.mkdir(exist_ok=True)
    ico = write_ico(src, OUT / "jabuti.ico")
    print(f"{ico.relative_to(ROOT)}  {ico.stat().st_size // 1024} KB  ({', '.join(map(str, ICO_SIZES))} px)")
    icns = write_icns(src, OUT / "jabuti.icns")
    if icns:
        print(f"{icns.relative_to(ROOT)}  {icns.stat().st_size // 1024} KB  (16 a 1024 px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
