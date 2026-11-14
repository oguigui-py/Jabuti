"""Casamento tolerante de nomes (arquivo/linha de tabela ↔ folha da árvore)."""

from __future__ import annotations

import re

_SEP = re.compile(r"[\s.\-/|:]+")


def normalize(name: str) -> str:
    """Minúsculas; espaço, ponto, hífen, barra etc. viram ``_``; sem ``_`` repetido nas pontas."""
    s = _SEP.sub("_", name.strip().strip("'\"").lower())
    return re.sub(r"_+", "_", s).strip("_")


def _cuts(name: str) -> list[tuple[str, str]]:
    """Todas as divisões de ``name`` num ``_``: [(prefixo, sufixo), ...]."""
    return [(name[:i], name[i + 1:]) for i, ch in enumerate(name) if ch == "_"]


def match_names(keys: list[str], leaves: list[str]) -> dict[str, str]:
    """Mapeia cada chave para uma folha (``{chave: folha}``), sem repetir folhas.

    1. igualdade exata; 2. igualdade normalizada; 3. uma contém a outra no início
    (ex.: ``GCF_000012345.1_ASM1v1_genomic`` ↔ ``GCF_000012345.1``); 4. uma termina com a
    outra (ex.: ``LB400`` ↔ ``Paraburkholderia_xenovorans_LB400``). 3 e 4 só se forem únicas.

    Linear no total de caracteres: prefixos e sufixos (nos limites de ``_``) são indexados
    uma vez, em vez de comparar todas as chaves com todas as folhas.
    """
    out: dict[str, str] = {}
    used: set[str] = set()
    leaf_set = set(leaves)
    for k in keys:
        if k in leaf_set and k not in used:
            out[k] = k
            used.add(k)

    norm_of = {leaf: normalize(leaf) for leaf in leaves}
    by_norm: dict[str, list[str]] = {}
    by_prefix: dict[str, list[str]] = {}   # "a_b" de "a_b_c" -> folhas
    by_suffix: dict[str, list[str]] = {}   # "b_c" de "a_b_c" -> folhas
    for leaf, nl in norm_of.items():
        if not nl:
            continue
        by_norm.setdefault(nl, []).append(leaf)
        for pre, suf in _cuts(nl):
            by_prefix.setdefault(pre, []).append(leaf)
            by_suffix.setdefault(suf, []).append(leaf)

    def take(k: str, cands) -> None:  # type: ignore[no-untyped-def]
        free = list(dict.fromkeys(c for c in cands if c not in used))
        if len(free) == 1:
            out[k] = free[0]
            used.add(free[0])

    for k in keys:
        if k not in out:
            take(k, by_norm.get(normalize(k), []))

    # 3. prefixo: a folha é um "_"-prefixo da chave, ou a chave é um "_"-prefixo da folha
    for k in keys:
        if k in out or not (nk := normalize(k)):
            continue
        cands = [l for pre, _ in _cuts(nk) for l in by_norm.get(pre, [])] + by_prefix.get(nk, [])
        take(k, cands)
    # 4. sufixo
    for k in keys:
        if k in out or not (nk := normalize(k)):
            continue
        cands = [l for _, suf in _cuts(nk) for l in by_norm.get(suf, [])] + by_suffix.get(nk, [])
        take(k, cands)
    return out
