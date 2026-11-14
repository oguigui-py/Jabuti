"""Leitura de Newick / .treefile (IQ-TREE) via Biopython, convertida para o modelo próprio."""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

from jabuti.models.tree import Node, Tree
from jabuti.parsers.errors import TreeParseError, read_text

_NUM = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _validate(text: str, path: Path | None) -> str:
    """Validação léxica mínima; devolve somente a primeira árvore."""
    depth = 0
    i = 0
    n = len(text)
    first_open: int | None = None
    while i < n:
        ch = text[i]
        if ch == "'":  # nome entre aspas ('' é aspa escapada)
            j = i + 1
            while True:
                j = text.find("'", j)
                if j == -1:
                    raise TreeParseError("Aspas simples não fechadas.", path, _line_of(text, i))
                if j + 1 < n and text[j + 1] == "'":
                    j += 2
                    continue
                break
            i = j + 1
            continue
        if ch == "[":  # comentário
            j = text.find("]", i)
            if j == -1:
                raise TreeParseError("Comentário '[' sem ']' correspondente.", path, _line_of(text, i))
            i = j + 1
            continue
        if ch == "(":
            if first_open is None:
                first_open = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise TreeParseError("Parêntese ')' sem '(' correspondente.", path, _line_of(text, i))
        elif ch == ":":
            m = re.match(r":\s*([^,();\[\s]*)", text[i:])
            token = m.group(1) if m else ""
            if not _NUM.match(token):
                raise TreeParseError(
                    f"Comprimento de ramo inválido: ':{token}' (esperado um número).",
                    path,
                    _line_of(text, i),
                )
        elif ch == ";":
            if depth != 0:
                raise TreeParseError(
                    "Parênteses desbalanceados antes do ';'.", path, _line_of(text, i)
                )
            return text[: i + 1]
        i += 1
    if depth != 0:
        raise TreeParseError("Parênteses desbalanceados (faltando ')').", path)
    if first_open is None:
        raise TreeParseError("O conteúdo não parece Newick (nenhum '(' encontrado).", path)
    # sem ';' final: aceita, mas completa
    return text.strip() + ";"


def _split_supports(label: str) -> list[float] | None:
    parts = label.split("/")
    try:
        return [float(p) for p in parts if p.strip() != ""] or None
    except ValueError:
        return None


def _convert(clade) -> Node:  # type: ignore[no-untyped-def]
    """Converte Bio.Phylo Clade -> Node (iterativo, para árvores grandes)."""
    root = Node()
    stack = [(clade, root)]
    while stack:
        src, dst = stack.pop()
        dst.length = float(src.branch_length) if src.branch_length is not None else None
        name = src.name or ""
        if src.clades:
            sup: list[float] | None = None
            if src.confidence is not None:
                sup = [float(src.confidence)]
            elif name:
                sup = _split_supports(name)
                if sup is not None:
                    name = ""
            dst.supports = sup or []
        dst.name = name
        for child in src.clades:
            node = Node()
            dst.add_child(node)
            stack.append((child, node))
    return root


def parse_newick_string(text: str, path: Path | None = None) -> Tree:
    from Bio import Phylo  # import tardio: só quando necessário
    from Bio.Phylo.NewickIO import NewickError

    if not text.strip():
        raise TreeParseError("Arquivo vazio.", path)
    first = _validate(text, path)
    try:
        trees = list(Phylo.parse(StringIO(first), "newick"))
    except NewickError as exc:
        raise TreeParseError(f"Newick inválido: {exc}", path) from exc
    except Exception as exc:  # noqa: BLE001
        raise TreeParseError(f"Falha ao interpretar a árvore: {exc}", path) from exc
    if not trees:
        raise TreeParseError("Nenhuma árvore encontrada no arquivo.", path)
    tree = Tree(_convert(trees[0].root))
    leaves = tree.leaves()
    if len(leaves) < 2:
        raise TreeParseError("A árvore precisa ter pelo menos 2 folhas.", path)
    unnamed = sum(1 for leaf in leaves if not leaf.name)
    if unnamed:
        raise TreeParseError(f"{unnamed} folha(s) sem nome.", path)
    return tree


def load_tree(path: str | Path) -> Tree:
    p = Path(path)
    return parse_newick_string(read_text(p, TreeParseError), p)
