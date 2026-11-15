"""Converte datasets do iTOL em objetos do Jabuti (sem Qt), a cada desenho.

Os IDs são resolvidos na árvore desenhada (já reenraizada/podada), então ``A|B`` acompanha
reenraizamento e ladderize. Nada é copiado para o estado do usuário: desligar ou remover um
dataset desfaz o efeito.

Tipos desta etapa: ``TREE_COLORS``, ``LABELS``, ``DATASET_COLORSTRIP`` e ``DATASET_STYLE``.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Iterable

from jabuti.models.annotations import LeafColumn, LegendGroup
from jabuti.models.clades import mrca
from jabuti.models.label_groups import LabelGroup, LabelLook
from jabuti.models.tree import Node, Tree
from jabuti.parsers.itol import ItolDataset, parse_color
from jabuti.parsers.names import match_names

_SPLIT = re.compile(r"\||---")
BAR_COLOR = "#4e79a7"
HEATMAP_DEFAULTS = {"COLOR_MIN": "#ff0000", "COLOR_MID": "#ffffff", "COLOR_MAX": "#0000ff", "COLOR_NAN": "#d9d9d9"}
MAX_WIDTH = 600.0                  # largura máxima de uma coluna de barras (px)
CONTAINS = "CONTAINS=="


@dataclass
class BranchLook:
    color: str | None = None
    width_factor: float = 1.0
    dashed: bool = False


@dataclass
class RangeBackground:
    """Faixa de fundo atrás de um clado (``range`` do TREE_COLORS)."""

    node: Node | None
    color: str
    alpha: float = 1.0
    label: str = ""


@dataclass
class BranchMark:
    """Símbolo ou texto do iTOL sobre o ramo que chega a ``node`` (``frac`` 0 = pai, 1 = nó)."""

    node: Node
    frac: float
    kind: str = "symbol"           # "symbol" | "text"
    shape: int = 1
    filled: bool = True
    color: str = "#000000"
    size: float = 1.0              # símbolo: relativo ao MAXIMUM_SIZE; texto: fator do tamanho dos rótulos
    text: str = ""
    bold: bool = False
    italic: bool = False
    rotation: float = 0.0


@dataclass
class ItolStats:
    applied: int = 0
    ignored: int = 0
    tolerant: int = 0              # IDs casados pelo modo tolerante (não exatos)
    problems: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class ItolColumn:
    key: str
    label: str                     # nome na lista "Ordem das colunas"
    tracks: list                   # LeafColumn, BarTrack ou StackedTrack (uma ou mais colunas)
    legend: LegendGroup | None

    @property
    def column(self):  # type: ignore[no-untyped-def]
        return self.tracks[0]


@dataclass
class ItolEffects:
    edge_looks: dict[Node, BranchLook] = field(default_factory=dict)
    node_looks: dict[Node, BranchLook] = field(default_factory=dict)
    ranges: list[RangeBackground] = field(default_factory=list)
    label_groups: list[LabelGroup] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    columns: list[ItolColumn] = field(default_factory=list)
    legends: list[LegendGroup] = field(default_factory=list)
    marks: list[BranchMark] = field(default_factory=list)
    stats: dict[str, ItolStats] = field(default_factory=dict)

    @property
    def branch_looks(self) -> tuple[dict, dict] | None:
        return (self.edge_looks, self.node_looks) if self.edge_looks or self.node_looks else None


@dataclass
class ItolEntry:
    """Dataset carregado + preferências editáveis (cores, título, visível)."""

    key: str
    dataset: ItolDataset
    visible: bool = True
    title: str = ""                                         # "" = DATASET_LABEL / nome do arquivo
    colors: dict[str, str] = field(default_factory=dict)    # cor original -> cor nova
    labels: dict[str, str] = field(default_factory=dict)    # cor original -> rótulo da legenda
    collapsed_sets: list[frozenset[str]] = field(default_factory=list)   # COLLAPSE já aplicados

    @property
    def name(self) -> str:
        return self.title or self.dataset.label

    def color(self, hexcolor: str) -> str:
        return self.colors.get(hexcolor, hexcolor)


# --------------------------------------------------------------- resolução de IDs
def _parts(ident: str) -> list[str]:
    if ident.startswith(CONTAINS):
        return []
    return [p.strip() for p in _SPLIT.split(ident) if p.strip()]


class Resolver:
    """IDs do iTOL → nós da árvore desenhada."""

    def __init__(self, tree: Tree, ids: Iterable[str], hidden: Iterable[str] = ()) -> None:
        self.tree = tree
        self.leaf = {n.name: n for n in tree.leaves()}
        self.internal = {n.name: n for n in tree.root.traverse_preorder() if not n.is_leaf and n.name}
        self.hidden = set(hidden)
        unknown = sorted({p for i in ids for p in _parts(i)
                          if p not in self.leaf and p not in self.internal and p not in self.hidden})
        self.tolerant = {k: v for k, v in match_names(unknown, list(self.leaf)).items() if k != v} if unknown else {}

    def resolve(self, ident: str) -> tuple[list[Node], bool, str | None]:
        """(nós, casou pelo modo tolerante?, motivo se não achou)."""
        ident = ident.strip()
        if not ident:
            return [], False, "ID vazio"
        if ident.startswith(CONTAINS):
            text = ident[len(CONTAINS):]
            found = [n for name, n in self.leaf.items() if text and text in name]
            return found, False, None if found else f"nenhuma folha contém “{text}”"
        parts = _parts(ident)
        if len(parts) == 1:
            p = parts[0]
            if p in self.leaf:
                return [self.leaf[p]], False, None
            if p in self.internal:
                return [self.internal[p]], False, None
            if p in self.tolerant:
                return [self.leaf[self.tolerant[p]]], True, None
            if p in self.hidden:
                return [], False, f"folha oculta: {p}"
            return [], False, f"folha não encontrada na árvore: {p}"
        nodes, tolerant, missing = [], False, []
        for p in parts:
            if p in self.leaf:
                nodes.append(self.leaf[p])
            elif p in self.tolerant:
                nodes.append(self.leaf[self.tolerant[p]])
                tolerant = True
            elif p in self.hidden:
                continue                 # folha oculta: o ancestral comum das demais
            else:
                missing.append(p)
        if missing:
            return [], False, f"folha(s) não encontrada(s) na árvore: {', '.join(missing)}"
        if not nodes:
            return [], False, "todas as folhas do ID estão ocultas"
        node = mrca(self.tree, frozenset(n.name for n in nodes))
        return ([node] if node is not None else []), tolerant, None


def _leaf_names(node: Node) -> list[str]:
    return [node.name] if node.is_leaf else [l.name for l in node.leaves()]


def _subtree(node: Node) -> list[Node]:
    return list(node.traverse_preorder())


def _tail(entry: ItolEntry, fields: list[str], i: int) -> str:
    """Último campo de texto. Com SEPARATOR SPACE, campos a mais são juntados nele (texto com
    espaços sem aspas)."""
    if i >= len(fields):
        return ""
    if entry.dataset.separator == "SPACE":
        return " ".join(fields[i:]).strip()
    return fields[i].strip()


def _float(text: str | None, default: float = 1.0) -> float:
    try:
        v = float(text)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


def _label_style(text: str) -> tuple[bool, bool] | None:
    t = (text or "").strip().lower().replace("_", "-")
    return {"normal": (False, False), "bold": (True, False), "italic": (False, True),
            "bold-italic": (True, True)}.get(t)


def _merge_look(base: LabelLook | None, new: LabelLook) -> LabelLook:
    if base is None:
        return new
    out = LabelLook(**base.to_dict())
    for k, v in new.to_dict().items():
        if k in ("text_color", "background", "bold", "italic") and v is not None:
            setattr(out, k, v)
    if new.background is not None:
        out.background_alpha = new.background_alpha
    if new.size_scale != 1.0:
        out.size_scale = new.size_scale
    return out


def dataset_entries(ds: ItolDataset) -> list[tuple[str, str]]:
    """Cores do dataset (cor original, rótulo) para o editor de cores/legenda, na ordem."""
    out: dict[str, str] = {}

    def add(color_text: str, label: str = "") -> None:
        c = parse_color(color_text)
        if c is not None and (c[0] not in out or (label and not out[c[0]])):
            out[c[0]] = label

    if ds.kind == "DATASET_COLORSTRIP":
        for c, l in zip(ds.options.get("LEGEND_COLORS", []), ds.options.get("LEGEND_LABELS", [])):
            add(c, l)
        for r in ds.rows:
            if len(r.fields) >= 2:
                add(r.fields[1], r.fields[2] if len(r.fields) > 2 else "")
    elif ds.kind == "TREE_COLORS":
        for r in ds.rows:
            if len(r.fields) >= 3:
                kind = r.fields[1].strip().lower()
                add(r.fields[2], r.fields[3] if kind == "range" and len(r.fields) > 3 else "")
    elif ds.kind == "DATASET_SIMPLEBAR":
        add(ds.option("COLOR") or BAR_COLOR)
    elif ds.kind in ("DATASET_MULTIBAR", "DATASET_BINARY"):
        labels = ds.options.get("FIELD_LABELS", [])
        colors = ds.options.get("FIELD_COLORS") or [ds.option("COLOR") or "#000000"] * max(len(labels), 1)
        for i, c in enumerate(colors):
            add(c, labels[i] if i < len(labels) else "")
    elif ds.kind == "DATASET_HEATMAP":
        for opt, name in (("COLOR_MIN", "mínimo"), ("COLOR_MID", "meio"), ("COLOR_MAX", "máximo"),
                          ("COLOR_NAN", "sem dado")):
            if opt == "COLOR_MID" and not ds.flag("USE_MID_COLOR"):
                continue
            add(ds.option(opt) or HEATMAP_DEFAULTS[opt], name)
    elif ds.kind == "DATASET_SYMBOL":
        for c, l in zip(ds.options.get("LEGEND_COLORS", []), ds.options.get("LEGEND_LABELS", [])):
            add(c, l)
        for r in ds.rows:
            if len(r.fields) >= 4:
                add(r.fields[3])
    elif ds.kind == "DATASET_TEXT":
        for r in ds.rows:
            if len(r.fields) >= 4:
                add(r.fields[3])
    elif ds.kind == "DATASET_STYLE":
        for r in ds.rows:
            if len(r.fields) >= 4:
                add(r.fields[3])
            if len(r.fields) >= 7:
                add(r.fields[6])
    return list(out.items())


# --------------------------------------------------------------- aplicação
class _Builder:
    def __init__(self, tree: Tree, hidden: Iterable[str], missing_color: str) -> None:
        self.tree = tree
        self.hidden = set(hidden)
        self.missing_color = missing_color
        self.fx = ItolEffects()
        self.looks: dict[str, LabelLook] = {}         # folha -> estilo de rótulo combinado
        self.look_owner: dict[str, str] = {}          # folha -> nome do dataset (nome do grupo)

    # -- estilos de ramo
    def branch(self, node: Node, look: BranchLook, clade: bool) -> None:
        """``clade``: o ramo até o nó e tudo abaixo; senão só o ramo que termina no nó."""
        for n in (_subtree(node) if clade else [node]):
            self.fx.edge_looks[n] = look
            if clade and not n.is_leaf:
                self.fx.node_looks[n] = look

    def label_look(self, node: Node, look: LabelLook, owner: str) -> None:
        for name in _leaf_names(node):
            self.looks[name] = _merge_look(self.looks.get(name), look)
            self.look_owner[name] = owner

    def finish(self) -> ItolEffects:
        by_look: dict[tuple, list[str]] = {}
        looks: dict[tuple, LabelLook] = {}
        owners: dict[tuple, str] = {}
        for leaf, look in self.looks.items():
            k = tuple(look.to_dict().items())
            by_look.setdefault(k, []).append(leaf)
            looks[k] = look
            owners.setdefault(k, self.look_owner[leaf])
        for i, (k, leaves) in enumerate(by_look.items()):
            self.fx.label_groups.append(LabelGroup(f"iTOL: {owners[k]} ({i + 1})", frozenset(leaves),
                                                   looks[k], True, "pattern"))
        return self.fx

    # -- tipos
    def run(self, entry: ItolEntry) -> None:
        ds = entry.dataset
        st = ItolStats(problems=list(ds.warnings))
        self.fx.stats[entry.key] = st
        if not ds.supported:
            st.ignored = len(ds.rows)
            return
        resolver = Resolver(self.tree, (r.fields[0] for r in ds.rows if r.fields), self.hidden)
        handler = {"TREE_COLORS": self._tree_colors, "LABELS": self._labels,
                   "DATASET_COLORSTRIP": self._colorstrip, "DATASET_STYLE": self._style,
                   "DATASET_SIMPLEBAR": self._simplebar, "DATASET_MULTIBAR": self._multibar,
                   "DATASET_HEATMAP": self._heatmap, "DATASET_BINARY": self._binary,
                   "DATASET_SYMBOL": self._symbol, "DATASET_TEXT": self._text, "COLLAPSE": self._collapse}[ds.kind]
        handler(entry, resolver, st)

    def _targets(self, row, resolver: Resolver, st: ItolStats, min_fields: int, what: str) -> list[Node]:  # type: ignore[no-untyped-def]
        if len(row.fields) < min_fields:
            st.ignored += 1
            st.problems.append((row.line, f"linha malformada: esperado {what}"))
            return []
        nodes, tolerant, why = resolver.resolve(row.fields[0])
        if not nodes:
            st.ignored += 1
            st.problems.append((row.line, why or "ID não encontrado"))
            return []
        st.tolerant += tolerant
        return nodes

    def _color(self, entry: ItolEntry, text: str, row, st: ItolStats) -> tuple[str, float] | None:  # type: ignore[no-untyped-def]
        c = parse_color(text)
        if c is None:
            st.ignored += 1
            st.problems.append((row.line, f"cor inválida “{text}”"))
            return None
        return entry.color(c[0]), c[1]

    def _tree_colors(self, entry: ItolEntry, resolver: Resolver, st: ItolStats) -> None:
        legend: dict[str, str] = {}
        for row in entry.dataset.rows:
            nodes = self._targets(row, resolver, st, 3, "ID, tipo e cor")
            if not nodes:
                continue
            f = row.fields + [""] * 5
            kind = f[1].strip().lower()
            if kind not in ("range", "clade", "branch", "label", "label_background"):
                st.ignored += 1
                st.problems.append((row.line, f"tipo “{f[1]}” desconhecido (use range, clade, branch, "
                                              "label ou label_background)"))
                continue
            c = self._color(entry, f[2], row, st)
            if c is None:
                continue
            color, alpha = c
            orig = (parse_color(f[2]) or (color, 1.0))[0]
            for node in nodes:
                if kind == "range":
                    label = entry.labels.get(orig, _tail(entry, row.fields, 3))
                    self.fx.ranges.append(RangeBackground(node, color, alpha, label))
                    if label:
                        legend.setdefault(label, color)
                elif kind in ("clade", "branch"):
                    dashed = f[3].strip().lower() == "dashed"
                    self.branch(node, BranchLook(color, _float(f[4]), dashed), kind == "clade")
                elif kind == "label":
                    bi = _label_style(f[3]) or (None, None)
                    self.label_look(node, LabelLook(text_color=color, bold=bi[0], italic=bi[1],
                                                    size_scale=_float(f[4])), entry.name)
                else:
                    self.label_look(node, LabelLook(background=color, background_alpha=alpha), entry.name)
            st.applied += 1
        if legend:
            title = entry.title or entry.dataset.option("DATASET_LABEL") or "Faixas"
            self.fx.legends.append(LegendGroup(title, list(legend.items())))

    def _labels(self, entry: ItolEntry, resolver: Resolver, st: ItolStats) -> None:
        for row in entry.dataset.rows:
            nodes = self._targets(row, resolver, st, 2, "ID e rótulo")
            if not nodes:
                continue
            if not all(n.is_leaf for n in nodes):
                st.ignored += 1
                st.problems.append((row.line, "nome de nó interno: o Jabuti não desenha nomes de nós internos "
                                              "(ignorado)"))
                continue
            for n in nodes:
                self.fx.names[n.name] = _tail(entry, row.fields, 1)
            st.applied += 1

    def _colorstrip(self, entry: ItolEntry, resolver: Resolver, st: ItolStats) -> None:
        ds = entry.dataset
        colors: dict[str, str] = {}
        texts: dict[str, str] = {}
        seen: dict[str, str] = {}               # cor -> rótulo (legenda a partir dos dados)
        for row in ds.rows:
            nodes = self._targets(row, resolver, st, 2, "ID e cor")
            if not nodes:
                continue
            c = self._color(entry, row.fields[1], row, st)
            if c is None:
                continue
            orig = (parse_color(row.fields[1]) or c)[0]
            label = _tail(entry, row.fields, 2)
            for node in nodes:
                for name in _leaf_names(node):
                    colors[name] = c[0]
                    if label:
                        texts[name] = label
            seen.setdefault(c[0], entry.labels.get(orig, label))
            st.applied += 1
        if not colors:
            return
        title = entry.title or ds.option("LEGEND_TITLE") or ds.label
        header = entry.title or ds.label
        width = ds.number("STRIP_WIDTH")
        col = LeafColumn(entry.key, header, colors, self.missing_color,
                         texts if ds.flag("SHOW_STRIP_LABELS") else {}, "metadata",
                         width if width and width > 0 else None)
        legend = None
        lc, ll = ds.options.get("LEGEND_COLORS", []), ds.options.get("LEGEND_LABELS", [])
        if lc and ll:
            entries = []
            for ctext, label in zip(lc, ll):
                pc = parse_color(ctext)
                if pc is None:
                    st.problems.append((0, f"cor inválida na legenda “{ctext}”"))
                    continue
                entries.append((entry.labels.get(pc[0], label), entry.color(pc[0])))
            legend = LegendGroup(title, entries) if entries else None
        elif any(seen.values()):
            legend = LegendGroup(title, [(l, c) for c, l in seen.items() if l])
        self.fx.columns.append(ItolColumn(entry.key, f"iTOL: {header}", [col], legend))
        if ds.flag("COLOR_BRANCHES"):
            self._color_branches(colors)

    def _color_branches(self, leaf_colors: dict[str, str]) -> None:
        """Ramo de cada folha e dos nós cujos descendentes têm todos a mesma cor."""
        node_color: dict[Node, str] = {}
        for node in self.tree.root.traverse_postorder():
            if node.is_leaf:
                if node.name in leaf_colors:
                    node_color[node] = leaf_colors[node.name]
            else:
                kids = [node_color.get(c) for c in node.children]
                if kids and kids[0] is not None and all(k == kids[0] for k in kids):
                    node_color[node] = kids[0]
        for node, color in node_color.items():
            self.fx.edge_looks[node] = BranchLook(color)
            if not node.is_leaf:
                self.fx.node_looks[node] = BranchLook(color)

    def _style(self, entry: ItolEntry, resolver: Resolver, st: ItolStats) -> None:
        for row in entry.dataset.rows:
            nodes = self._targets(row, resolver, st, 4, "ID, tipo, alvo e cor")
            if not nodes:
                continue
            f = row.fields + [""] * 7
            kind, what = f[1].strip().lower(), f[2].strip().lower()
            if kind not in ("branch", "label") or what not in ("node", "clade"):
                st.ignored += 1
                st.problems.append((row.line, f"esperado branch/label e node/clade, recebido “{f[1]}”, “{f[2]}”"))
                continue
            c = self._color(entry, f[3], row, st)
            if c is None:
                continue
            color = c[0]
            ok = True
            for node in nodes:
                if kind == "branch":
                    self.branch(node, BranchLook(color, _float(f[4]), f[5].strip().lower() == "dashed"),
                                what == "clade")
                    continue
                if what == "node" and not node.is_leaf:
                    st.problems.append((row.line, "rótulo de nó interno: o Jabuti não desenha nomes de nós "
                                                  "internos (ignorado)"))
                    ok = False
                    continue
                bi = _label_style(f[5]) or (None, None)
                look = LabelLook(text_color=color, bold=bi[0], italic=bi[1], size_scale=_float(f[4]))
                bg = parse_color(f[6]) if f[6].strip() else None
                if bg is not None:
                    look.background, look.background_alpha = entry.color(bg[0]), bg[1]
                self.label_look(node, look, entry.name)
            if ok:
                st.applied += 1
            else:
                st.ignored += 1

    # -- colunas de dados (etapa 2)
    def _width(self, ds: ItolDataset, name: str, default: float, st: ItolStats) -> float:
        w = ds.number(name)
        if w is None or w <= 0:
            return default
        if w > MAX_WIDTH:
            st.problems.append((0, f"{name} {w:g} reduzido para {MAX_WIDTH:g} px"))
            return MAX_WIDTH
        return w

    def _unsupported_opts(self, ds: ItolDataset, st: ItolStats, names: tuple[str, ...]) -> None:
        for n in names:
            if ds.flag(n):
                st.problems.append((0, f"{n} não é suportado: ignorado"))

    def _numeric_rows(self, entry: ItolEntry, resolver: Resolver, st: ItolStats, n_fields: int | None,
                      allow_missing: bool):  # type: ignore[no-untyped-def]
        """(folhas, valores) por linha; valores None = sem dado (X) quando permitido."""
        out = []
        for row in entry.dataset.rows:
            nodes = self._targets(row, resolver, st, 2, "ID e valor(es)")
            if not nodes:
                continue
            raw = row.fields[1:]
            if n_fields is not None and len(raw) > n_fields:
                st.problems.append((row.line, f"{len(raw)} valores para {n_fields} campos: os de sobra "
                                              "foram ignorados"))
                raw = raw[:n_fields]
            try:
                vals = [_number(v) for v in raw]
            except ValueError as exc:
                st.ignored += 1
                st.problems.append((row.line, f"valor não numérico “{exc}”"))
                continue
            if not allow_missing and any(v is None for v in vals):
                st.ignored += 1
                st.problems.append((row.line, "valor ausente"))
                continue
            if n_fields is not None and len(vals) < n_fields:
                vals += [None] * (n_fields - len(vals))
            names = [n for node in nodes for n in _leaf_names(node)]
            out.append((names, vals))
            st.applied += 1
        return out

    def _simplebar(self, entry: ItolEntry, resolver: Resolver, st: ItolStats) -> None:
        from jabuti.models.tracks import bar_track

        ds = entry.dataset
        self._unsupported_opts(ds, st, ("LOG_SCALE",))
        values: dict[str, float] = {}
        for names, vals in self._numeric_rows(entry, resolver, st, None, False):
            for n in names:
                values[n] = vals[0]
        if not values:
            return
        zero = ds.number("BAR_ZERO", 0.0) or 0.0
        if zero != 0.0:
            st.problems.append((0, f"BAR_ZERO {zero:g}: as barras partem do 0 no Jabuti"))
        color = entry.color((parse_color(ds.option("COLOR") or BAR_COLOR) or (BAR_COLOR, 1.0))[0])
        header = entry.title or ds.label
        track = bar_track(entry.key, header, values, color=color, refs=_scale_values(ds.options.get("DATASET_SCALE", [])),
                          show_values=ds.flag("SHOW_VALUE"), width=self._width(ds, "WIDTH", 80.0, st),
                          missing_color=self.missing_color, margin=max(ds.number("MARGIN", 0.0) or 0.0, 0.0))
        self.fx.columns.append(ItolColumn(entry.key, f"iTOL barras: {header}", [track], None))

    def _field_colors(self, entry: ItolEntry, n: int, st: ItolStats) -> list[str]:
        ds = entry.dataset
        raw = ds.options.get("FIELD_COLORS") or []
        default = ds.option("COLOR") or "#000000"
        out = []
        for i in range(n):
            text = raw[i] if i < len(raw) else default
            c = parse_color(text)
            if c is None:
                st.problems.append((0, f"cor inválida em FIELD_COLORS “{text}”"))
                c = ("#000000", 1.0)
            out.append(entry.color(c[0]))
        return out

    def _field_labels(self, entry: ItolEntry, n: int, colors_orig: list[str]) -> list[str]:
        raw = entry.dataset.options.get("FIELD_LABELS") or []
        out = []
        for i in range(n):
            label = raw[i] if i < len(raw) and raw[i] else f"campo {i + 1}"
            out.append(entry.labels.get(colors_orig[i], label) or label if i < len(colors_orig) else label)
        return out

    def _orig_field_colors(self, ds: ItolDataset, n: int) -> list[str]:
        raw = ds.options.get("FIELD_COLORS") or []
        default = ds.option("COLOR") or "#000000"
        return [(parse_color(raw[i] if i < len(raw) else default) or ("#000000", 1.0))[0] for i in range(n)]

    def _n_fields(self, ds: ItolDataset, st: ItolStats, need: tuple[str, ...]) -> int:
        counts = [len(ds.options.get(o, [])) for o in need if ds.options.get(o)]
        if not counts:
            n = max((len(r.fields) - 1 for r in ds.rows), default=0)
            st.problems.append((0, f"{' e '.join(need)} ausente(s): {n} campo(s) pelos dados"))
            return n
        return max(counts)

    def _multibar(self, entry: ItolEntry, resolver: Resolver, st: ItolStats) -> None:
        from jabuti.models.tracks import stacked_track

        ds = entry.dataset
        self._unsupported_opts(ds, st, ("LOG_SCALE", "SIDE_STACKED", "ALIGN_FIELDS"))
        n = self._n_fields(ds, st, ("FIELD_LABELS", "FIELD_COLORS"))
        if n <= 0:
            return
        orig = self._orig_field_colors(ds, n)
        colors = self._field_colors(entry, n, st)
        labels = self._field_labels(entry, n, orig)
        series = list(labels)
        for i, l in enumerate(series):       # séries com o mesmo nome continuam separadas
            if series.count(l) > 1:
                series[i] = f"{l} ({i + 1})"
        columns: dict[str, dict[str, float]] = {s: {} for s in series}
        for names, vals in self._numeric_rows(entry, resolver, st, n, True):
            for i, v in enumerate(vals):
                if v is not None:
                    for name in names:
                        columns[series[i]][name] = v
        if not any(columns.values()):
            return
        header = entry.title or ds.label
        track = stacked_track(entry.key, header, series, colors, columns, None,
                              width=self._width(ds, "WIDTH", 100.0, st), missing_color=self.missing_color,
                              margin=max(ds.number("MARGIN", 0.0) or 0.0, 0.0))
        self.fx.columns.append(ItolColumn(entry.key, f"iTOL empilhadas: {header}", [track],
                                          LegendGroup(entry.title or ds.option("LEGEND_TITLE") or header,
                                                      list(zip(series, colors)))))

    def _heatmap(self, entry: ItolEntry, resolver: Resolver, st: ItolStats) -> None:
        from jabuti.models.annotations import gradient_color
        from jabuti.models.tracks import fmt_value

        ds = entry.dataset
        n = self._n_fields(ds, st, ("FIELD_LABELS",))
        if n <= 0:
            return
        labels = (ds.options.get("FIELD_LABELS") or []) + [f"campo {i + 1}" for i in range(n)]
        rows = self._numeric_rows(entry, resolver, st, n, True)
        values = [v for _names, vals in rows for v in vals if v is not None]
        if not values:
            return

        def col(opt: str) -> str:
            c = parse_color(ds.option(opt) or HEATMAP_DEFAULTS[opt])
            if c is None:
                st.problems.append((0, f"cor inválida em {opt}"))
                c = (HEATMAP_DEFAULTS[opt], 1.0)
            return entry.color(c[0])

        cmin, cmax, nan = col("COLOR_MIN"), col("COLOR_MAX"), col("COLOR_NAN")
        use_mid = ds.flag("USE_MID_COLOR")
        cmid = col("COLOR_MID") if use_mid else None
        lo = ds.number("USER_MIN_VALUE", min(values))
        hi = ds.number("USER_MAX_VALUE", max(values))
        if hi <= lo:
            hi = lo + 1.0
        mid = ds.number("USER_MID_VALUE", (lo + hi) / 2)
        mid = min(max(mid, lo), hi)

        def color(v: float) -> str:
            v = min(max(v, lo), hi)
            if cmid is None:
                return gradient_color((v - lo) / (hi - lo), [cmin, cmax])
            if v <= mid:
                return gradient_color((v - lo) / (mid - lo) if mid > lo else 1.0, [cmin, cmid])
            return gradient_color((v - mid) / (hi - mid) if hi > mid else 0.0, [cmid, cmax])

        cell = ds.number("STRIP_WIDTH")
        cell = cell if cell and cell > 0 else None
        tracks = []
        for i in range(n):
            colors = {}
            texts = {}
            for names, vals in rows:
                if vals[i] is not None:
                    for name in names:
                        colors[name] = color(vals[i])
                        texts[name] = fmt_value(vals[i])
            tracks.append(LeafColumn(f"{entry.key}:{i}", labels[i], colors, nan,
                                     texts if ds.flag("SHOW_VALUES") else {}, "matrix", cell,
                                     margin=max(ds.number("MARGIN", 0.0) or 0.0, 0.0) if i == 0 else 0.0))
        k = 21                                           # paradas amostradas (meio fora do centro)
        stops = [color(lo + (hi - lo) * j / (k - 1)) for j in range(k)]
        ticks = [(0.0, fmt_value(round(lo, 3))), (1.0, fmt_value(round(hi, 3)))]
        fmid = (mid - lo) / (hi - lo)
        if cmid is not None and 0.25 <= fmid <= 0.75:      # perto das pontas o rótulo encostaria
            ticks.insert(1, (fmid, fmt_value(round(mid, 3))))
        title = entry.title or ds.option("LEGEND_TITLE") or ds.label
        legend = LegendGroup(title, [("sem dado", nan)], "colorbar", stops, ticks)
        self.fx.columns.append(ItolColumn(entry.key, f"iTOL heatmap: {entry.title or ds.label} ({n} colunas)",
                                          tracks, legend))

    def _binary(self, entry: ItolEntry, resolver: Resolver, st: ItolStats) -> None:
        ds = entry.dataset
        n = self._n_fields(ds, st, ("FIELD_SHAPES", "FIELD_LABELS"))
        if n <= 0:
            return
        shapes_raw = ds.options.get("FIELD_SHAPES") or []
        shapes = []
        for i in range(n):
            try:
                sh = int(shapes_raw[i]) if i < len(shapes_raw) else 1
            except ValueError:
                st.problems.append((0, f"forma inválida em FIELD_SHAPES “{shapes_raw[i]}” (usando quadrado)"))
                sh = 1
            if not 1 <= sh <= 6:
                st.problems.append((0, f"forma {sh} desconhecida (use 1–6): usando quadrado"))
                sh = 1
            shapes.append(sh)
        orig = self._orig_field_colors(ds, n)
        colors = self._field_colors(entry, n, st)
        labels = self._field_labels(entry, n, orig)
        cells: list[dict[str, tuple[int, bool]]] = [{} for _ in range(n)]
        for names, vals in self._numeric_rows(entry, resolver, st, n, True):
            for i, v in enumerate(vals):
                if v is None or v == -1:
                    continue                            # -1 / ausente = sem dado (nada desenhado)
                if v not in (0, 1):
                    st.problems.append((0, f"valor {v:g} em DATASET_BINARY (use 1, 0 ou -1): ignorado"))
                    continue
                for name in names:
                    cells[i][name] = (shapes[i], v == 1)
        if not any(cells):
            return
        margin = max(ds.number("MARGIN", 0.0) or 0.0, 0.0)
        tracks = [LeafColumn(f"{entry.key}:{i}", labels[i], {}, self.missing_color, {}, "binary", None,
                             margin=margin if i == 0 else 0.0, shapes=cells[i], shape_color=colors[i])
                  for i in range(n)]
        title = entry.title or ds.option("LEGEND_TITLE") or ds.label
        legend = LegendGroup(title, list(zip(labels, colors)))
        self.fx.columns.append(ItolColumn(entry.key, f"iTOL presença: {entry.title or ds.label} ({n} colunas)",
                                          tracks, legend))

    # -- extras (etapa 3)
    def _symbol(self, entry: ItolEntry, resolver: Resolver, st: ItolStats) -> None:
        ds = entry.dataset
        max_size = ds.number("MAXIMUM_SIZE", 50.0) or 50.0
        columns: dict[int, dict[str, dict]] = {}
        for row in ds.rows:
            nodes = self._targets(row, resolver, st, 6, "ID, símbolo, tamanho, cor, preenchido e posição")
            if not nodes:
                continue
            f = row.fields
            try:
                shape, size, pos = int(float(f[1])), float(f[2]), float(f[5])
            except ValueError:
                st.ignored += 1
                st.problems.append((row.line, "símbolo, tamanho ou posição não numérico"))
                continue
            if not 1 <= shape <= 12:
                st.problems.append((row.line, f"símbolo {shape} desconhecido (use 1–12): usando quadrado"))
                shape = 1
            c = self._color(entry, f[3], row, st)
            if c is None:
                continue
            filled = f[4].strip() != "0"
            rel = max(size, 0.0) / max_size if max_size > 0 else 1.0
            if pos < 0:
                k = max(int(round(-pos)), 1)
                col = columns.setdefault(k, {"shapes": {}, "colors": {}, "sizes": {}})
                for node in nodes:
                    for name in _leaf_names(node):
                        col["shapes"][name] = (shape, filled)
                        col["colors"][name] = c[0]
                        col["sizes"][name] = rel
            else:
                if pos > 1:
                    st.problems.append((row.line, f"posição {pos:g} fora de 0–1: no fim do ramo"))
                for node in nodes:
                    self.fx.marks.append(BranchMark(node, min(pos, 1.0), "symbol", shape, filled, c[0], rel))
            st.applied += 1
        if not columns:
            return
        title = entry.title or ds.label
        tracks = []
        for k in sorted(columns):
            col = columns[k]
            header = title if len(columns) == 1 else f"{title} {k}"
            first = next(iter(col["colors"].values()), "#000000")
            tracks.append(LeafColumn(f"{entry.key}:{k}", header, {}, self.missing_color, {}, "binary", None,
                                     margin=max(ds.number("MARGIN", 0.0) or 0.0, 0.0) if not tracks else 0.0,
                                     shapes=col["shapes"], shape_color=first, shape_colors=col["colors"],
                                     shape_sizes=col["sizes"]))
        legend = None
        lc, ll = ds.options.get("LEGEND_COLORS", []), ds.options.get("LEGEND_LABELS", [])
        if lc and ll:
            entries = [(entry.labels.get(pc[0], l), entry.color(pc[0]))
                       for ctext, l in zip(lc, ll) if (pc := parse_color(ctext)) is not None]
            legend = LegendGroup(entry.title or ds.option("LEGEND_TITLE") or title, entries) if entries else None
        self.fx.columns.append(ItolColumn(entry.key, f"iTOL símbolos: {title}", tracks, legend))

    def _text(self, entry: ItolEntry, resolver: Resolver, st: ItolStats) -> None:
        ds = entry.dataset
        factor = ds.number("SIZE_FACTOR", 1.0) or 1.0
        texts: dict[str, str] = {}
        colors: dict[str, str] = {}
        styles: dict[str, tuple[bool, bool, float]] = {}
        for row in ds.rows:
            nodes = self._targets(row, resolver, st, 2, "ID e texto")
            if not nodes:
                continue
            f = row.fields + [""] * 7
            text = html.unescape(re.sub(r"<[^>]+>", "", f[1])).strip()
            if not text:
                st.ignored += 1
                st.problems.append((row.line, "texto vazio"))
                continue
            try:
                pos = float(f[2]) if f[2].strip() else -1.0
                size = float(f[5]) if f[5].strip() else 1.0
                rot = float(f[6]) if f[6].strip() else 0.0
            except ValueError:
                st.ignored += 1
                st.problems.append((row.line, "posição, tamanho ou rotação não numérico"))
                continue
            color = "#000000"
            if f[3].strip():
                c = self._color(entry, f[3], row, st)
                if c is None:
                    continue
                color = c[0]
            bold, italic = _label_style(f[4]) or (False, False)
            size = max(size, 0.1) * factor
            if pos < 0:
                for node in nodes:
                    for name in _leaf_names(node):
                        texts[name], colors[name], styles[name] = text, color, (bold, italic, size)
            else:
                for node in nodes:
                    self.fx.marks.append(BranchMark(node, min(pos, 1.0), "text", color=color, size=size,
                                                    text=text, bold=bold, italic=italic, rotation=rot))
            st.applied += 1
        if texts:
            title = entry.title or ds.label
            col = LeafColumn(entry.key, title, {}, self.missing_color, texts, "text", None,
                             margin=max(ds.number("MARGIN", 0.0) or 0.0, 0.0), text_colors=colors,
                             text_styles=styles)
            self.fx.columns.append(ItolColumn(entry.key, f"iTOL texto: {title}", [col], None))

    def _collapse(self, entry: ItolEntry, resolver: Resolver, st: ItolStats) -> None:
        """Só conta: os colapsos entram nas edições da árvore ao importar (``collapse_sets``)."""
        for row in entry.dataset.rows:
            nodes = self._targets(row, resolver, st, 1, "ID")
            if not nodes:
                continue
            if all(n.is_leaf for n in nodes):
                st.ignored += 1
                st.problems.append((row.line, "uma folha não tem o que colapsar (use A|B para o clado)"))
                continue
            st.applied += 1


def _scale_values(items: list[str]) -> list[float]:
    """DATASET_SCALE: "10" ou "10-rótulo-cor-largura-tracejado-fator" → valores."""
    out = []
    for it in items:
        m = re.match(r"^\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", it)
        if m:
            out.append(float(m.group(1)))
    return out


def _number(text: str) -> float | None:
    t = (text or "").strip()
    if t.upper() in ("X", "NA", "NAN", ""):
        return None
    try:
        return float(t.replace(",", ".")) if t.count(",") == 1 and "." not in t else float(t)
    except ValueError:
        raise ValueError(t) from None


def apply_itol(entries: list[ItolEntry], tree: Tree, hidden: Iterable[str] = (),
               missing_color: str = "#d9d9d9") -> ItolEffects:
    """Efeitos de todos os datasets visíveis, na ordem (o seguinte vence em conflito)."""
    b = _Builder(tree, hidden, missing_color)
    for e in entries:
        if e.visible:
            b.run(e)
        else:
            b.fx.stats[e.key] = ItolStats()
    return b.finish()


def collapse_sets(entry: ItolEntry, tree: Tree, hidden: Iterable[str] = ()) -> list[frozenset[str]]:
    """Conjuntos de folhas dos clados de um COLLAPSE (para as edições da árvore)."""
    rows = [r for r in entry.dataset.rows if r.fields]
    resolver = Resolver(tree, (r.fields[0] for r in rows), hidden)
    out: list[frozenset[str]] = []
    for r in rows:
        nodes, _tol, _why = resolver.resolve(r.fields[0])
        for n in nodes:
            if not n.is_leaf:
                leaves = frozenset(_leaf_names(n))
                if leaves not in out:
                    out.append(leaves)
    return out
