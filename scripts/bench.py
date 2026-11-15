"""Tempo de desenho e de exportação com árvores sintéticas grandes, em todos os layouts.

Uso:  python scripts/bench.py [500 1000 2000] [--export]

Cada árvore é aleatória (semente fixa), com metadados (faixa + cor dos ramos), uma coluna de
barras e legenda na figura. Nada é gravado fora de uma pasta temporária.
"""

from __future__ import annotations

import os
import random
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JABUTI_NO_SPLASH", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def random_newick(n: int, seed: int = 1) -> str:
    rng = random.Random(seed)
    nodes = [f"G{i:05d}:{rng.uniform(0.01, 0.3):.4f}" for i in range(n)]
    while len(nodes) > 1:
        a = nodes.pop(rng.randrange(len(nodes)))
        b = nodes.pop(rng.randrange(len(nodes)))
        nodes.append(f"({a},{b}){rng.randint(50, 100)}:{rng.uniform(0.005, 0.1):.4f}")
    return nodes[0].rsplit(":", 1)[0] + ";"


def main(argv: list[str]) -> int:
    sizes = [int(a) for a in argv if a.isdigit()] or [500, 1000, 2000]
    do_export = "--export" in argv
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["JABUTI_CONFIG_DIR"] = str(Path(tmp) / "cfg")
        from jabuti.style import LayoutKind
        from jabuti.views.export import ExportError, export_png, export_svg
        from jabuti.views.main_window import MainWindow

        print(f"{'folhas':>6} {'layout':<12} {'desenho (s)':>11} {'itens':>7}"
              + (f" {'SVG (s)':>8} {'PNG (s)':>8}" if do_export else ""))
        for n in sizes:
            tree = Path(tmp) / f"t{n}.nwk"
            tree.write_text(random_newick(n), encoding="utf-8")
            meta = Path(tmp) / f"m{n}.tsv"
            rng = random.Random(2)
            meta.write_text("genome\thabitat\tsize\n" + "".join(
                f"G{i:05d}\t{rng.choice(['solo', 'raiz', 'nódulo', 'água'])}\t{rng.uniform(3, 9):.2f}\n"
                for i in range(n)), encoding="utf-8")
            win = MainWindow()
            win.tree_tab.load(tree)
            win.metadata_tab.load(meta)
            fp = win.figure_panel
            fp.add_bar()
            orig = win.current_style
            for kind in LayoutKind:
                def cs(kind=kind):  # type: ignore[no-untyped-def]
                    s = orig()
                    s.layout = kind
                    s.legend.in_figure = True
                    s.metadata.color_by = "habitat"
                    s.metadata.color_branches = True
                    s.metadata.strips = ["habitat"]
                    return s
                win.current_style = cs
                t0 = time.perf_counter()
                win.generate()
                app.processEvents()
                dt = time.perf_counter() - t0
                row = f"{n:>6} {kind.value:<12} {dt:>11.2f} {len(win.renderer.scene.items()):>7}"
                if do_export:
                    t0 = time.perf_counter()
                    export_svg(win.renderer.scene, Path(tmp) / "f.svg")
                    t1 = time.perf_counter()
                    try:
                        export_png(win.renderer.scene, Path(tmp) / "f.png", dpi=150)
                        png = f"{time.perf_counter() - t1:>8.2f}"
                    except ExportError:
                        png = f"{'grande':>8}"           # > 30000 px: o app pede DPI menor ou SVG/PDF
                    row += f" {t1 - t0:>8.2f} {png}"
                print(row, flush=True)
            win.close()
            win.deleteLater()
            app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
