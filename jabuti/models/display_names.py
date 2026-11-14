"""Nomes de exibição das folhas (o nome original continua nas buscas e mapeamentos).

Ordem: tabela (original → exibido) → "_" vira espaço → regras regex → abreviar gênero →
prefixo/símbolo nas folhas marcadas.
"""

from __future__ import annotations

import re
from typing import Iterable

_GENUS = re.compile(r"^([A-Z][a-z]{2,})([ _])(?=\S)")


def compile_rules(patterns: list[str], replacements: list[str]) -> tuple[list[tuple[re.Pattern, str]], list[str]]:
    """Regras válidas e mensagens das inválidas."""
    out, errors = [], []
    for i, pat in enumerate(patterns):
        if not pat:
            continue
        rep = replacements[i] if i < len(replacements) else ""
        try:
            out.append((re.compile(pat), rep))
        except re.error as exc:
            errors.append(f"Regra {i + 1} (“{pat}”): expressão regular inválida — {exc}")
    return out, errors


def abbreviate_genus(name: str) -> str:
    """"Cupriavidus necator" → "C. necator" (só o primeiro nome, se for seguido de outro)."""
    return _GENUS.sub(lambda m: f"{m.group(1)[0]}.{m.group(2)}", name, count=1)


def display_names(names: Iterable[str], rules, mapping: dict[str, str] | None = None,  # type: ignore[no-untyped-def]
                  marked: Iterable[str] = ()) -> dict[str, str]:
    """Nome exibido de cada folha que muda (as demais ficam de fora)."""
    mapping = mapping or {}
    marked = set(marked)
    compiled, _errors = compile_rules(list(rules.patterns), list(rules.replacements))
    out: dict[str, str] = {}
    for name in names:
        s = mapping.get(name, name)
        if rules.underscores:
            s = s.replace("_", " ")
        for rx, rep in compiled:
            try:
                s = rx.sub(rep, s)
            except (re.error, IndexError):
                continue
        if rules.abbreviate_genus:
            s = abbreviate_genus(s)
        if name in marked and rules.mark_prefix:
            s = f"{rules.mark_prefix}{s}"
        if s != name:
            out[name] = s
    return out


def parse_name_table(table) -> tuple[dict[str, str], list[str]]:  # type: ignore[no-untyped-def]
    """Tabela de 2 colunas (nome original, nome exibido) → dicionário; avisos de linhas vazias."""
    a, b = table.columns[0], table.columns[1]
    out, warnings = {}, []
    for i, row in enumerate(table.rows, start=2):
        k, v = row.get(a, "").strip(), row.get(b, "").strip()
        if k and v:
            out[k] = v
        elif k or v:
            warnings.append(f"Linha {i}: nome original ou exibido vazio (ignorada).")
    return out, warnings
