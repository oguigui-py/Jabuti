"""Grupos de rótulos: estilo dos nomes das folhas, independente dos ramos.

Grupos guardam **nomes de folhas** (não nós), então seguem as folhas após
reenraizar, aplicar ladderize ou colapsar. Uma folha pertence a no máximo um
grupo efetivo: em conflito, vale o grupo criado por último (fim da lista).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields, replace
from typing import Iterable, Literal

GroupSource = Literal["clade", "selection", "pattern"]
SOURCES: dict[str, str] = {"clade": "clado", "selection": "seleção", "pattern": "padrão"}

# fundos sugeridos (marca-texto) para grupos novos, em ordem
HIGHLIGHT_COLORS = ["#b7e4a3", "#ffe066", "#a5d8ff", "#ffc9c9", "#e5dbff", "#ffd8a8", "#c3fae8", "#d8d8d8"]


@dataclass
class LabelLook:
    """Estilo de rótulo de um grupo. ``None`` = herda (metadados/clado/padrão)."""

    text_color: str | None = None
    background: str | None = None
    background_alpha: float = 1.0
    bold: bool | None = None
    italic: bool | None = None
    size_scale: float = 1.0          # relativo ao tamanho padrão dos rótulos
    padding: float = 2.0             # margem interna do fundo (px)
    radius: float = 3.0              # cantos arredondados do fundo (px)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass
class LabelGroup:
    name: str
    leaves: frozenset[str]
    look: LabelLook = field(default_factory=LabelLook)
    visible: bool = True
    source: GroupSource = "selection"


@dataclass
class LabelGroupSet:
    groups: list[LabelGroup] = field(default_factory=list)
    show_in_legend: bool = True

    def add(self, leaves: Iterable[str], source: GroupSource, name: str | None = None,
            look: LabelLook | None = None) -> LabelGroup:
        leaves = frozenset(leaves)
        if not leaves:
            raise ValueError("Nenhuma folha para o grupo.")
        n = sum(1 for g in self.groups if g.source == source) + 1
        default_name = {"clade": f"Clado {n}", "selection": f"Seleção {n}", "pattern": f"Padrão {n}"}[source]
        if look is None:
            look = LabelLook(background=self.next_color())
        g = LabelGroup(name or default_name, leaves, look, True, source)
        self.groups.append(g)
        return g

    def next_color(self) -> str:
        used = {g.look.background for g in self.groups}
        return next((c for c in HIGHLIGHT_COLORS if c not in used),
                    HIGHLIGHT_COLORS[len(self.groups) % len(HIGHLIGHT_COLORS)])

    def remove(self, group: LabelGroup) -> None:
        self.groups = [g for g in self.groups if g is not group]

    def clear(self) -> None:
        self.groups = []

    def effective(self, names: Iterable[str] | None = None) -> dict[str, LabelGroup]:
        """Grupo que vale para cada folha (o último visível que a contém)."""
        allowed = set(names) if names is not None else None
        out: dict[str, LabelGroup] = {}
        for g in self.groups:
            if not g.visible:
                continue
            for leaf in g.leaves:
                if allowed is None or leaf in allowed:
                    out[leaf] = g
        return out

    def effective_counts(self, names: Iterable[str] | None = None) -> dict[int, int]:
        """id(grupo) -> nº de folhas em que o grupo está valendo."""
        counts: dict[int, int] = {id(g): 0 for g in self.groups}
        for g in self.effective(names).values():
            counts[id(g)] += 1
        return counts

    def group_of(self, leaf: str) -> LabelGroup | None:
        return self.effective().get(leaf)

    def restricted_to(self, names: Iterable[str]) -> tuple["LabelGroupSet", int, int]:
        """Cópia só com folhas existentes; (conjunto, folhas ignoradas, grupos descartados)."""
        present = set(names)
        out = LabelGroupSet(show_in_legend=self.show_in_legend)
        ignored = dropped = 0
        for g in self.groups:
            keep = g.leaves & present
            ignored += len(g.leaves) - len(keep)
            if keep:
                out.groups.append(replace(g, leaves=frozenset(keep)))
            else:
                dropped += 1
        return out, ignored, dropped


def match_pattern(names: Iterable[str], text: str, regex: bool = False) -> list[str]:
    """Folhas cujo nome casa com ``text`` (sem diferenciar maiúsculas).

    Texto simples = "contém". Regex inválida levanta ``ValueError`` com mensagem clara.
    """
    text = text.strip()
    if not text:
        return []
    if regex:
        try:
            rx = re.compile(text, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"Expressão regular inválida: {exc}") from exc
        return [n for n in names if rx.search(n)]
    needle = text.lower()
    return [n for n in names if needle in n.lower()]
