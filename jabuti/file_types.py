"""Que tipo de arquivo é este? (sem Qt) — para duplo clique, "Abrir com", arrastar e recentes.

Primeiro a extensão; nos ambíguos (``.txt``, ``.tsv``, ``.csv``), uma olhada no começo do
arquivo: anotação do iTOL (palavra-chave ``DATASET_…``/``TREE_COLORS``…), Newick (começa
com ``(``) ou, senão, tabela de metadados.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_SUFFIX = ".jabuti"
# extensões registradas no sistema (Info.plist do .app) e aceitas na linha de comando
TREE_SUFFIXES = (".nwk", ".newick", ".treefile", ".tree", ".tre", ".contree")
OPEN_WITH_SUFFIXES = (PROJECT_SUFFIX, ".nwk", ".newick", ".treefile", ".tree", ".tre")
GFF_SUFFIXES = (".gff", ".gff3", ".gff.gz", ".gff3.gz")
TABLE_SUFFIXES = (".tsv", ".tab", ".csv", ".txt", ".itol")

KINDS = ("project", "tree", "gff", "itol", "metadata")


def _suffix(p: Path) -> str:
    name = p.name.lower()
    for double in (".gff.gz", ".gff3.gz"):
        if name.endswith(double):
            return double
    return p.suffix.lower()


def _zip_is_project(p: Path) -> bool:
    from jabuti.project import bundle_project_name

    return bundle_project_name(p) is not None


def _head(p: Path, n: int = 4096) -> str:
    try:
        with open(p, "rb") as fh:
            return fh.read(n).decode("utf-8-sig", errors="ignore")
    except OSError:
        return ""


def looks_like_newick(p: Path) -> bool:
    text = _head(p).lstrip()
    return text.startswith("(") or (text.startswith("[") and "(" in text)


def classify(path: str | Path) -> str | None:
    """"project", "tree", "gff", "itol", "metadata" ou ``None`` (não é arquivo/desconhecido)."""
    p = Path(path)
    if not p.is_file():
        return None
    suf = _suffix(p)
    if suf == PROJECT_SUFFIX or (suf == ".zip" and _zip_is_project(p)):
        return "project"
    if suf in TREE_SUFFIXES:
        return "tree"
    if suf in GFF_SUFFIXES:
        return "gff"
    if suf in TABLE_SUFFIXES or suf == "":
        from jabuti.parsers.itol import sniff_itol

        if sniff_itol(p):
            return "itol"
        if looks_like_newick(p):
            return "tree"
        return "metadata" if suf != ".itol" else None
    return "tree" if looks_like_newick(p) else None


def group(paths) -> dict[str, list[str]]:  # type: ignore[no-untyped-def]
    """Arquivos agrupados por tipo (na ordem dada); desconhecidos em ``"unknown"``."""
    out: dict[str, list[str]] = {}
    for path in paths:
        out.setdefault(classify(path) or "unknown", []).append(str(path))
    return out
