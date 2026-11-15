"""Assinatura de cenas para o teste de regressão "tudo desligado = mesmo desenho".

``python tests/scene_baseline.py`` regrava ``tests/data/scene_baseline.json`` (só faça isso
quando uma mudança visual for intencional). A assinatura depende das fontes do sistema;
o teste é pulado se a métrica de referência for diferente da gravada.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).parent / "data" / "scene_baseline.json"


def font_probe() -> float:
    from PySide6.QtGui import QFont, QFontMetricsF

    f = QFont()
    f.setPointSizeF(10)
    f.setItalic(True)
    return round(QFontMetricsF(f).horizontalAdvance("Paraburkholderia xenovorans LB400"), 2)


def signature(scene) -> list:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QAbstractGraphicsShapeItem, QGraphicsSimpleTextItem

    out = []
    for it in scene.items():
        r = it.sceneBoundingRect()
        row = [type(it).__name__, str(it.data(1) or ""),
               round(r.x()), round(r.y()), round(r.width()), round(r.height()), round(it.zValue(), 1)]
        if isinstance(it, QGraphicsSimpleTextItem):
            row.append(it.text())
        if isinstance(it, QAbstractGraphicsShapeItem):
            row += [it.brush().color().name(QColorName.HexArgb), it.pen().color().name(QColorName.HexArgb),
                    round(it.pen().widthF(), 2), int(it.pen().style().value)]
        out.append(row)
    out.sort(key=_order)
    return out


def _order(row: list) -> str:
    # identidade (tipo, marca, texto, cores) primeiro; posição só desempata
    return json.dumps([row[0], row[1], row[6:], row[2:6]])


def same(a: list, b: list, tol: float = 1.5) -> str | None:
    """``None`` se as cenas forem iguais (posições com tolerância de arredondamento)."""
    if len(a) != len(b):
        return f"{len(a)} itens, esperados {len(b)}"
    for x, y in zip(sorted(a, key=_order), sorted(b, key=_order)):
        if x[:2] != y[:2] or x[6:] != y[6:] or any(abs(p - q) > tol for p, q in zip(x[2:6], y[2:6])):
            return f"{x} != {y}"
    return None


from PySide6.QtGui import QColor  # noqa: E402

QColorName = QColor.NameFormat


def scenarios():  # type: ignore[no-untyped-def]
    """(nome, função que desenha numa cena e devolve a cena)."""
    from PySide6.QtWidgets import QApplication, QGraphicsScene

    QApplication.instance() or QApplication([])
    from jabuti.models.annotations import metadata_colors, metadata_column
    from jabuti.models.clades import Clade, clades_by_k
    from jabuti.models.label_groups import LabelGroupSet, LabelLook
    from jabuti.parsers.metadata import load_metadata, match_table
    from jabuti.parsers.newick import load_tree
    from jabuti.style import LayoutKind, RenderStyle
    from jabuti.views.tree_renderer import TreeRenderer

    tree = load_tree(ROOT / "examples" / "paraburkholderia_40.treefile")
    table = load_metadata(ROOT / "examples" / "metadata.tsv")
    by_leaf = match_table(table, "genome", tree.leaf_names()).by_leaf
    clades = [Clade(f"C{i}", s, None, True, "auto") for i, s in enumerate(clades_by_k(tree, 4))]
    names = tree.leaf_names()

    def run(layout, full: bool, merge: bool = False, mode: str = "text"):  # type: ignore[no-untyped-def]
        def draw():  # type: ignore[no-untyped-def]
            scene = QGraphicsScene()
            st = RenderStyle(layout=layout, merge_backgrounds=merge)
            st.clades.label_mode = mode          # cenários antigos: cor nas letras (como gravados)
            kw = {}
            if full:
                st.clades.outer_strip = True
                st.clades.background = True
                st.clades.show_names = True
                st.support.mode = "symbols"
                st.symbols.shape = "circle"
                st.legend.in_figure = True
                pal = st.palette_colors()
                col1, _ = metadata_column(by_leaf, "habitat", pal, "#d9d9d9", 12)
                col2, _ = metadata_column(by_leaf, "gc_percent", pal, "#d9d9d9", 12)
                meta, legend = metadata_colors(by_leaf, "symbiont", pal)
                groups = LabelGroupSet()
                groups.add(names[:3], "selection", look=LabelLook(background="#ffe066", bold=True))
                small = min((c.leaves for c in clades if len(c.leaves) > 1), key=len)
                kw = dict(clades=clades, collapsed=[small],
                          columns=[col1, col2], meta_colors=meta, label_groups=groups, legend=[legend])
            else:
                kw = dict(clades=clades)
            TreeRenderer(scene).render(tree.copy(), st, **kw)
            return scene
        return draw

    return [
        ("rect-basic", run(LayoutKind.RECTANGULAR, False)),
        ("circ-basic", run(LayoutKind.CIRCULAR, False)),
        ("rect-full", run(LayoutKind.RECTANGULAR, True)),
        ("circ-full", run(LayoutKind.CIRCULAR, True)),
        # padrão atual: fundos vizinhos unidos (os de cima: modo antigo, idêntico ao desenho original)
        ("rect-full-merged", run(LayoutKind.RECTANGULAR, True, True)),
        ("circ-full-merged", run(LayoutKind.CIRCULAR, True, True)),
        # clados com fundo nos nomes (marca-texto, padrão desde o formato 2), fundos unidos
        ("rect-marca-texto", run(LayoutKind.RECTANGULAR, False, True, "background")),
        ("circ-marca-texto", run(LayoutKind.CIRCULAR, False, True, "background")),
        ("fan-marca-texto", run(LayoutKind.FAN, False, True, "background")),
        ("slanted-marca-texto", run(LayoutKind.SLANTED, False, True, "background")),
        ("unrooted-marca-texto", run(LayoutKind.UNROOTED, False, True, "background")),
        ("rect-full-marca-texto", run(LayoutKind.RECTANGULAR, True, True, "background")),
    ]


keep: list = []


def record(only_missing: bool = False) -> None:
    from PySide6.QtWidgets import QApplication

    keep.append(QApplication.instance() or QApplication([]))
    old = json.loads(BASELINE.read_text(encoding="utf-8")) if only_missing and BASELINE.exists() else None
    scenes = dict(old["scenes"]) if old else {}
    for name, fn in scenarios():
        if name not in scenes:
            scenes[name] = signature(fn())
    data = {"font_probe": old["font_probe"] if old else font_probe(), "scenes": scenes}
    BASELINE.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"gravado {BASELINE} ({', '.join(f'{k}: {len(v)} itens' for k, v in data['scenes'].items())})")


if __name__ == "__main__":
    import sys

    record(only_missing="--novos" in sys.argv)   # --novos: grava só os cenários que faltam
