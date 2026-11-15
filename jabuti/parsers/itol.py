"""Leitura de arquivos de anotação do iTOL (https://itol.embl.de/help.cgi), sem Qt.

Estrutura: 1ª linha útil = tipo (ex.: ``DATASET_COLORSTRIP``); depois ``SEPARATOR``, opções
do cabeçalho e ``DATA``; as linhas seguintes são os dados. ``#`` começa um comentário.

A leitura nunca falha por causa de uma linha: linhas malformadas e palavras-chave
desconhecidas viram avisos (com o número da linha). Só um arquivo ilegível, vazio ou que não
seja do iTOL levanta :class:`ItolError`.
"""

from __future__ import annotations

import csv
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from jabuti.parsers.errors import JabutiParseError, read_text

# tipos com leitura própria no Jabuti (os demais aparecem na lista como "ignorados")
SUPPORTED = {"TREE_COLORS", "LABELS", "DATASET_COLORSTRIP", "DATASET_STYLE",
             "DATASET_SIMPLEBAR", "DATASET_MULTIBAR", "DATASET_HEATMAP", "DATASET_BINARY",
             "DATASET_SYMBOL", "DATASET_TEXT", "COLLAPSE"}
# por que cada tipo conhecido não é suportado (aviso na lista)
UNSUPPORTED_WHY = {
    "POPUP_INFO": "pop-ups só existem na página interativa do iTOL, não numa figura estática",
    "DATASET_RANGE": "use as faixas “range” do TREE_COLORS",
    "DATASET_ALIGNMENT": "alinhamentos de sequência não são desenhados pelo Jabuti",
    "DATASET_CONNECTION": "conexões entre folhas não são desenhadas pelo Jabuti",
    "DATASET_IMAGE": "imagens externas não são carregadas",
}
# tipos do iTOL conhecidos, mas não suportados (ainda)
KNOWN = SUPPORTED | {
    "DATASET_SIMPLEBAR", "DATASET_MULTIBAR", "DATASET_HEATMAP", "DATASET_BINARY", "DATASET_SYMBOL",
    "DATASET_TEXT", "COLLAPSE", "POPUP_INFO", "DATASET_RANGE", "DATASET_GRADIENT", "DATASET_PIECHART",
    "DATASET_BOXPLOT", "DATASET_LINECHART", "DATASET_ALIGNMENT", "DATASET_CONNECTION", "DATASET_DOMAINS",
    "DATASET_EXTERNALSHAPE", "DATASET_IMAGE", "DATASET_SPECTRUM",
}
KIND_NAMES = {
    "TREE_COLORS": "cores e estilos", "LABELS": "nomes", "DATASET_COLORSTRIP": "faixa de cor",
    "DATASET_STYLE": "estilos", "DATASET_SIMPLEBAR": "barras", "DATASET_MULTIBAR": "barras empilhadas",
    "DATASET_HEATMAP": "heatmap", "DATASET_BINARY": "presença/ausência", "DATASET_SYMBOL": "símbolos",
    "DATASET_TEXT": "texto", "COLLAPSE": "colapsar", "POPUP_INFO": "pop-ups",
}
SEPARATORS = {"TAB": "\t", "COMMA": ",", "SPACE": " "}

# opções conhecidas do cabeçalho (comuns a todos os datasets + específicas dos suportados)
_COMMON_OPTIONS = {
    "SEPARATOR", "DATASET_LABEL", "COLOR", "LEGEND_TITLE", "LEGEND_SCALE", "LEGEND_POSITION_X",
    "LEGEND_POSITION_Y", "LEGEND_HORIZONTAL", "LEGEND_SHAPES", "LEGEND_COLORS", "LEGEND_LABELS",
    "LEGEND_SHAPE_SCALES", "LEGEND_SHAPE_INNER_SCALES", "MARGIN", "SHOW_INTERNAL", "LABEL_ROTATION",
    "LABEL_SHIFT", "ALIGN_TO_TREE", "SIZE_FACTOR", "SHOW_LABELS", "LABEL_SIZE_FACTOR",
    "LABEL_ALIGN_TO_TREE", "HEIGHT_FACTOR", "BORDER_WIDTH", "BORDER_COLOR", "COMPLETE_BORDER",
    "DATASET_SCALE", "SHOW_DOMAIN_LABELS", "DATA", "LEGEND_FONT_SIZE",
}
OPTIONS = {
    "DATASET_COLORSTRIP": _COMMON_OPTIONS | {"COLOR_BRANCHES", "STRIP_WIDTH", "SHOW_STRIP_LABELS",
                                             "STRIP_LABEL_POSITION", "STRIP_LABEL_SIZE_FACTOR",
                                             "STRIP_LABEL_COLOR", "STRIP_LABEL_ROTATION",
                                             "STRIP_LABEL_SHIFT", "STRIP_LABEL_COLOR_STROKE",
                                             "STRIP_LABEL_WIDTH_STROKE", "STRIP_LABEL_ALIGN"},
    "DATASET_STYLE": _COMMON_OPTIONS,
    "DATASET_SIMPLEBAR": _COMMON_OPTIONS | {"WIDTH", "BAR_ZERO", "BAR_SHIFT", "SHOW_VALUE", "LOG_SCALE",
                                            "DASHED_LINES", "BAR_SHAPE", "BAR_ROUND_CORNERS",
                                            "VALUE_LABEL_COLOR", "VALUE_LABEL_SIZE_FACTOR",
                                            "LABEL_POSITION", "LABEL_AUTO_COLOR", "VALUE_DECIMALS"},
    "DATASET_MULTIBAR": _COMMON_OPTIONS | {"FIELD_COLORS", "FIELD_LABELS", "WIDTH", "ALIGN_FIELDS",
                                           "SIDE_STACKED", "BAR_ZERO", "BAR_SHIFT", "SHOW_VALUE",
                                           "LOG_SCALE", "DASHED_LINES", "BAR_SHAPE", "BAR_ROUND_CORNERS",
                                           "VALUE_LABEL_COLOR", "VALUE_LABEL_SIZE_FACTOR", "VALUE_DECIMALS"},
    "DATASET_HEATMAP": _COMMON_OPTIONS | {"FIELD_LABELS", "FIELD_TREE", "STRIP_WIDTH", "COLOR_MIN",
                                          "COLOR_MAX", "USE_MID_COLOR", "COLOR_MID", "COLOR_NAN",
                                          "USER_MIN_VALUE", "USER_MID_VALUE", "USER_MAX_VALUE",
                                          "AUTO_LEGEND", "DISPLAY_TREE", "TREE_WIDTH", "SHOW_VALUES",
                                          "LABEL_SHIFT", "LABEL_COLOR", "LABEL_SIZE_FACTOR",
                                          "VERTICAL_GRID", "HORIZONTAL_GRID", "GRID_COLOR", "GRID_WIDTH"},
    "DATASET_SYMBOL": _COMMON_OPTIONS | {"MAXIMUM_SIZE", "GRADIENT_FILL", "SYMBOL_SPACING"},
    "DATASET_TEXT": _COMMON_OPTIONS | {"SIZE_FACTOR", "EXTERNAL_LABEL_SCALE", "STRAIGHT_LABELS",
                                       "LABELS_BELOW", "VERTICAL_SHIFT", "TEXT_LABEL_SCALE"},
    "COLLAPSE": {"SEPARATOR", "DATA"},
    "DATASET_BINARY": _COMMON_OPTIONS | {"FIELD_SHAPES", "FIELD_LABELS", "FIELD_COLORS", "SYMBOL_SPACING",
                                         "HORIZONTAL_GRID", "VERTICAL_GRID", "GRID_COLOR", "GRID_WIDTH",
                                         "SHOW_LABELS", "LABEL_COLOR"},
    "TREE_COLORS": {"SEPARATOR", "DATA"},
    "LABELS": {"SEPARATOR", "DATA"},
}

_KEYWORD = re.compile(r"^[A-Z][A-Z0-9_]*$")
_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB = re.compile(r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$", re.I)


class ItolError(JabutiParseError):
    pass


@dataclass
class ItolRow:
    line: int
    fields: list[str]


@dataclass
class ItolDataset:
    path: Path
    kind: str
    separator: str = "TAB"
    options: dict[str, list[str]] = field(default_factory=dict)
    rows: list[ItolRow] = field(default_factory=list)
    warnings: list[tuple[int, str]] = field(default_factory=list)

    @property
    def label(self) -> str:
        v = self.options.get("DATASET_LABEL")
        return v[0] if v and v[0] else self.path.stem

    @property
    def supported(self) -> bool:
        return self.kind in SUPPORTED

    def option(self, name: str, default: str | None = None) -> str | None:
        v = self.options.get(name)
        return v[0] if v else default

    def flag(self, name: str) -> bool:
        return (self.option(name, "0") or "0").strip() == "1"

    def number(self, name: str, default: float | None = None) -> float | None:
        try:
            return float(self.option(name))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default


def parse_color(text: str) -> tuple[str, float] | None:
    """``#rgb``, ``#rrggbb``, ``rgb(r,g,b)`` ou ``rgba(r,g,b,a)`` → (``#rrggbb``, opacidade)."""
    s = (text or "").strip()
    m = _HEX.match(s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return f"#{h.lower()}", 1.0
    m = _RGB.match(s)
    if m:
        try:
            r, g, b = (max(0, min(int(round(float(m.group(i)))), 255)) for i in (1, 2, 3))
            a = float(m.group(4)) if m.group(4) is not None else 1.0
        except ValueError:
            return None
        return f"#{r:02x}{g:02x}{b:02x}", max(0.0, min(a, 1.0))
    return None


def _split_any(line: str) -> list[str]:
    """Linha do cabeçalho: aceita TAB, vírgula ou espaço (o template de colorstrip mistura)."""
    for sep in ("\t", ","):
        if sep in line:
            return [f.strip() for f in next(csv.reader([line], delimiter=sep))]
    return _split_space(line)


def _split_space(line: str) -> list[str]:
    lex = shlex.shlex(line, posix=True)
    lex.whitespace_split = True
    lex.commenters = ""
    lex.escape = ""
    return list(lex)


def split_line(line: str, separator: str) -> list[str]:
    """Campos de uma linha de dados (aspas duplas agrupam; espaços extras são removidos)."""
    if separator == "SPACE":
        return _split_space(line)
    reader = csv.reader([line], delimiter=SEPARATORS[separator], skipinitialspace=True)
    return [f.strip() for f in next(reader)]


def _guess_separator(lines: list[str]) -> str:
    sample = "\n".join(lines[:50])
    if "\t" in sample:
        return "TAB"
    if "," in sample:
        return "COMMA"
    return "SPACE"


def sniff_itol(path: str | Path) -> bool:
    """O arquivo parece uma anotação do iTOL? (para arrastar e soltar)"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096).decode("utf-8-sig", errors="ignore")
    except OSError:
        return False
    for line in head.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        token = re.split(r"[\s,]", s, maxsplit=1)[0]
        return token in KNOWN or token.startswith("DATASET_")
    return False


def parse_itol(path: str | Path, cancelled=None) -> ItolDataset:  # type: ignore[no-untyped-def]
    p = Path(path)
    text = read_text(p, ItolError)
    lines = text.splitlines()
    first = None
    for i, line in enumerate(lines, start=1):
        s = line.strip()
        if s and not s.startswith("#"):
            first = (i, s)
            break
    if first is None:
        raise ItolError("Arquivo vazio (só comentários ou linhas em branco).", p)
    lineno, s = first
    kind = re.split(r"[\s,]", s, maxsplit=1)[0]
    if not _KEYWORD.match(kind) or (kind not in KNOWN and not kind.startswith("DATASET_")):
        raise ItolError(f"Não parece um arquivo de anotação do iTOL: a 1ª linha deveria ser o tipo "
                        f"(ex.: DATASET_COLORSTRIP, TREE_COLORS), mas é “{s[:60]}”.", p, lineno)
    ds = ItolDataset(p, kind)
    if kind not in SUPPORTED:
        what = KIND_NAMES.get(kind, kind)
        why = UNSUPPORTED_WHY.get(kind, "não é suportado nesta versão")
        ds.warnings.append((lineno, f"tipo {kind} ({what}): {why} — arquivo ignorado"))
    known_options = OPTIONS.get(kind)
    sep: str | None = None
    in_data = False
    for i in range(lineno, len(lines)):
        n = i + 1
        raw = lines[i]
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if not in_data:
            m = re.match(r"^SEPARATOR[\s,]+(\w+)", s)
            if m:
                name = m.group(1).upper()
                if name in SEPARATORS:
                    sep = name
                else:
                    ds.warnings.append((n, f"separador desconhecido “{m.group(1)}” (use TAB, SPACE ou COMMA)"))
                continue
            if s == "DATA" or re.match(r"^DATA[\s,]*$", s):
                in_data = True
                if sep is None:
                    sep = _guess_separator([l for l in lines[n:] if l.strip() and not l.strip().startswith("#")])
                    if kind != "COLLAPSE":           # o template do COLLAPSE não tem SEPARATOR
                        ds.warnings.append((n, f"sem linha SEPARATOR; usando {sep}"))
                continue
            fields = _split_any(s) if sep is None or sep == "SPACE" else split_line(s, sep)
            if len(fields) <= 1 and sep is not None:
                fields = _split_any(s)
            key = fields[0].upper() if fields else ""
            if not _KEYWORD.match(key):
                ds.warnings.append((n, f"linha antes de DATA não reconhecida: “{s[:60]}” (ignorada)"))
                continue
            if known_options is not None and key not in known_options:
                ds.warnings.append((n, f"opção desconhecida {key} (ignorada)"))
            ds.options[key] = fields[1:]
            continue
        try:
            fields = split_line(s, sep or "TAB")
        except (ValueError, csv.Error) as exc:
            ds.warnings.append((n, f"linha malformada ({exc}) — ignorada"))
            continue
        ds.rows.append(ItolRow(n, fields))
    ds.separator = sep or "TAB"
    if not in_data and kind in SUPPORTED:
        ds.warnings.append((len(lines), "linha DATA não encontrada: nenhum dado lido"))
    return ds
