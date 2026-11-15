"""Exportação em lote (sem Qt): itens, nomes de arquivo e estilo de cada item.

Um item = (layout, preset) × formato. O preset muda só o visual: colunas, anotações,
nomes, ordem das colunas, metadados usados e comprimentos de ramo continuam os do projeto.
"""

from __future__ import annotations

import copy
import re
import string
from dataclasses import dataclass, field
from pathlib import Path

from jabuti.style import LayoutKind, RenderStyle

FORMATS = ("svg", "pdf", "png", "tiff")
LAYOUT_SLUGS = {
    LayoutKind.RECTANGULAR: "retangular",
    LayoutKind.SLANTED: "diagonal",
    LayoutKind.CIRCULAR: "circular",
    LayoutKind.FAN: "leque",
    LayoutKind.UNROOTED: "nao_enraizada",
}
LAYOUT_NAMES = {
    LayoutKind.RECTANGULAR: "Retangular",
    LayoutKind.SLANTED: "Diagonal",
    LayoutKind.CIRCULAR: "Circular",
    LayoutKind.FAN: "Leque",
    LayoutKind.UNROOTED: "Não enraizada",
}
FIELDS = ("projeto", "layout", "preset", "ext")
DEFAULT_TEMPLATE = "{projeto}_{layout}_{preset}.{ext}"
CURRENT_PRESET = "atual"


class TemplateError(ValueError):
    pass


def check_template(template: str) -> None:
    """Levanta ``TemplateError`` com mensagem clara se o modelo de nome for inválido."""
    if not template.strip():
        raise TemplateError("O modelo de nome está vazio.")
    try:
        names = [f for _t, f, _s, _c in string.Formatter().parse(template) if f is not None]
    except ValueError as exc:
        raise TemplateError(f"Modelo de nome inválido ({exc}). Use chaves como {{layout}}.") from None
    unknown = [n for n in names if n not in FIELDS]
    if unknown:
        raise TemplateError(f"Campo desconhecido no modelo: {{{unknown[0]}}}. Use {', '.join('{%s}' % f for f in FIELDS)}.")
    if any(sep in template for sep in ("/", "\\")):
        raise TemplateError("O modelo de nome não pode ter “/” nem “\\” (a pasta é escolhida à parte).")


def safe_part(text: str) -> str:
    """Trecho seguro para nome de arquivo (sem separadores nem caracteres proibidos)."""
    out = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", text).strip(" .")
    return out or "sem_nome"


def file_name(template: str, project: str, layout: LayoutKind, preset: str, fmt: str) -> str:
    name = template.format(projeto=safe_part(project), layout=LAYOUT_SLUGS[layout], preset=safe_part(preset),
                           ext="tif" if fmt == "tiff" else fmt)
    name = safe_part(name)
    ext = "tif" if fmt == "tiff" else fmt
    if not name.lower().endswith(f".{ext}") and not (fmt == "tiff" and name.lower().endswith(".tiff")):
        name += f".{ext}"
    return name


def visual_style(current: RenderStyle, preset: RenderStyle | None, layout: LayoutKind) -> RenderStyle:
    """Estilo do item: o visual do preset sobre os dados do projeto, no layout pedido."""
    out = copy.deepcopy(preset if preset is not None else current)
    if preset is not None:
        out.figure = copy.deepcopy(current.figure)                 # colunas, iTOL, nomes, ordem…
        out.metadata.color_by = current.metadata.color_by          # quais colunas de metadados
        out.metadata.strips = list(current.metadata.strips)
        out.use_lengths = current.use_lengths
    out.layout = layout
    return out


@dataclass
class BatchItem:
    layout: LayoutKind
    preset: str                      # nome do preset ("atual" = estilo do projeto)
    fmt: str
    path: Path


@dataclass
class BatchPlan:
    items: list[BatchItem] = field(default_factory=list)


def plan_batch(project: str, layouts: list[LayoutKind], presets: list[str], formats: list[str],
               template: str, dest: str | Path) -> BatchPlan:
    """Itens na ordem layout → preset → formato, com nomes únicos (``_2``, ``_3``… se repetirem)."""
    check_template(template)
    if not layouts:
        raise TemplateError("Escolha pelo menos um layout.")
    if not presets:
        raise TemplateError("Escolha pelo menos um estilo (o atual ou um preset).")
    if not formats:
        raise TemplateError("Escolha pelo menos um formato.")
    d = Path(dest)
    used: set[str] = set()
    plan = BatchPlan()
    for layout in layouts:
        for preset in presets:
            for fmt in formats:
                name = file_name(template, project, layout, preset, fmt)
                stem, dot, ext = name.rpartition(".")
                candidate, n = name, 2
                while candidate.lower() in used:
                    candidate, n = f"{stem}_{n}{dot}{ext}", n + 1
                used.add(candidate.lower())
                plan.items.append(BatchItem(layout, preset, fmt, d / candidate))
    return plan


@dataclass
class BatchReport:
    generated: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)     # (arquivo, motivo)
    failed: list[tuple[str, str]] = field(default_factory=list)      # (arquivo, motivo)
    cancelled: bool = False
    not_run: int = 0                                                  # itens não feitos por cancelamento

    def summary(self) -> str:
        lines = [f"Gerados: {len(self.generated)}"]
        lines += [f"  ✓ {p.name}" for p in self.generated]
        if self.skipped:
            lines.append(f"Pulados: {len(self.skipped)}")
            lines += [f"  – {n}: {why}" for n, why in self.skipped]
        if self.failed:
            lines.append(f"Falharam: {len(self.failed)}")
            lines += [f"  ✗ {n}: {why}" for n, why in self.failed]
        if self.cancelled:
            lines.append(f"Cancelado: {self.not_run} item(ns) não exportado(s).")
        return "\n".join(lines)
