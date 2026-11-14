"""Tabelas de dados extras (colunas numéricas, matrizes) e o mapeamento linha → folha.

A tabela é lida fora da thread da interface (``jabuti.workers.FileLoader``); aqui fica só
o modelo, sem Qt. A primeira coluna é a chave (nome do genoma/folha); o mapeamento é
automático (``match_names``) e pode ser corrigido à mão, como na aba GFF.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from jabuti.parsers.metadata import MetadataTable, column_is_numeric, is_missing
from jabuti.parsers.names import match_names

METADATA_SOURCE = "metadata"   # a tabela da aba Metadados


@dataclass
class LeafMapping:
    """Chave (nome no arquivo) -> folha, com edições manuais preservadas."""

    keys: list[str] = field(default_factory=list)
    leaves: list[str] = field(default_factory=list)
    mapping: dict[str, str | None] = field(default_factory=dict)
    manual: set[str] = field(default_factory=set)

    def auto_map(self, reset: bool = True) -> None:
        if reset:
            self.manual.clear()
        keep = {k: l for k, l in self.mapping.items() if k in self.manual and l in self.leaves}
        free = [l for l in self.leaves if l not in keep.values()]
        auto = match_names([k for k in self.keys if k not in keep], free)
        self.mapping = {k: keep.get(k, auto.get(k)) for k in self.keys}

    def set_leaves(self, leaves: list[str]) -> None:
        self.leaves = list(leaves)
        self.manual = {k for k in self.manual if self.mapping.get(k) in self.leaves}
        self.auto_map(reset=False)

    def set(self, key: str, leaf: str | None) -> None:
        """Uma folha só pode ter uma linha: quem a tinha fica sem folha."""
        if leaf is not None:
            for k, l in self.mapping.items():
                if l == leaf and k != key:
                    self.mapping[k] = None
                    self.manual.discard(k)
        self.mapping[key] = leaf
        self.manual.add(key)

    def mapped(self) -> dict[str, str]:
        return {k: l for k, l in self.mapping.items() if l}

    def leaves_without(self) -> list[str]:
        used = set(self.mapped().values())
        return [l for l in self.leaves if l not in used]

    def unused_keys(self) -> list[str]:
        return [k for k in self.keys if not self.mapping.get(k)]


@dataclass
class DataSource:
    """Tabela carregada no painel Figura. ``name`` é o nome do arquivo (usado nos presets)."""

    name: str
    table: MetadataTable
    path: Path | None = None
    key_column: str = ""
    mapping: LeafMapping = field(default_factory=LeafMapping)

    def __post_init__(self) -> None:
        if not self.key_column:
            self.key_column = self.table.columns[0]
        self.mapping.keys = [r.get(self.key_column, "") for r in self.table.rows
                             if r.get(self.key_column, "").strip()]

    @property
    def value_columns(self) -> list[str]:
        return [c for c in self.table.columns if c != self.key_column]

    def numeric_columns(self) -> list[str]:
        return [c for c in self.value_columns if column_is_numeric(self.table.values(c))
                or _all_numbers(self.table.values(c))]

    def by_leaf(self) -> dict[str, dict[str, str]]:
        rows = {r.get(self.key_column, ""): r for r in self.table.rows}
        return {leaf: rows[k] for k, leaf in self.mapping.mapped().items() if k in rows}


def _all_numbers(values: list[str]) -> bool:
    """Coluna só de números (inclui contagens 0/1, que ``column_is_numeric`` trata como categoria)."""
    present = [v for v in values if not is_missing(v)]
    if not present:
        return False
    try:
        for v in present:
            float(v.replace(",", "."))
    except ValueError:
        return False
    return True


def numeric_column(by_leaf: dict[str, dict[str, str]], column: str) -> dict[str, float]:
    """Folha -> valor numérico (NA, vazio ou texto ficam de fora = "sem dado")."""
    out: dict[str, float] = {}
    for leaf, row in by_leaf.items():
        v = row.get(column, "")
        if is_missing(v):
            continue
        try:
            out[leaf] = float(v.replace(",", "."))
        except ValueError:
            continue
    return out
