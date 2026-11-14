"""Blocos de fundo contínuos a partir das pontas desenhadas (sem Qt).

Pontas seguidas com o mesmo fundo (mesma "chave": cor, opacidade…) formam um bloco, que é
desenhado como um único caminho: sem emenda entre as folhas e sem opacidade dobrada. Um
bloco encostado em outro de chave diferente vai até o ponto médio entre as duas folhas; uma
ponta sem fundo (ou um clado colapsado, que ocupa a sua linha) separa os blocos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Hashable, Iterable, Sequence, TypeVar

T = TypeVar("T")

# avanço (em unidades de cena = pt) do bloco seguinte sob a divisa entre cores diferentes:
# cobre o meio pixel de antialiasing, para não aparecer uma linha clara na divisa
SEAM_OVERLAP = 0.25


@dataclass
class Block:
    key: Hashable
    tips: list = field(default_factory=list)
    before: bool = False        # encostado num bloco de outra chave antes da 1ª ponta
    after: bool = False         # encostado num bloco de outra chave depois da última


def blocks(tips: Sequence[T], key_of: Callable[[T], Hashable | None],
           adjacent: Callable[[T, T], bool] = lambda a, b: True) -> list[Block]:
    """Agrupa pontas consecutivas (na ordem desenhada) com a mesma chave.

    ``key_of`` devolve ``None`` para pontas sem fundo; ``adjacent(a, b)`` diz se duas pontas
    seguidas se encostam (ex.: não se encostam no fim e no começo de um leque)."""
    out: list[Block] = []
    prev_key: Hashable | None = None
    prev_tip: T | None = None
    for tip in tips:
        key = key_of(tip)
        touching = prev_tip is not None and adjacent(prev_tip, tip)
        if key is None:
            prev_key, prev_tip = None, tip
            continue
        if out and touching and key == prev_key:
            out[-1].tips.append(tip)
        else:
            block = Block(key, [tip])
            if touching and prev_key is not None:      # encostado num bloco de outra chave
                block.before = True
                out[-1].after = True
            out.append(block)
        prev_key, prev_tip = key, tip
    return out


def ordered_tips(nodes: Iterable[T], position: Callable[[T], float]) -> list[T]:
    """Pontas (folhas e clados colapsados) na ordem em que são desenhadas."""
    return sorted(nodes, key=position)
