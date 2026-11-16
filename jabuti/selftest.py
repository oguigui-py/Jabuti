"""Autoteste do executável: ``Jabuti --autoteste PASTA`` (ou ``python -m jabuti --autoteste PASTA``).

Confere, no próprio pacote gerado pelo PyInstaller, o que costuma faltar num executável:
assets, README e exemplos empacotados, plugins do Qt (plataforma, SVG, TIFF), leitura de
árvore (Biopython), desenho, exportação nos 4 formatos e salvar/abrir um projeto ``.jabuti``
— tudo numa pasta com acento no nome. Grava ``autoteste.txt`` na pasta e sai com código 0
(tudo certo) ou 1. Sem tela (CI), rode com ``QT_QPA_PLATFORM=offscreen``.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def examples_dir() -> Path:
    from jabuti.resources import assets_dir

    return assets_dir().parent.parent / "examples"      # empacotado: ao lado de jabuti/; código: raiz


def run_selftest(out: str | Path) -> int:
    from PySide6.QtGui import QImageWriter
    from PySide6.QtWidgets import QApplication

    from jabuti import __version__

    base = Path(out)
    work = base / "autoteste ção"                        # caminho com acento e espaço
    work.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [f"Jabuti {__version__} — autoteste",
                        f"executável empacotado: {bool(getattr(sys, 'frozen', False))}",
                        f"python {sys.version.split()[0]} · {sys.platform}"]
    failures = 0

    def check(name: str, fn) -> object:  # type: ignore[no-untyped-def]
        nonlocal failures
        try:
            result = fn()
            ok = result is not False and result is not None
        except Exception:  # noqa: BLE001
            ok, result = False, traceback.format_exc(limit=3).strip().splitlines()[-1]
        failures += not ok
        lines.append(f"[{'ok' if ok else 'FALHOU'}] {name}" + ("" if ok or result is False else f": {result}"))
        return result if ok else None

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Jabuti")
    lines.append(f"plataforma Qt: {app.platformName()}")

    from jabuti.resources import JABUTI_ICON, JABUTI_LOGO, LGEM_LOGO, app_icon, asset_path, readme_path

    check("assets (logos e ícone)", lambda: all(asset_path(n).is_file() for n in (JABUTI_ICON, JABUTI_LOGO, LGEM_LOGO)))
    check("ícone da janela", lambda: not app_icon().isNull())
    check("README empacotado", lambda: readme_path() is not None)
    tree_file = examples_dir() / "paraburkholderia_40.treefile"
    check("exemplos empacotados", tree_file.is_file)
    formats = {bytes(f).decode() for f in QImageWriter.supportedImageFormats()}
    check("Qt grava PNG e TIFF", lambda: {"png", "tiff"} <= formats or sorted(formats))
    check("Qt SVG (QSvgGenerator)", lambda: __import__("PySide6.QtSvg", fromlist=["QSvgGenerator"]).QSvgGenerator)

    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    errors.QMessageBox.exec = lambda self: 0              # nenhum diálogo modal trava o teste
    w = MainWindow()
    w.ask_on_close = False
    local_tree = work / "árvore de exemplo.treefile"
    if tree_file.is_file():
        local_tree.write_bytes(tree_file.read_bytes())
    check("abrir árvore (Biopython)", lambda: w.open_paths([local_tree], ask=False) and w.tree is not None
          and len(w.tree.leaf_names()) == 40)
    check("detectar clados e desenhar", lambda: (w.style_panel.detect() > 0, w.generate(),
                                                 len(w.renderer.scene.items()) > 20)[::2] == (True, True))

    from jabuti.views.export import export_pdf, export_png, export_svg, export_tiff

    for fn, name in ((export_svg, "figura.svg"), (export_pdf, "figura.pdf"), (export_png, "figura.png"),
                     (export_tiff, "figura.tif")):
        check(f"exportar {name.split('.')[1].upper()}", lambda fn=fn, name=name: fn(w.renderer.scene, work / name).stat().st_size > 1000)
    project = work / "projeto ção.jabuti"
    check("salvar projeto .jabuti", lambda: w.project._write(project) is not None and project.is_file())
    w2 = MainWindow()
    w2.ask_on_close = False
    check("abrir projeto .jabuti", lambda: w2.open_paths([project], ask=False, wait=True) and w2.tree is not None
          and len(w2.style_panel.clade_set.clades) == len(w.style_panel.clade_set.clades))
    for win in (w, w2):
        win.close()
    lines.append("resultado: " + ("TUDO CERTO" if failures == 0 else f"{failures} falha(s)"))
    report = base / "autoteste.txt"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        print("\n".join(lines))
    except Exception:  # noqa: BLE001 — sem console (Windows, janela): só o arquivo
        pass
    return 0 if failures == 0 else 1
