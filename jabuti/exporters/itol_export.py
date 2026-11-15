"""Exportação da figura atual para o iTOL: árvore Newick + um arquivo por anotação (sem Qt).

Trabalha sobre o que foi efetivamente desenhado (``FigureSnapshot``, montado a cada desenho),
então anotações vindas de datasets iTOL importados saem na versão atual (cores, títulos e
ordem editados). As cores de ramos e rótulos vêm de ``ColorRules``: as mesmas da tela.

Todos os arquivos usam ``SEPARATOR TAB`` (nomes com espaço ou vírgula não quebram) e seguem
os templates oficiais do iTOL (palavra-chave na 1ª linha, cabeçalho, ``DATA``).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from jabuti import __version__
from jabuti.models.annotations import LeafColumn, LegendGroup
from jabuti.models.color_rules import ColorRules
from jabuti.models.tracks import CLADE_STRIP, BarTrack, StackedTrack, fmt_value
from jabuti.models.tree import Node, Tree
from jabuti.parsers.newick import write_newick

TREE_FILE = "arvore.nwk"
README_FILE = "LEIAME.txt"
ITOL_BRANCH = "#000000"


@dataclass
class TrackBlock:
    """Uma entrada da "Ordem das colunas": suas trilhas e legendas."""

    key: str
    label: str
    tracks: list
    legends: list[LegendGroup] = field(default_factory=list)
    visible: bool = True


@dataclass
class FigureSnapshot:
    """Entradas do último desenho (o que está na tela)."""

    tree: Tree                                   # árvore desenhada (raiz, ordem e poda atuais)
    style: object                                # RenderStyle
    clades: list = field(default_factory=list)   # ResolvedClade
    collapsed: list[Node] = field(default_factory=list)
    blocks: list[TrackBlock] = field(default_factory=list)
    meta_colors: dict[str, str] = field(default_factory=dict)
    groups: dict = field(default_factory=dict)   # folha -> LabelGroup efetivo
    names: dict[str, str] = field(default_factory=dict)
    branch_looks: tuple[dict, dict] | None = None
    ranges: list = field(default_factory=list)   # RangeBackground do iTOL
    marks: list = field(default_factory=list)    # BranchMark do iTOL
    original_lengths: dict[Node, float] = field(default_factory=dict)   # ramos encurtados ("//")
    hidden_count: int = 0
    extras: list[str] = field(default_factory=list)   # sem equivalente, informado pela janela
    tree_name: str = "arvore"


@dataclass
class ExportFile:
    name: str
    kind: str
    text: str
    rows: int
    title: str = ""

    @property
    def count(self) -> str:
        return f"{self.rows} folha(s)" if self.kind == "Newick" else f"{self.rows} linha(s)"


@dataclass
class ExportPlan:
    files: list[ExportFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)   # aproximações e itens sem equivalente
    readme: str = ""

    def summary(self) -> str:
        lines = [f"• {f.name} — {f.kind}" + (f" “{f.title}”" if f.title else "") + f" ({f.count})"
                 for f in self.files]
        return "\n".join(lines)


# ------------------------------------------------------------ utilidades
def node_id(node: Node) -> str:
    """ID do iTOL: o nome da folha, ou "primeira|última" folha do nó interno (MRCA)."""
    if node.is_leaf:
        return node.name
    leaves = node.leaves()
    return f"{leaves[0].name}|{leaves[-1].name}"


def _clean(text: str) -> str:
    """Campo seguro para SEPARATOR TAB (sem tabulação nem quebra de linha)."""
    return re.sub(r"[\t\r\n]+", " ", str(text)).strip()


def _rgba(color: str, alpha: float) -> str:
    if alpha >= 0.999:
        return color
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{round(alpha, 3):g})"


def _num(v: float) -> str:
    """Número sem perder precisão e sem ".0" à toa (10.37 → "10.37", 2.0 → "2")."""
    v = float(v)
    return str(int(v)) if v.is_integer() and abs(v) < 1e15 else f"{v:.12g}"


def _font(bold: bool, italic: bool) -> str:
    return {(False, False): "normal", (True, False): "bold", (False, True): "italic",
            (True, True): "bold-italic"}[(bool(bold), bool(italic))]


def _block_title(b: TrackBlock, legend: LegendGroup | None = None) -> str:
    """Título de um bloco sem o prefixo da "Ordem das colunas" ("iTOL heatmap: X (3 colunas)" → "X")."""
    if legend is not None and legend.title:
        return legend.title
    t = re.sub(r"^[^:]{1,30}:\s*", "", b.label)
    return re.sub(r"\s*\(\d+ colunas?\)$", "", t) or b.label


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")
    return (s or "dataset")[:40]


class _Writer:
    def __init__(self, kind: str, title: str = "", color: str = "#000000") -> None:
        self.kind = kind
        self.title = title
        # o template oficial do COLLAPSE não tem SEPARATOR (só IDs, um por linha)
        self.lines = [kind] if kind == "COLLAPSE" else [kind, "SEPARATOR TAB"]
        if kind.startswith("DATASET_"):
            self.option("DATASET_LABEL", title or kind)
            self.option("COLOR", color)
        self.data: list[str] = []

    def option(self, name: str, *values) -> None:  # type: ignore[no-untyped-def]
        self.lines.append("\t".join([name, *(_clean(v) for v in values)]))

    def legend(self, title: str, entries: list[tuple[str, str | None]],
               shapes: list[tuple[int, bool] | None] | None = None) -> None:
        shapes = list(shapes or [])
        rows = [(l, c, shapes[i] if i < len(shapes) and shapes[i] else (1, True))
                for i, (l, c) in enumerate(entries) if c]
        if not rows:
            return
        self.option("LEGEND_TITLE", title)
        self.option("LEGEND_SHAPES", *[str(sh[0]) for _l, _c, sh in rows])
        self.option("LEGEND_COLORS", *[c for _l, c, _sh in rows])
        self.option("LEGEND_LABELS", *[l for l, _c, _sh in rows])
        if any(not sh[1] for _l, _c, sh in rows):
            self.option("LEGEND_SHAPE_INVERT", *["0" if sh[1] else "1" for _l, _c, sh in rows])

    def row(self, *fields) -> None:  # type: ignore[no-untyped-def]
        out = [_clean(f) for f in fields]
        while len(out) > 1 and out[-1] == "":           # campos opcionais vazios no fim
            out.pop()
        self.data.append("\t".join(out))

    def text(self) -> str:
        head = [f"# Gerado pelo Jabuti {__version__} — formato {self.kind} (iTOL)"]
        return "\n".join(head + self.lines + ["DATA"] + self.data) + "\n"


# ------------------------------------------------------------ montagem
class _Planner:
    def __init__(self, snap: FigureSnapshot) -> None:
        self.s = snap
        self.style = snap.style
        self.plan = ExportPlan()
        self.rules = ColorRules(snap.tree, snap.style, snap.clades, snap.meta_colors, snap.branch_looks,
                                snap.groups)
        self.leaves = snap.tree.leaves()
        self.shown = {l.name for l in self.leaves}
        self.used: set[str] = set()

    def warn(self, msg: str) -> None:
        if msg not in self.plan.warnings:
            self.plan.warnings.append(msg)

    def add(self, stem: str, w: _Writer) -> None:
        if not w.data:
            return
        n = len(self.plan.files)
        name = f"{n:02d}_{_slug(stem)}.txt"
        while name in self.used:
            name = name[:-4] + "_.txt"
        self.used.add(name)
        self.plan.files.append(ExportFile(name, w.kind, w.text(), len(w.data), w.title))

    # -- árvore
    def tree(self) -> None:
        text = write_newick(self.s.tree, self.s.original_lengths)
        self.plan.files.append(ExportFile(TREE_FILE, "Newick", text, len(self.leaves), self.s.tree_name))
        if self.s.original_lengths:
            self.warn(f"{len(self.s.original_lengths)} ramo(s) encurtado(s) (“//”) saem com o comprimento "
                      "original: o iTOL não tem a marca de ramo encurtado")
        if self.s.hidden_count:
            self.warn(f"{self.s.hidden_count} folha(s) oculta(s) foram removidas da árvore exportada")

    # -- cores de ramos, rótulos e faixas
    def tree_colors(self) -> None:
        w = _Writer("TREE_COLORS")
        cs = self.style.clades
        if cs.background:
            for rc in self.s.clades:
                if rc.valid and rc.clade.visible and rc.node is not None:
                    w.row(node_id(rc.node), "range", _rgba(rc.color, max(cs.background_alpha, 0.05)),
                          rc.clade.name)
        for r in self.s.ranges:
            if r.node is not None:
                w.row(node_id(r.node), "range", _rgba(r.color, r.alpha), r.label or "faixa")
        self._branches(w)
        for leaf in self.leaves:
            p = self.rules.label_paint(leaf)
            w.row(leaf.name, "label", p.color)
            if p.background:
                w.row(leaf.name, "label_background", _rgba(p.background, p.background_alpha))
        self.add("tree_colors", w)

    def _pen(self, node: Node, connector: bool) -> tuple[str, float, bool]:
        color, width, dashed = self.rules.node_pen(node) if connector else self.rules.edge_pen(node)
        base = self.rules.width(node) or 1.0
        return color, round(width / base, 3), dashed

    def _branches(self, w: _Writer) -> None:
        """Ramos com cor/estilo diferente do padrão, simulando a leitura do iTOL/Jabuti:
        ``clade`` vale para o ramo até o nó e tudo abaixo; ``branch`` só para o ramo do nó.
        Em pré-ordem, um ``clade`` é emitido quando o conector muda, e ``branch`` corrige o
        que ficar diferente — o resultado relido é igual ao desenhado."""
        default = (self.style.branch.color, 1.0, False)
        stack: list[tuple[Node, tuple]] = [(self.s.tree.root, default)]
        while stack:
            node, inherited = stack.pop()
            here = inherited
            if not node.is_leaf:
                conn = self._pen(node, True)
                if conn != inherited:
                    w.row(node_id(node), "clade", conn[0], "dashed" if conn[2] else "normal", _num(conn[1]))
                    here = conn
            if node is not self.s.tree.root:
                edge = self._pen(node, False)
                if edge != here:
                    w.row(node_id(node), "branch", edge[0], "dashed" if edge[2] else "normal", _num(edge[1]))
            stack.extend((c, here) for c in reversed(node.children))

    def styles(self) -> None:
        """Estilo de fonte e tamanho dos rótulos (o iTOL usa fonte normal e fator 1)."""
        w = _Writer("DATASET_STYLE", "Estilo dos rótulos")
        for leaf in self.leaves:
            p = self.rules.label_paint(leaf)
            if p.bold or p.italic or abs(p.size_scale - 1.0) > 1e-6:
                bg = _rgba(p.background, p.background_alpha) if p.background else ""
                w.row(leaf.name, "label", "node", p.color, _num(p.size_scale), _font(p.bold, p.italic), bg)
        self.add("estilo_rotulos", w)

    def labels(self) -> None:
        w = _Writer("LABELS")
        for leaf in self.leaves:
            shown = self.s.names.get(leaf.name, leaf.name)
            if shown != leaf.name:
                w.row(leaf.name, shown)
        self.add("labels", w)

    # -- colunas
    def columns(self) -> None:
        for b in self.s.blocks:
            if not b.visible:
                continue
            legend = b.legends[0] if b.legends else None
            if b.tracks == [CLADE_STRIP]:
                self._clade_strip(b)
                continue
            leaf_cols = [t for t in b.tracks if isinstance(t, LeafColumn)]
            for t in b.tracks:
                if isinstance(t, BarTrack):
                    self._bar(t)
                elif isinstance(t, StackedTrack):
                    self._stacked(t, b)
            if not leaf_cols:
                continue
            kinds = {c.kind for c in leaf_cols}
            if kinds == {"matrix"}:
                self._heatmap(b, leaf_cols, legend)
            elif kinds == {"genes"}:
                self._genes(b, leaf_cols, legend)
            elif kinds == {"binary"}:
                if any(c.shape_colors or c.shape_sizes for c in leaf_cols):
                    self._symbols(b, leaf_cols, legend)
                else:
                    self._binary(b, leaf_cols, legend)
            else:
                for c in leaf_cols:
                    if c.kind == "metadata":
                        self._strip(c, legend, b.label)
                    elif c.kind == "text":
                        self._texts(c)
                    else:
                        self.warn(f"coluna “{c.header}” ({c.kind}) sem equivalente no iTOL")

    def _strip(self, col: LeafColumn, legend: LegendGroup | None, label: str) -> None:
        title = col.header
        w = _Writer("DATASET_COLORSTRIP", title, next(iter(col.colors.values()), "#000000"))
        if col.width:
            w.option("STRIP_WIDTH", _num(col.width))
        if col.margin:
            w.option("MARGIN", _num(col.margin))
        names = {}
        if legend is not None and legend.kind == "swatches":
            names = {c: l for l, c in legend.entries if c}
            w.legend(legend.title or title, legend.entries, legend.shapes)
        if col.texts:
            w.option("SHOW_STRIP_LABELS", "1")
        for leaf in self.leaves:
            if leaf.name in col.colors:
                c = col.colors[leaf.name]
                w.row(leaf.name, c, col.texts.get(leaf.name) or names.get(c, ""))
        if legend is not None and legend.kind == "colorbar":
            self.warn(f"faixa “{title}”: escala contínua vira cores por folha (o iTOL não desenha a barra de cor)")
        self.add(f"faixa_{title}", w)

    def _clade_strip(self, b: TrackBlock) -> None:
        colors: dict[str, str] = {}
        entries = []
        for rc in self.s.clades:
            if rc.valid and rc.clade.visible and rc.node is not None:
                entries.append((rc.clade.name, rc.color))
                for l in rc.node.leaves():
                    colors[l.name] = self.rules.clade_of(l).color if self.rules.clade_of(l) else rc.color
        w = _Writer("DATASET_COLORSTRIP", "Faixa de clados", entries[0][1] if entries else "#000000")
        w.option("STRIP_WIDTH", _num(self.style.clades.strip_width))
        w.legend("Clados", entries)
        names = {c: n for n, c in entries}
        for leaf in self.leaves:
            if leaf.name in colors:
                w.row(leaf.name, colors[leaf.name], names.get(colors[leaf.name], ""))
        self.add("faixa_clados", w)

    def _bar(self, t: BarTrack) -> None:
        w = _Writer("DATASET_SIMPLEBAR", t.header, t.color)
        w.option("WIDTH", _num(t.width))
        if t.margin:
            w.option("MARGIN", _num(t.margin))
        if t.refs:
            w.option("DATASET_SCALE", *[_num(r) for r in t.refs])
        if t.show_values:
            w.option("SHOW_VALUE", "1")
        if t.log:
            w.option("LOG_SCALE", "1")
        if t.color_mode != "single":
            self.warn(f"barras “{t.header}”: cor por clado/metadado vira uma cor única (o SIMPLEBAR do iTOL "
                      "tem uma só cor)")
        if t.vmin != 0 and not t.log:
            self.warn(f"barras “{t.header}”: o mínimo {fmt_value(t.vmin)} não é exportado (o iTOL parte do 0)")
        for leaf in self.leaves:
            if leaf.name in t.values:
                w.row(leaf.name, _num(t.values[leaf.name]))
        self.add(f"barras_{t.header}", w)

    def _stacked(self, t: StackedTrack, b: TrackBlock) -> None:
        w = _Writer("DATASET_MULTIBAR", t.header, t.colors[0] if t.colors else "#000000")
        w.option("FIELD_COLORS", *t.colors)
        w.option("FIELD_LABELS", *t.series)
        w.option("WIDTH", _num(t.width))
        if t.margin:
            w.option("MARGIN", _num(t.margin))
        w.legend(b.legends[0].title if b.legends else t.header, list(zip(t.series, t.colors)))
        missing = False
        for leaf in self.leaves:
            vals = t.values.get(leaf.name)
            if vals is None or all(v is None for v in vals):
                continue
            missing |= any(v is None for v in vals)
            w.row(leaf.name, *[_num(v) if v is not None else "0" for v in vals])
        if missing:
            self.warn(f"empilhadas “{t.header}”: séries sem dado saem como 0")
        self.add(f"empilhadas_{t.header}", w)

    def _heatmap(self, b: TrackBlock, cols: list[LeafColumn], legend: LegendGroup | None) -> None:
        ramp = next((c.ramp for c in cols if c.ramp is not None), None)
        title = _block_title(b, legend)
        if ramp is None or not any(c.values for c in cols):
            self.warn(f"heatmap “{title}”: sem valores numéricos, não exportado")
            return
        w = _Writer("DATASET_HEATMAP", title, ramp.cmax)
        w.option("FIELD_LABELS", *[c.header for c in cols])
        w.option("COLOR_MIN", ramp.cmin)
        w.option("COLOR_MAX", ramp.cmax)
        if ramp.cmid is not None:
            w.option("USE_MID_COLOR", "1")
            w.option("COLOR_MID", ramp.cmid)
            w.option("USER_MID_VALUE", _num(ramp.vmid if ramp.vmid is not None else (ramp.vmin + ramp.vmax) / 2))
        w.option("COLOR_NAN", cols[0].missing_color)
        w.option("USER_MIN_VALUE", _num(ramp.vmin))
        w.option("USER_MAX_VALUE", _num(ramp.vmax))
        if cols[0].width:
            w.option("STRIP_WIDTH", _num(cols[0].width))
        if cols[0].margin:
            w.option("MARGIN", _num(cols[0].margin))
        if any(c.texts for c in cols):
            w.option("SHOW_VALUES", "1")
        if not ramp.exact:
            self.warn(f"heatmap “{title}”: mapa de cores aproximado por 3 cores (mín/meio/máx, escala linear)")
        for leaf in self.leaves:
            vals = [c.values.get(leaf.name) for c in cols]
            if all(v is None for v in vals):
                continue
            w.row(leaf.name, *[_num(v) if v is not None else "X" for v in vals])
        self.add(f"heatmap_{title}", w)

    def _genes(self, b: TrackBlock, cols: list[LeafColumn], legend: LegendGroup | None) -> None:
        present = legend.entries[0][1] if legend is not None and legend.entries else "#2b6cb0"
        title = legend.title if legend is not None else "Heatmap de genes"
        w = _Writer("DATASET_BINARY", title, present)
        w.option("FIELD_SHAPES", *["1"] * len(cols))
        w.option("FIELD_COLORS", *[present] * len(cols))
        w.option("FIELD_LABELS", *[c.header for c in cols])
        for leaf in self.leaves:
            vals = [c.values.get(leaf.name) for c in cols]
            if all(v is None for v in vals):
                continue
            w.row(leaf.name, *["-1" if v is None else ("1" if v > 0 else "0") for v in vals])
        self.warn("heatmap de genes: vira presença/ausência (quadrado cheio/vazado); o nº de cópias e a cor de "
                  "“ausente” não vão")
        self.add(f"genes_{title}", w)

    def _binary(self, b: TrackBlock, cols: list[LeafColumn], legend: LegendGroup | None) -> None:
        title = _block_title(b, legend)
        w = _Writer("DATASET_BINARY", title, cols[0].shape_color)
        w.option("FIELD_SHAPES", *[str(next(iter(c.shapes.values()), (1, True))[0]) for c in cols])
        w.option("FIELD_COLORS", *[c.shape_color for c in cols])
        w.option("FIELD_LABELS", *[c.header for c in cols])
        if cols[0].margin:
            w.option("MARGIN", _num(cols[0].margin))
        if legend is not None:
            w.legend(legend.title, legend.entries, legend.shapes)
        for leaf in self.leaves:
            cells = [c.shapes.get(leaf.name) for c in cols]
            if all(x is None for x in cells):
                continue
            w.row(leaf.name, *["-1" if x is None else ("1" if x[1] else "0") for x in cells])
        self.add(f"binario_{title}", w)

    def _symbols(self, b: TrackBlock, cols: list[LeafColumn], legend: LegendGroup | None) -> None:
        title = cols[0].header if len(cols) == 1 else re.sub(r"\s+\d+$", "", cols[0].header)
        w = _Writer("DATASET_SYMBOL", title, cols[0].shape_color)
        w.option("MAXIMUM_SIZE", "50")
        if cols[0].margin:
            w.option("MARGIN", _num(cols[0].margin))
        if legend is not None:
            w.legend(legend.title, legend.entries, legend.shapes)
        for k, c in enumerate(cols, start=1):
            for leaf in self.leaves:
                if leaf.name in c.shapes:
                    shape, filled = c.shapes[leaf.name]
                    size = c.shape_sizes.get(leaf.name, 1.0) * 50
                    w.row(leaf.name, str(shape), _num(round(size, 3)), c.shape_colors.get(leaf.name, c.shape_color),
                          "1" if filled else "0", str(-k))
        self.add(f"simbolos_{title}", w)

    def _texts(self, c: LeafColumn) -> None:
        w = _Writer("DATASET_TEXT", c.header, next(iter(c.text_colors.values()), "#000000"))
        if c.margin:
            w.option("MARGIN", _num(c.margin))
        for leaf in self.leaves:
            if leaf.name in c.texts:
                bold, italic, size = c.text_styles.get(leaf.name, (False, False, 1.0))
                w.row(leaf.name, c.texts[leaf.name], "-1", c.text_colors.get(leaf.name, "#000000"),
                      _font(bold, italic), _num(size), "0")
        self.add(f"texto_{c.header}", w)

    def marks(self) -> None:
        sym = _Writer("DATASET_SYMBOL", "Símbolos nos ramos")
        sym.option("MAXIMUM_SIZE", "50")
        txt = _Writer("DATASET_TEXT", "Textos nos ramos")
        for m in self.s.marks:
            if m.kind == "symbol":
                sym.row(node_id(m.node), str(m.shape), _num(round(m.size * 50, 3)), m.color,
                        "1" if m.filled else "0", _num(m.frac))
            else:
                txt.row(node_id(m.node), m.text, _num(m.frac), m.color, _font(m.bold, m.italic), _num(m.size),
                        _num(m.rotation))
        self.add("simbolos_ramos", sym)
        self.add("textos_ramos", txt)

    def collapse(self) -> None:
        w = _Writer("COLLAPSE")
        for n in self.s.collapsed:
            if not n.is_leaf:
                w.row(node_id(n))
        self.add("colapsos", w)

    def run(self) -> ExportPlan:
        self.tree()
        self.tree_colors()
        self.styles()
        self.labels()
        self.columns()
        self.marks()
        self.collapse()
        for e in self.s.extras:
            self.warn(e)
        self.plan.readme = self.readme()
        return self.plan

    def readme(self) -> str:
        lines = [f"Exportado pelo Jabuti {__version__} para o iTOL (https://itol.embl.de)", "",
                 "COMO USAR", "  1. No iTOL, envie a árvore (Upload) escolhendo o arquivo "
                 f"{TREE_FILE}.", "  2. Com a árvore aberta, arraste os demais arquivos .txt sobre ela "
                 "(todos de uma vez).", "",
                 "ARQUIVOS"]
        lines += [f"  {f.name:<34} {f.kind}" + (f" — {f.title}" if f.title else "") + f" ({f.count})"
                  for f in self.plan.files]
        lines += ["", "O QUE NÃO FOI EXPORTADO (o iTOL escolhe no próprio site)",
                  "  - layout (retangular, circular, leque, não enraizada), ângulos e rotação;",
                  "  - fonte, tamanho e espaçamento dos rótulos; espessura base dos ramos;",
                  "  - legenda da figura e sua posição, barra de escala, títulos das colunas no desenho;",
                  "  - linhas-guia, símbolos nas pontas e números de suporte (o suporte está no Newick);",
                  "  - folhas ocultas (removidas da árvore) e a marca “//” de ramo encurtado."]
        if self.plan.warnings:
            lines += ["", "AVISOS E APROXIMAÇÕES"] + [f"  - {w}" for w in self.plan.warnings]
        return "\n".join(lines) + "\n"


def plan_export(snap: FigureSnapshot) -> ExportPlan:
    return _Planner(snap).run()


def write_export(plan: ExportPlan, dest: str | Path, as_zip: bool = False) -> Path:
    """Grava a pasta (criada se preciso) ou o .zip com a árvore, os datasets e o LEIAME."""
    dest = Path(dest)
    files = [(f.name, f.text) for f in plan.files] + [(README_FILE, plan.readme)]
    if as_zip:
        if dest.suffix.lower() != ".zip":
            dest = dest.with_suffix(".zip")
        dest.parent.mkdir(parents=True, exist_ok=True)
        folder = dest.stem
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for name, text in files:
                z.writestr(f"{folder}/{name}", text.encode("utf-8"))
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    for name, text in files:
        (dest / name).write_text(text, encoding="utf-8")
    return dest
