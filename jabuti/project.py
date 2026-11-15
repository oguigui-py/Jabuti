"""Projeto do Jabuti (``.jabuti``): JSON com versão do formato, sem Qt.

Guarda o que é preciso para reabrir a figura inteira: caminhos dos dados (árvore, metadados,
tabelas, tabela de nomes, GFFs, anotações iTOL) e o "view" (o mesmo conteúdo de um preset
completo: estilo, clados, edições da árvore, grupos de rótulos, detecção).

Caminhos: cada arquivo é uma referência ``{"rel": ..., "abs": ..., "name": ...}``. Ao abrir,
tenta-se o relativo à pasta do projeto e depois o absoluto (mover a pasta inteira funciona).
No pacote com cópia dos dados (``.zip``) só há caminhos relativos a ``dados/``.
"""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from jabuti.parsers.errors import JabutiParseError

PROJECT_FORMAT = "jabuti-project"
PROJECT_VERSION = 2
PROJECT_SUFFIX = ".jabuti"
BUNDLE_DATA_DIR = "dados"
BUNDLE_MAX_BYTES = 20 * 1024 * 1024        # arquivos maiores não entram no pacote


class ProjectError(JabutiParseError):
    def __init__(self, message: str, path: str | Path | None = None) -> None:
        super().__init__(message, path)


# ------------------------------------------------------------------ referências a arquivos
def file_ref(path: str | Path, base: Path, absolute: bool = True) -> dict[str, str]:
    """Referência a ``path`` relativa à pasta ``base`` (e absoluta, salvo ``absolute=False``)."""
    p = Path(path).expanduser()
    p = p if p.is_absolute() else (Path.cwd() / p)
    p = Path(os.path.normpath(p))
    out: dict[str, str] = {"name": p.name}
    try:
        out["rel"] = PurePosixPath(Path(os.path.relpath(p, base)).as_posix()).as_posix()
    except ValueError:              # outro disco no Windows: não há caminho relativo
        pass
    if absolute:
        out["abs"] = str(p)
    return out


def resolve_ref(ref: Any, base: Path) -> Path | None:
    """Arquivo existente apontado pela referência (relativo primeiro), ou None."""
    if isinstance(ref, str):                        # tolerância: caminho solto
        ref = {"abs": ref} if Path(ref).is_absolute() else {"rel": ref}
    if not isinstance(ref, dict):
        return None
    for key in ("rel", "abs"):
        raw = ref.get(key)
        if isinstance(raw, str) and raw:
            p = Path(raw) if key == "abs" else base / Path(raw)
            if p.is_file():
                return Path(os.path.normpath(p))
    return None


def ref_label(ref: Any) -> str:
    """Texto para mostrar uma referência (o melhor caminho conhecido)."""
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict):
        return str(ref.get("abs") or ref.get("rel") or ref.get("name") or "?")
    return "?"


# ------------------------------------------------------------------ versões
def _v0_to_v1(data: dict) -> dict:
    """Formato 0 (rascunho): a árvore ficava em ``tree_file`` e o estilo em ``preset``."""
    out = dict(data)
    if "tree_file" in out and "tree" not in out:
        out["tree"] = {"file": out.pop("tree_file"), "rooting": {"mode": "file"}}
    if "preset" in out and "view" not in out:
        out["view"] = out.pop("preset")
    out["version"] = 1
    return out


def _v1_to_v2(data: dict) -> dict:
    """Formato 2: cor dos clados nos nomes vira ``clades.label_mode`` (fundo/texto); os
    projetos antigos mantêm a aparência (as duas caixas antigas são convertidas)."""
    from jabuti.presets import migrate_style_dict

    out = dict(data)
    view = dict(out.get("view") or {})
    if isinstance(view.get("style"), dict):
        view["style"] = migrate_style_dict(view["style"])
    out["view"] = view
    out["version"] = 2
    return out


MIGRATIONS: dict[int, Callable[[dict], dict]] = {0: _v0_to_v1, 1: _v1_to_v2}


def migrate(data: dict) -> tuple[dict, list[str]]:
    version = data.get("version")
    if not isinstance(version, int) or version < 0:
        raise ProjectError("Projeto sem versão do formato reconhecível.")
    if version > PROJECT_VERSION:
        raise ProjectError(f"Este projeto foi criado por uma versão mais nova do Jabuti (formato {version}; "
                           f"esta versão lê até o formato {PROJECT_VERSION}). Atualize o Jabuti para abri-lo.")
    notes = []
    while version < PROJECT_VERSION:
        data = MIGRATIONS[version](data)
        notes.append(f"Projeto convertido do formato {version} para o {data['version']}.")
        version = data["version"]
    return data, notes


def read_project(path: str | Path) -> tuple[dict, list[str]]:
    """Lê, valida e migra. Levanta ``ProjectError`` com mensagem clara."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProjectError("Arquivo de projeto não encontrado.", p) from None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectError(f"Arquivo de projeto inválido (não é JSON do Jabuti): {exc}", p) from None
    if not isinstance(data, dict) or data.get("format") != PROJECT_FORMAT:
        raise ProjectError("Este arquivo não é um projeto do Jabuti.", p)
    try:
        data, notes = migrate(data)
    except ProjectError as exc:
        raise ProjectError(exc.message, p) from None
    if not isinstance(data.get("tree"), dict) or not data["tree"].get("file"):
        raise ProjectError("Projeto sem árvore.", p)
    return data, notes


def write_project(path: str | Path, data: dict) -> Path:
    p = Path(path)
    if p.suffix.lower() != PROJECT_SUFFIX:
        p = p.with_name(p.name + PROJECT_SUFFIX)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)                    # grava inteiro ou nada
    return p


def iter_refs(data: dict):  # type: ignore[no-untyped-def]
    """(seção, índice, referência) de todos os arquivos do projeto, na ordem de leitura."""
    yield "tree", 0, data.get("tree", {}).get("file")
    md = data.get("metadata")
    if isinstance(md, dict) and md.get("file"):
        yield "metadata", 0, md["file"]
    for i, t in enumerate(data.get("tables") or []):
        if isinstance(t, dict) and t.get("file"):
            yield "tables", i, t["file"]
    nm = data.get("names")
    if isinstance(nm, dict) and nm.get("file"):
        yield "names", 0, nm["file"]
    for i, r in enumerate((data.get("itol") or {}).get("files") or []):
        yield "itol", i, r
    for i, r in enumerate((data.get("gff") or {}).get("files") or []):
        yield "gff", i, r


SECTION_NAMES = {"tree": "Árvore", "metadata": "Metadados", "tables": "Tabela de dados",
                 "names": "Tabela de nomes", "itol": "Anotação iTOL", "gff": "GFF3"}


# ------------------------------------------------------------------ pacote com cópia dos dados
@dataclass
class BundleResult:
    path: Path
    copied: list[str] = field(default_factory=list)          # nomes dentro de dados/
    left_out: list[tuple[str, str]] = field(default_factory=list)   # (arquivo, motivo)


def plan_bundle(data: dict, base: Path, max_bytes: int = BUNDLE_MAX_BYTES):  # type: ignore[no-untyped-def]
    """O que entra e o que fica de fora do pacote: ([(seção, i, arquivo)], [(nome, motivo)])."""
    take, out = [], []
    for section, i, ref in iter_refs(data):
        p = resolve_ref(ref, base)
        name = ref_label(ref)
        if section == "gff":
            out.append((Path(name).name, "GFF3 não entra no pacote (arquivos grandes)"))
        elif p is None:
            out.append((Path(name).name, "arquivo não encontrado"))
        elif p.stat().st_size > max_bytes:
            out.append((p.name, f"maior que {max_bytes // (1024 * 1024)} MB"))
        else:
            take.append((section, i, p))
    return take, out


def _set_ref(data: dict, section: str, i: int, ref: dict) -> None:
    if section == "tree":
        data["tree"]["file"] = ref
    elif section in ("metadata", "names"):
        data[section]["file"] = ref
    elif section == "tables":
        data["tables"][i]["file"] = ref
    else:
        data[section]["files"][i] = ref


def write_bundle(zip_path: str | Path, data: dict, base: Path, project_name: str,
                 max_bytes: int = BUNDLE_MAX_BYTES) -> BundleResult:
    """``.zip`` com ``<nome>.jabuti`` e ``dados/``. Nenhum caminho absoluto fica no projeto:
    arquivos copiados apontam para ``dados/…``; os que ficaram de fora guardam só o nome."""
    zp = Path(zip_path)
    if zp.suffix.lower() != ".zip":
        zp = zp.with_name(zp.name + ".zip")
    take, left_out = plan_bundle(data, base, max_bytes)
    out = json.loads(json.dumps(data))                 # cópia profunda
    copied_by_src: dict[Path, str] = {}
    used: set[str] = set()
    files: list[tuple[Path, str]] = []
    for section, i, src in take:
        name = copied_by_src.get(src)
        if name is None:
            stem, suffix, n = src.stem, src.suffix, 2
            name = src.name
            while name.lower() in used:
                name, n = f"{stem}_{n}{suffix}", n + 1
            used.add(name.lower())
            copied_by_src[src] = name
            files.append((src, name))
        _set_ref(out, section, i, {"name": name, "rel": f"{BUNDLE_DATA_DIR}/{name}"})
    taken = {(s, i) for s, i, _p in take}
    for section, i, ref in iter_refs(out):
        if (section, i) not in taken:
            _set_ref(out, section, i, {"name": Path(ref_label(ref)).name})
    out["bundle"] = True
    stem = Path(project_name).stem or "projeto"
    tmp = zp.with_name(zp.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{stem}{PROJECT_SUFFIX}", json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        for src, name in files:
            z.write(src, f"{BUNDLE_DATA_DIR}/{name}")
    os.replace(tmp, zp)
    return BundleResult(zp, [n for _s, n in files], left_out)


def bundle_project_name(zip_path: str | Path) -> str | None:
    """Nome do ``.jabuti`` na raiz do zip (None se o zip não for um projeto)."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = [n for n in z.namelist() if "/" not in n.strip("/") and n.endswith(PROJECT_SUFFIX)]
    except (zipfile.BadZipFile, OSError):
        return None
    return names[0] if names else None


def extract_bundle(zip_path: str | Path, dest: str | Path) -> Path:
    """Extrai o pacote em ``dest`` (sem deixar sair da pasta) e devolve o ``.jabuti``."""
    name = bundle_project_name(zip_path)
    if name is None:
        raise ProjectError("O .zip não contém um projeto do Jabuti.", zip_path)
    d = Path(dest)
    d.mkdir(parents=True, exist_ok=True)
    root = d.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            target = (d / info.filename).resolve()
            if root not in target.parents and target != root:
                raise ProjectError(f"Caminho inválido dentro do .zip: {info.filename}", zip_path)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as fin, open(target, "wb") as fout:
                fout.write(fin.read())
    return d / name
