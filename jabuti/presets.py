"""Presets: todas as configurações visuais em JSON (estilo, detecção, clados e edições).

Formato versionado. Ao carregar, chaves desconhecidas são ignoradas e valores
inválidos viram avisos (o valor padrão é mantido) — nunca erro fatal, exceto
JSON ilegível.
"""

from __future__ import annotations

import json
import re
import typing
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from jabuti.models.clades import Clade, CladeSet
from jabuti.models.document import LADDERIZE, TreeEdits
from jabuti.models.label_groups import SOURCES, LabelGroup, LabelGroupSet, LabelLook
from jabuti.parsers.errors import JabutiParseError, read_text
from jabuti.models.colormaps import COLORMAPS, SCALES
from jabuti.style import (
    BAR_COLOR_MODES,
    HEADER_ROTATIONS,
    MATRIX_SELECT,
    GUIDE_KINDS,
    LEGEND_POSITIONS,
    PALETTES,
    SCALE_POSITIONS,
    SUPPORT_MODES,
    TIP_SHAPES,
    RenderStyle,
)

PRESET_VERSION = 1
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# valores permitidos para campos de texto com opções fixas: (classe, campo) -> opções
CHOICES: dict[tuple[str, str], set[str]] = {
    ("GuideStyle", "kind"): set(GUIDE_KINDS),
    ("SymbolStyle", "shape"): set(TIP_SHAPES),
    ("SupportStyle", "mode"): set(SUPPORT_MODES),
    ("ScaleBarStyle", "position"): set(SCALE_POSITIONS),
    ("LegendStyle", "position"): set(LEGEND_POSITIONS),
    ("CladeStyle", "palette"): set(PALETTES),
    ("CladeStyle", "name_mode"): {"curved", "radial"},
    ("BranchStyle", "cap"): {"flat", "round"},
    ("BarSpec", "color_mode"): set(BAR_COLOR_MODES),
    ("MatrixSpec", "select"): set(MATRIX_SELECT),
    ("MatrixSpec", "scale"): set(SCALES),
    ("MatrixSpec", "colormap"): set(COLORMAPS),
}
# floats que podem ser negativos (os demais precisam ser >= 0)
SIGNED: set[tuple[str, str]] = {("BarSpec", "vmin"), ("BarSpec", "vmax"), ("BarSpec", "refs"),
                                 ("MatrixSpec", "vmin"), ("MatrixSpec", "vmax")}
INT_CHOICES: dict[tuple[str, str], set[int]] = {("SupportStyle", "index"): {-1, 0, 1, 99},
                                               ("MatrixSpec", "header_rotation"): set(HEADER_ROTATIONS)}
# campos fora do preset (estado de tela, não configuração)
SKIP: set[tuple[str, str]] = {("CladeStyle", "cut_distance")}

DEFAULT_DETECTION: dict[str, Any] = {
    "mode": "k",
    "k": 4,
    "support_threshold": 95.0,
    "support_index": 1,
    "distance_fraction": 1 / 3,
    "show_cut": True,
}


class PresetError(JabutiParseError):
    pass


# ------------------------------------------------------------------ estilo
def _plain(val: Any) -> Any:
    if is_dataclass(val):
        return style_to_dict(val)
    if isinstance(val, Enum):
        return val.value
    if isinstance(val, list):
        return [_plain(v) for v in val]
    return val


def style_to_dict(style: Any) -> dict[str, Any]:
    return {f.name: _plain(getattr(style, f.name)) for f in fields(style)
            if (type(style).__name__, f.name) not in SKIP}


def _is_color_field(name: str) -> bool:
    return name.endswith("color") or name == "background"


def _coerce(cls_name: str, name: str, hint: Any, value: Any) -> tuple[bool, Any]:
    """Converte/valida ``value`` para o tipo anotado; (ok, valor)."""
    args = typing.get_args(hint)
    optional = type(None) in args
    base = next((a for a in args if a is not type(None)), hint) if args else hint
    if value is None:
        return optional, None
    if typing.get_origin(hint) is list:
        (item,) = typing.get_args(hint) or (str,)
        if not isinstance(value, list):
            return False, None
        if item is float:
            ok = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
            if ok and (cls_name, name) not in SIGNED:
                ok = all(v >= 0 for v in value)
            return ok, [float(v) for v in value] if ok else None
        ok = all(isinstance(v, str) for v in value)
        if ok and _is_color_field(name.rstrip("s")):
            ok = all(_HEX.match(v) for v in value)
            return ok, [v.lower() for v in value] if ok else None
        return ok, list(value) if ok else None
    if isinstance(base, type) and issubclass(base, Enum):
        try:
            return True, base(value)
        except ValueError:
            return False, None
    if base is bool:
        return isinstance(value, bool), value
    if base is int:
        if isinstance(value, bool) or not isinstance(value, int):
            return False, None
        allowed = INT_CHOICES.get((cls_name, name))
        return (allowed is None or value in allowed), value
    if base is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, None
        return (value >= 0 or (cls_name, name) in SIGNED), float(value)
    if base is str:
        if not isinstance(value, str):
            return False, None
        if _is_color_field(name):
            return bool(_HEX.match(value)), value.lower()
        allowed = CHOICES.get((cls_name, name))
        return (allowed is None or value in allowed), value
    return False, None


def _from_dict(cls: type, data: Any, path: str, warnings: list[str]) -> Any:
    obj = cls()
    if not isinstance(data, dict):
        warnings.append(f"“{path}” deveria ser um objeto; usando o padrão.")
        return obj
    hints = typing.get_type_hints(cls)
    for f in fields(cls):
        if f.name not in data or (cls.__name__, f.name) in SKIP:
            continue
        hint = hints[f.name]
        value = data[f.name]
        key = f"{path}.{f.name}" if path else f.name
        if is_dataclass(hint):
            setattr(obj, f.name, _from_dict(hint, value, key, warnings))
            continue
        item = typing.get_args(hint)[0] if typing.get_origin(hint) is list else None
        if item is not None and is_dataclass(item):
            if isinstance(value, list):
                setattr(obj, f.name, [_from_dict(item, v, f"{key}[{i}]", warnings) for i, v in enumerate(value)])
            else:
                warnings.append(f"“{key}” deveria ser uma lista; usando o padrão.")
            continue
        ok, conv = _coerce(cls.__name__, f.name, hint, value)
        if ok:
            setattr(obj, f.name, conv)
        else:
            warnings.append(f"Valor inválido em “{key}”: {value!r} (mantido o padrão).")
    return obj


def style_from_dict(data: Any, warnings: list[str] | None = None) -> RenderStyle:
    return _from_dict(RenderStyle, data, "style", warnings if warnings is not None else [])


# ---------------------------------------------------------------- preset
def preset_to_dict(
    style: RenderStyle,
    clade_set: CladeSet | None = None,
    edits: TreeEdits | None = None,
    detection: dict[str, Any] | None = None,
    label_groups: LabelGroupSet | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "app": "jabuti",
        "version": PRESET_VERSION,
        "style": style_to_dict(style),
        "detection": {**DEFAULT_DETECTION, **(detection or {})},
    }
    if clade_set is not None:
        out["clades"] = [
            {"name": c.name, "leaves": sorted(c.leaves), "color": c.color,
             "visible": c.visible, "source": c.source}
            for c in clade_set.clades
        ]
        out["clade_auto_mode"] = clade_set.auto_mode
    if label_groups is not None:
        out["label_groups"] = {
            "show_in_legend": label_groups.show_in_legend,
            "groups": [
                {"name": g.name, "leaves": sorted(g.leaves), "source": g.source, "visible": g.visible,
                 "look": g.look.to_dict()}
                for g in label_groups.groups
            ],
        }
    if edits is not None:
        out["edits"] = {
            "ladderize": edits.ladderize,
            "rotations": [sorted(s) for s in edits.rotations],
            "collapsed": [sorted(s) for s in edits.collapsed],
        }
    return out


class LoadedPreset(typing.NamedTuple):
    style: RenderStyle
    detection: dict[str, Any]
    clade_set: CladeSet | None      # None = o preset não traz clados
    edits: TreeEdits | None         # None = o preset não traz edições
    warnings: list[str]
    label_groups: LabelGroupSet | None = None  # None = o preset não traz grupos de rótulos


def _leafsets(raw: Any, key: str, warnings: list[str]) -> list[frozenset[str]]:
    out: list[frozenset[str]] = []
    if not isinstance(raw, list):
        warnings.append(f"“{key}” deveria ser uma lista.")
        return out
    for i, item in enumerate(raw):
        if isinstance(item, list) and item and all(isinstance(x, str) for x in item):
            out.append(frozenset(item))
        else:
            warnings.append(f"“{key}[{i}]” ignorado (lista de nomes de folhas esperada).")
    return out


def preset_from_dict(data: Any) -> LoadedPreset:
    warnings: list[str] = []
    if not isinstance(data, dict):
        raise PresetError("O preset deve ser um objeto JSON.")
    version = data.get("version")
    if not isinstance(version, int):
        warnings.append("Preset sem versão; tentando ler mesmo assim.")
    elif version > PRESET_VERSION:
        warnings.append(f"Preset de versão mais nova ({version}); opções desconhecidas foram ignoradas.")
    style = style_from_dict(data.get("style", {}), warnings)

    detection = dict(DEFAULT_DETECTION)
    raw_det = data.get("detection", {})
    if isinstance(raw_det, dict):
        for k, default in DEFAULT_DETECTION.items():
            if k not in raw_det:
                continue
            v = raw_det[k]
            ok = isinstance(v, type(default)) and not (isinstance(v, bool) and not isinstance(default, bool))
            if isinstance(default, float) and isinstance(v, int) and not isinstance(v, bool):
                v, ok = float(v), True
            if k == "mode" and v not in ("k", "support", "distance", "manual"):
                ok = False
            if ok:
                detection[k] = v
            else:
                warnings.append(f"Valor inválido em “detection.{k}”: {v!r}.")

    clade_set: CladeSet | None = None
    if "clades" in data:
        clade_set = CladeSet()
        raw = data["clades"]
        if not isinstance(raw, list):
            warnings.append("“clades” deveria ser uma lista.")
        else:
            for i, c in enumerate(raw):
                if not isinstance(c, dict):
                    warnings.append(f"“clades[{i}]” ignorado.")
                    continue
                leaves = c.get("leaves")
                if not (isinstance(leaves, list) and leaves and all(isinstance(x, str) for x in leaves)):
                    warnings.append(f"“clades[{i}]” sem lista de folhas válida; ignorado.")
                    continue
                color = c.get("color")
                if color is not None and not (isinstance(color, str) and _HEX.match(color)):
                    warnings.append(f"Cor inválida em “clades[{i}]”; usando a da paleta.")
                    color = None
                source = c.get("source") if c.get("source") in ("auto", "manual") else "manual"
                clade_set.clades.append(Clade(
                    name=str(c.get("name") or f"Clado {i + 1}"),
                    leaves=frozenset(leaves),
                    color=color.lower() if color else None,
                    visible=c.get("visible") is not False,
                    source=source,
                ))
            mode = data.get("clade_auto_mode")
            clade_set.auto_mode = mode if mode in ("k", "support", "distance") else None

    edits: TreeEdits | None = None
    if "edits" in data:
        raw = data["edits"]
        edits = TreeEdits()
        if not isinstance(raw, dict):
            warnings.append("“edits” deveria ser um objeto.")
        else:
            lad = raw.get("ladderize", "none")
            if lad in LADDERIZE:
                edits.ladderize = lad
            else:
                warnings.append(f"Valor inválido em “edits.ladderize”: {lad!r}.")
            edits.rotations = _leafsets(raw.get("rotations", []), "edits.rotations", warnings)
            edits.collapsed = _leafsets(raw.get("collapsed", []), "edits.collapsed", warnings)
    label_groups: LabelGroupSet | None = None
    if "label_groups" in data:
        label_groups = _label_groups(data["label_groups"], warnings)
    return LoadedPreset(style, detection, clade_set, edits, warnings, label_groups)


def _label_groups(raw: Any, warnings: list[str]) -> LabelGroupSet:
    out = LabelGroupSet()
    if not isinstance(raw, dict):
        warnings.append("“label_groups” deveria ser um objeto.")
        return out
    if isinstance(raw.get("show_in_legend"), bool):
        out.show_in_legend = raw["show_in_legend"]
    items = raw.get("groups", [])
    if not isinstance(items, list):
        warnings.append("“label_groups.groups” deveria ser uma lista.")
        return out
    for i, g in enumerate(items):
        key = f"label_groups.groups[{i}]"
        if not isinstance(g, dict):
            warnings.append(f"“{key}” ignorado.")
            continue
        leaves = g.get("leaves")
        if not (isinstance(leaves, list) and leaves and all(isinstance(x, str) for x in leaves)):
            warnings.append(f"“{key}” sem lista de folhas válida; ignorado.")
            continue
        look = _from_dict(LabelLook, g.get("look", {}), f"{key}.look", warnings)
        look.background_alpha = min(look.background_alpha, 1.0)
        look.size_scale = min(max(look.size_scale, 0.5), 2.0)
        source = g.get("source") if g.get("source") in SOURCES else "selection"
        out.groups.append(LabelGroup(
            name=str(g.get("name") or f"Grupo {i + 1}"),
            leaves=frozenset(leaves),
            look=look,
            visible=g.get("visible") is not False,
            source=source,
        ))
    return out


def save_preset(path: str | Path, data: dict[str, Any]) -> Path:
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise PresetError(f"Não foi possível salvar: {exc.strerror or exc}", p) from exc
    return p


def load_preset(path: str | Path) -> LoadedPreset:
    p = Path(path)
    text = read_text(p, PresetError)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PresetError(f"JSON inválido: {exc.msg}", p, exc.lineno) from exc
    try:
        return preset_from_dict(data)
    except PresetError as exc:
        raise PresetError(exc.message, p) from exc
