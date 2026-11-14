"""Casamento tolerante de nomes (arquivo/linha de tabela ↔ folha da árvore)."""

from __future__ import annotations

import re

_SEP = re.compile(r"[\s.\-/|:]+")


def normalize(name: str) -> str:
    """Minúsculas; espaço, ponto, hífen, barra etc. viram ``_``; sem ``_`` repetido nas pontas."""
    s = _SEP.sub("_", name.strip().strip("'\"").lower())
    return re.sub(r"_+", "_", s).strip("_")


def match_names(keys: list[str], leaves: list[str]) -> dict[str, str]:
    """Mapeia cada chave para uma folha (``{chave: folha}``), sem repetir folhas.

    1. igualdade exata; 2. igualdade normalizada; 3. uma contém a outra no início
    (ex.: ``GCF_000012345.1_ASM1v1_genomic`` ↔ ``GCF_000012345.1``), só se for única.
    """
    out: dict[str, str] = {}
    used: set[str] = set()
    leaf_set = set(leaves)
    for k in keys:
        if k in leaf_set and k not in used:
            out[k] = k
            used.add(k)
    norm_leaves: dict[str, list[str]] = {}
    for leaf in leaves:
        norm_leaves.setdefault(normalize(leaf), []).append(leaf)
    for k in keys:
        if k in out:
            continue
        cands = [l for l in norm_leaves.get(normalize(k), []) if l not in used]
        if len(cands) == 1:
            out[k] = cands[0]
            used.add(cands[0])
    for k in keys:
        if k in out:
            continue
        nk = normalize(k)
        if not nk:
            continue
        cands = [
            l for l in leaves
            if l not in used and (nl := normalize(l))
            and (nk.startswith(nl + "_") or nl.startswith(nk + "_"))
        ]
        if len(cands) == 1:
            out[k] = cands[0]
            used.add(cands[0])
    return out
