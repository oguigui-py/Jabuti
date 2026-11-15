"""Converte datasets do iTOL em objetos do Jabuti (sem Qt), a cada desenho.

Os IDs são resolvidos na árvore desenhada (já reenraizada/podada), então ``A|B`` acompanha
reenraizamento e ladderize. Nada é copiado para o estado do usuário: desligar ou remover um
dataset desfaz o efeito.

Tipos desta etapa: ``TREE_COLORS``, ``LABELS``, ``DATASET_COLORSTRIP`` e ``DATASET_STYLE``.
"""

from __future__ import annotations

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
class ItolStats:
    applied: int = 0
    ignored: int = 0
    tolerant: int = 0              # IDs casados pelo modo tolerante (não exatos)
    problems: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class ItolColumn:
    key: str
    label: str                     # nome na lista "Ordem das colunas"
    column: LeafColumn
    legend: LegendGroup | None


@dataclass
class ItolEffects:
    edge_looks: dict[Node, BranchLook] = field(default_factory=dict)
    node_looks: dict[Node, BranchLook] = field(default_factory=dict)
    ranges: list[RangeBackground] = field(default_factory=list)
    label_groups: list[LabelGroup] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    columns: list[ItolColumn] = field(default_factory=list)
    legends: list[LegendGroup] = field(default_factory=list)
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
                   "DATASET_COLORSTRIP": self._colorstrip, "DATASET_STYLE": self._style}[ds.kind]
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
        self.fx.columns.append(ItolColumn(entry.key, f"iTOL: {header}", col, legend))
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
