"""Metadados em TSV/CSV: uma linha por genoma/folha, com cabeçalho."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from jabuti.parsers.errors import JabutiParseError, read_text
from jabuti.parsers.names import match_names


class MetadataParseError(JabutiParseError):
    pass


MISSING = {"", "na", "n/a", "nan", "none", "null", "-", "?"}


@dataclass
class MetadataTable:
    path: Path | None
    columns: list[str]
    rows: list[dict[str, str]]
    delimiter: str = "\t"
    warnings: list[str] = field(default_factory=list)

    def values(self, column: str) -> list[str]:
        return [r.get(column, "") for r in self.rows]


@dataclass
class MetadataMatch:
    key_column: str
    by_leaf: dict[str, dict[str, str]]     # folha -> linha
    leaves_without: list[str]              # folhas sem linha
    unused_keys: list[str]                 # linhas que não casaram com nenhuma folha


def _sniff_delimiter(sample: str, path: Path | None) -> str:
    first = sample.splitlines()[0] if sample else ""
    if path is not None and path.suffix.lower() in (".tsv", ".tab"):
        return "\t"
    try:
        return csv.Sniffer().sniff(sample, delimiters="\t,;").delimiter
    except csv.Error:
        counts = {d: first.count(d) for d in ("\t", ",", ";")}
        best = max(counts, key=counts.get)  # type: ignore[arg-type]
        if counts[best] == 0:
            raise MetadataParseError(
                "Não encontrei separador (TAB, vírgula ou ponto e vírgula) no cabeçalho.", path, 1
            ) from None
        return best


def parse_table_text(text: str, path: Path | None = None) -> MetadataTable:
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    if not lines:
        raise MetadataParseError("Arquivo vazio.", path)
    delim = _sniff_delimiter("\n".join(lines[:20]), path)
    reader = csv.reader(lines, delimiter=delim)
    header = [h.strip() for h in next(reader)]
    if len(header) < 2:
        raise MetadataParseError("A tabela precisa de pelo menos 2 colunas (chave + 1 metadado).", path, 1)
    if any(not h for h in header):
        header = [h or f"coluna_{i + 1}" for i, h in enumerate(header)]
    dups = {h for h in header if header.count(h) > 1}
    if dups:
        seen: dict[str, int] = {}
        new = []
        for h in header:
            seen[h] = seen.get(h, 0) + 1
            new.append(h if seen[h] == 1 else f"{h}_{seen[h]}")
        header = new
    table = MetadataTable(path, header, [], delim)
    if dups:
        table.warnings.append(f"Colunas repetidas renomeadas: {', '.join(sorted(dups))}.")
    for n, row in enumerate(reader, start=2):
        if len(row) != len(header):
            if len(table.warnings) < 10:
                table.warnings.append(f"Linha {n}: {len(row)} campos (esperados {len(header)}).")
            row = (row + [""] * len(header))[: len(header)]
        table.rows.append({h: v.strip() for h, v in zip(header, row)})
    if not table.rows:
        raise MetadataParseError("A tabela só tem cabeçalho.", path)
    return table


def load_metadata(path: str | Path) -> MetadataTable:
    p = Path(path)
    return parse_table_text(read_text(p, MetadataParseError), p)


def match_table(table: MetadataTable, key_column: str, leaves: list[str]) -> MetadataMatch:
    keys = [r[key_column] for r in table.rows if r.get(key_column, "").strip()]
    mapping = match_names(keys, leaves)
    by_leaf: dict[str, dict[str, str]] = {}
    for row in table.rows:
        leaf = mapping.get(row.get(key_column, ""))
        if leaf is not None and leaf not in by_leaf:
            by_leaf[leaf] = row
    return MetadataMatch(
        key_column=key_column,
        by_leaf=by_leaf,
        leaves_without=[l for l in leaves if l not in by_leaf],
        unused_keys=[k for k in keys if k not in mapping],
    )


def guess_key_column(table: MetadataTable, leaves: list[str]) -> str:
    """Coluna cujos valores casam com mais folhas (empate: a primeira)."""
    best, best_n = table.columns[0], -1
    for col in table.columns:
        n = len(match_names([r[col] for r in table.rows if r.get(col)], leaves))
        if n > best_n:
            best, best_n = col, n
    return best


def is_missing(value: str) -> bool:
    return value.strip().lower() in MISSING


def column_is_numeric(values: list[str]) -> bool:
    present = [v for v in values if not is_missing(v)]
    if len(present) < 2:
        return False
    try:
        nums = [float(v.replace(",", ".")) for v in present]
    except ValueError:
        return False
    return len(set(nums)) > 2  # 0/1 ou poucos valores: melhor como categoria
