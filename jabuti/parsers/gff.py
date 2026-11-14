"""Leitura leve de GFF3 (Prokka, Bakta, NCBI/PGAP), sem dependências.

- Ignora comentários e para em ``##FASTA``.
- Aceita ``.gff``, ``.gff3`` e versões ``.gz``.
- Linhas malformadas viram avisos (com nº de linha), não erro — a menos que
  nenhuma feature válida seja encontrada.
- Features filhas (ex.: CDS com ``Parent=gene-X``) herdam nome/gene/locus_tag do pai.
"""

from __future__ import annotations

import gzip
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

from jabuti.parsers.errors import JabutiParseError

# tipos que representam genes "pesquisáveis" (evita contar gene + CDS duas vezes)
GENE_TYPES = {"CDS", "tRNA", "rRNA", "tmRNA", "ncRNA", "misc_RNA", "RNase_P_RNA", "SRP_RNA"}
PARENT_TYPES = {"gene", "pseudogene"}
SEARCH_FIELDS = ("product", "name", "gene", "locus_tag")
MAX_WARNINGS = 20


class GffParseError(JabutiParseError):
    pass


class LoadCancelled(Exception):
    """Leitura interrompida pelo usuário."""


CANCEL_CHECK_EVERY = 2000  # linhas


@dataclass
class Feature:
    seqid: str
    type: str
    start: int
    end: int
    strand: str
    attributes: dict[str, str]

    def attr(self, key: str) -> str:
        return self.attributes.get(key, "")

    @property
    def id(self) -> str:
        return self.attr("ID")

    @property
    def name(self) -> str:
        return self.attr("Name")

    @property
    def gene(self) -> str:
        return self.attr("gene") or self.attr("gene_name")

    @property
    def locus_tag(self) -> str:
        return self.attr("locus_tag") or self.attr("old_locus_tag")

    @property
    def product(self) -> str:
        return self.attr("product")

    @property
    def label(self) -> str:
        """Nome curto para exibição (gene > Name > locus_tag)."""
        return self.gene or self.name or self.locus_tag or self.id

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    def field_value(self, name: str) -> str:
        return {"product": self.product, "name": self.name, "gene": self.gene,
                "locus_tag": self.locus_tag}.get(name, self.attr(name))


@dataclass
class Genome:
    name: str                      # nome do arquivo sem extensões (usado no mapeamento)
    path: Path
    key: str = ""                                            # caminho absoluto resolvido (identidade/cache)
    mtime_ns: int = 0                                        # data de modificação lida (cache)
    size: int = 0
    features: list[Feature] = field(default_factory=list)   # todas as features lidas
    genes: list[Feature] = field(default_factory=list)      # pesquisáveis, ordenadas por posição
    warnings: list[str] = field(default_factory=list)

    @property
    def n_genes(self) -> int:
        return len(self.genes)


def genome_name_from_path(path: str | Path) -> str:
    name = Path(path).name
    for ext in (".gz", ".gff3", ".gff", ".gtf"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
    return name


def _parse_attributes(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in text.strip().strip(";").split(";"):
        if not part.strip():
            continue
        if "=" in part:
            k, v = part.split("=", 1)
        else:  # tolera atributos estilo GTF ("key value")
            bits = part.strip().split(" ", 1)
            k, v = bits[0], bits[1].strip('"') if len(bits) > 1 else ""
        out[unquote(k.strip())] = unquote(v.strip())
    return out


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        raise GffParseError("Arquivo não encontrado.", path)
    if path.is_dir():
        raise GffParseError("O caminho é uma pasta, não um arquivo.", path)
    try:
        raw = path.read_bytes()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
    except (OSError, EOFError) as exc:
        raise GffParseError(f"Não foi possível ler o arquivo: {exc}", path) from exc
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc).splitlines()
        except UnicodeDecodeError:
            continue
    raise GffParseError("Codificação de texto não reconhecida.", path)  # pragma: no cover


def file_signature(path: str | Path) -> tuple[int, int]:
    """(data de modificação em ns, tamanho) — muda quando o arquivo é editado."""
    st = Path(path).stat()
    return st.st_mtime_ns, st.st_size


def parse_gff3(path: str | Path, should_stop: Callable[[], bool] | None = None) -> Genome:
    """Lê um GFF3. ``should_stop`` é consultado periodicamente; se devolver True,
    levanta ``LoadCancelled`` (usado pela leitura em segundo plano)."""
    p = Path(path)
    if should_stop is not None and should_stop():
        raise LoadCancelled()
    sig = file_signature(p) if p.exists() and p.is_file() else (0, 0)
    lines = _read_lines(p)
    genome = Genome(genome_name_from_path(p), p, mtime_ns=sig[0], size=sig[1])
    bad = 0

    def warn(msg: str) -> None:
        nonlocal bad
        bad += 1
        if len(genome.warnings) < MAX_WARNINGS:
            genome.warnings.append(msg)

    for i, line in enumerate(lines, start=1):
        if should_stop is not None and i % CANCEL_CHECK_EVERY == 0 and should_stop():
            raise LoadCancelled()
        if not line.strip():
            continue
        if line.startswith("##FASTA") or line.startswith(">"):
            break
        if line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) != 9:
            warn(f"Linha {i}: esperadas 9 colunas separadas por TAB, encontradas {len(cols)}.")
            continue
        seqid, _source, ftype, start, end, _score, strand, _phase, attrs = cols
        try:
            s, e = int(start), int(end)
        except ValueError:
            warn(f"Linha {i}: início/fim não numéricos ({start!r}, {end!r}).")
            continue
        if s > e:
            s, e = e, s
            warn(f"Linha {i}: início maior que o fim (invertidos).")
        genome.features.append(Feature(seqid, ftype, s, e, strand if strand in "+-" else ".",
                                       _parse_attributes(attrs)))

    if not genome.features:
        if bad:
            raise GffParseError(
                f"Nenhuma feature válida ({bad} linha(s) malformada(s)). O arquivo parece não ser GFF3.", p
            )
        raise GffParseError("Nenhuma feature encontrada (arquivo vazio ou só comentários).", p)
    if bad > len(genome.warnings):
        genome.warnings.append(f"… e mais {bad - len(genome.warnings)} linha(s) ignorada(s).")

    _inherit_from_parents(genome.features)
    genome.genes = _searchable(genome.features)
    return genome


def _inherit_from_parents(features: list[Feature]) -> None:
    by_id = {f.id: f for f in features if f.id}
    for f in features:
        parent_id = f.attr("Parent").split(",")[0]
        parent = by_id.get(parent_id)
        if parent is None:
            continue
        for key in ("locus_tag", "gene", "Name"):
            if not f.attributes.get(key) and parent.attributes.get(key):
                f.attributes[key] = parent.attributes[key]
        if not f.product and parent.product:
            f.attributes["product"] = parent.product


def _searchable(features: list[Feature]) -> list[Feature]:
    with_child = {f.attr("Parent").split(",")[0] for f in features if f.type in GENE_TYPES}
    genes = [f for f in features if f.type in GENE_TYPES]
    # genes/pseudogenes sem CDS/RNA filho também contam (ex.: anotações só com "gene")
    genes += [f for f in features if f.type in PARENT_TYPES and f.id not in with_child]
    genes.sort(key=lambda f: (f.seqid, f.start, f.end))
    return genes


# ------------------------------------------------------------------- busca
@dataclass(frozen=True)
class GeneQuery:
    text: str
    fields: tuple[str, ...] = SEARCH_FIELDS
    regex: bool = False
    label: str = ""

    @property
    def title(self) -> str:
        return self.label or self.text

    def matcher(self):  # type: ignore[no-untyped-def]
        """Função ``Feature -> bool``. Levanta ``ValueError`` com regex inválida."""
        if self.regex:
            try:
                rx = re.compile(self.text, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"Expressão regular inválida: {exc}") from exc
            return lambda f: any(rx.search(f.field_value(k) or "") for k in self.fields)
        needle = self.text.lower()
        return lambda f: any(needle in (f.field_value(k) or "").lower() for k in self.fields)


def find_genes(genome: Genome, query: GeneQuery) -> list[Feature]:
    if not query.text.strip():
        return []
    match = query.matcher()
    return [g for g in genome.genes if match(g)]


def neighbors(genome: Genome, anchor: Feature, n: int) -> list[Feature]:
    """``anchor`` e até ``n`` genes de cada lado no mesmo contig (em ordem de posição)."""
    same = [g for g in genome.genes if g.seqid == anchor.seqid]
    try:
        i = next(k for k, g in enumerate(same) if g is anchor)
    except StopIteration:
        return [anchor]
    return same[max(0, i - n): i + n + 1]
