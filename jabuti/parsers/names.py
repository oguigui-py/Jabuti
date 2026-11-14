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
    (ex.: ``GCF_000012345.1_ASM1v1_genomic`` ↔ ``GCF_000012345.1``); 4. uma termina com a
    outra (ex.: ``LB400`` ↔ ``Paraburkholderia_xenovorans_LB400``). 3 e 4 só se forem únicas.
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
    def prefix(a: str, b: str) -> bool:
        return a.startswith(b + "_") or b.startswith(a + "_")

    def suffix(a: str, b: str) -> bool:
        return a.endswith("_" + b) or b.endswith("_" + a)

    for rule in (prefix, suffix):
        for k in keys:
            if k in out:
                continue
            nk = normalize(k)
            if not nk:
                continue
            cands = [l for l in leaves if l not in used and (nl := normalize(l)) and rule(nk, nl)]
            if len(cands) == 1:
                out[k] = cands[0]
                used.add(cands[0])
    return out
