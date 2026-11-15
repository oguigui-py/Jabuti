"""Salvar e abrir projetos (``.jabuti``) na janela principal.

Abrir acontece em etapas: árvore (rápida, na thread da GUI) → metadados → tabelas → tabela
de nomes → anotações iTOL → GFFs (estas lidas nas threads de sempre) → aplicar o "view"
(estilo, clados, edições, grupos), os mapeamentos manuais e as buscas → desenhar uma vez.
A janela continua respondendo durante a leitura.

Alterações não salvas: o projeto coletado agora é comparado com o do último salvar/abrir
(desfazer uma mudança à mão tira o asterisco).
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jabuti import __version__
from jabuti.logs import get_logger
from jabuti.parsers.gff import GeneQuery
from jabuti.presets import preset_from_dict
from jabuti.project import (
    BUNDLE_MAX_BYTES,
    PROJECT_FORMAT,
    PROJECT_SUFFIX,
    PROJECT_VERSION,
    SECTION_NAMES,
    ProjectError,
    bundle_project_name,
    extract_bundle,
    file_ref,
    iter_refs,
    plan_bundle,
    read_project,
    ref_label,
    resolve_ref,
    write_bundle,
    write_project,
)
from jabuti.settings import add_recent, open_file, save_file
from jabuti.views.errors import show_error

PROJECT_FILTER = "Projeto do Jabuti (*.jabuti *.zip);;Todos (*)"
_log = get_logger("project")


class MissingFilesDialog(QDialog):
    """Arquivos do projeto que não foram encontrados: Localizar… ou Ignorar, um a um."""

    def __init__(self, missing: list[tuple[str, int, object]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Arquivos não encontrados")
        self.setModal(True)
        self.result_paths: dict[tuple[str, int], Path | None] = {(s, i): None for s, i, _r in missing}
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Estes arquivos do projeto não foram encontrados (nem pelo caminho relativo, nem pelo "
                           "absoluto).\nLocalize-os ou ignore; o resto do projeto abre normalmente."))
        grid = QGridLayout()
        self.status: dict[tuple[str, int], QLabel] = {}
        for row, (section, i, ref) in enumerate(missing):
            name = QLabel(f"<b>{SECTION_NAMES.get(section, section)}</b>: {Path(ref_label(ref)).name}")
            name.setToolTip(ref_label(ref))
            st = QLabel("ausente" if section != "tree" else "ausente (obrigatório)")
            loc = QPushButton("Localizar…")
            loc.clicked.connect(lambda _=False, k=(section, i), r=ref: self._locate(k, r))
            grid.addWidget(name, row, 0)
            grid.addWidget(st, row, 1)
            grid.addWidget(loc, row, 2)
            if section != "tree":
                ign = QPushButton("Ignorar")
                ign.clicked.connect(lambda _=False, k=(section, i): self._ignore(k))
                grid.addWidget(ign, row, 3)
            self.status[(section, i)] = st
        v.addLayout(grid)
        box = QDialogButtonBox()
        box.addButton("Continuar", QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton("Cancelar abertura", QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        v.addWidget(box)

    def _locate(self, key: tuple[str, int], ref) -> None:  # type: ignore[no-untyped-def]
        path = open_file(self, f"Localizar {Path(ref_label(ref)).name}", "project", "Todos (*)")
        if path:
            self.result_paths[key] = Path(path)
            self.status[key].setText(f"→ {Path(path).name}")

    def _ignore(self, key: tuple[str, int]) -> None:
        self.result_paths[key] = None
        self.status[key].setText("ignorado")


class ProjectController(QObject):
    loaded = Signal(bool)              # terminou de abrir (ok?)

    def __init__(self, win) -> None:  # type: ignore[no-untyped-def]
        super().__init__(win)
        self.win = win
        self.path: Path | None = None
        self.loading = False
        self._baseline: str | None = None
        self._steps: list = []
        self._waiting: str | None = None
        self._data: dict = {}
        self._base = Path.cwd()
        self._found: dict[tuple[str, int], Path] = {}
        self._notes: list[str] = []
        self.dangling: dict[str, list] = {}        # referências ignoradas (continuam no projeto)
        win.figure_panel.table_loaded.connect(lambda _ok: self._step_done("table"))
        win.figure_panel.itol.loaded.connect(lambda _ok: self._step_done("itol"))
        win.gff_tab.loading_finished.connect(lambda *_a: self._step_done("gff"))

    # ------------------------------------------------------------------ coletar
    def base_dir(self) -> Path:
        return self.path.parent if self.path is not None else Path.cwd()

    def collect(self, base: Path | None = None, absolute: bool = True) -> dict | None:
        w = self.win
        if w.tree is None or w.tree_tab.path is None:
            return None
        base = base or self.base_dir()

        def ref(p):  # type: ignore[no-untyped-def]
            return file_ref(p, base, absolute)

        fp, gff, md = w.figure_panel, w.gff_tab, w.metadata_tab
        data: dict = {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "app_version": __version__,
            "tree": {"file": ref(w.tree_tab.path), "rooting": dict(w.tree_tab.rooting)},
            "view": w.collect_preset(include_tree_state=True),
            "export": {"png_dpi": w.viz_tab.dpi.value(), "tiff_dpi": w.viz_tab.tiff_dpi.value(),
                       "tiff_lzw": w.viz_tab.tiff_lzw.isChecked()},
            "metadata": None,
            "tables": [],
            "names": None,
            "gff": {"files": [], "manual": {}, "queries": [], "context": {}},
            "itol": {"files": []},
        }
        if md.table is not None and md.table.path is not None:
            data["metadata"] = {"file": ref(md.table.path), "key_column": md.key_column() or ""}
        for src in fp.sources.values():
            if src.path is None:
                continue
            m = src.mapping
            data["tables"].append({"file": ref(src.path), "key_column": src.key_column,
                                   "manual": {k: m.mapping.get(k) for k in sorted(m.manual) if m.mapping.get(k)}})
        if fp.name_map_path is not None:
            data["names"] = {"file": ref(fp.name_map_path)}
        g = data["gff"]
        g["files"] = [ref(x.path) for x in gff.genomes]
        g["manual"] = {n: gff.mapping.get(n) for n in sorted(gff.manual) if gff.mapping.get(n)}
        g["queries"] = [{"text": q.text, "fields": list(q.fields), "regex": q.regex, "label": q.label}
                        for q in gff.queries]
        g["context"] = {"enabled": gff.ctx_enabled.isChecked(), "anchor": gff.ctx_anchor.currentData() or "",
                        "n": gff.ctx_n.value()}
        data["itol"]["files"] = [ref(p) for p in fp.itol.paths()]
        # arquivos ignorados ao abrir continuam guardados (até sair do painel)
        for section, refs in self.dangling.items():
            target = data["gff"]["files"] if section == "gff" else data["itol"]["files"] if section == "itol" else None
            if target is not None:
                target.extend(refs)
            elif section == "tables":
                data["tables"].extend({"file": r, "key_column": "", "manual": {}} for r in refs)
            elif section in ("metadata", "names") and refs and data[section] is None:
                data[section] = {"file": refs[0], "key_column": ""} if section == "metadata" else {"file": refs[0]}
        return data

    def _blob(self) -> str | None:
        try:
            data = self.collect(absolute=True)
        except Exception:  # noqa: BLE001 — o indicador nunca pode derrubar o app
            _log.exception("falha ao comparar o projeto")
            return None
        return json.dumps(data, sort_keys=True, ensure_ascii=False) if data is not None else None

    # ------------------------------------------------------------------ alterações / título
    def is_dirty(self) -> bool:
        if self.loading or self.win.tree is None:
            return False
        return self._blob() != self._baseline

    def mark_clean(self) -> None:
        self._baseline = self._blob()
        self.update_title()

    def update_dirty(self) -> None:
        if self.loading:
            return
        if self._baseline is None and self.win.tree is not None and self.path is None:
            self._baseline = self._blob()          # primeira árvore da sessão: ponto de partida
        self.update_title()

    def display_name(self) -> str:
        if self.path is not None:
            return self.path.name
        if self.win.tree_tab.path is not None:
            return self.win.tree_tab.path.name
        return ""

    def update_title(self) -> None:
        name = self.display_name()
        self.win.setWindowTitle(f"{name}[*] — Jabuti" if name else "Jabuti")
        self.win.setWindowModified(self.is_dirty())

    # ------------------------------------------------------------------ salvar
    def save(self) -> Path | None:
        if self.path is None:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> Path | None:
        if self.win.tree is None:
            show_error(self.win, Exception("Abra uma árvore antes de salvar o projeto."), "Salvar projeto")
            return None
        stem = self.path.stem if self.path else (self.win.tree_tab.path.stem if self.win.tree_tab.path else "projeto")
        path = save_file(self.win, "Salvar projeto", "project", f"{stem}{PROJECT_SUFFIX}",
                         "Projeto do Jabuti (*.jabuti)")
        return self._write(Path(path)) if path else None

    def _write(self, path: Path) -> Path | None:
        if path.suffix.lower() != PROJECT_SUFFIX:
            path = path.with_name(path.name + PROJECT_SUFFIX)
        data = self.collect(base=path.parent)
        if data is None:
            show_error(self.win, Exception("Abra uma árvore antes de salvar o projeto."), "Salvar projeto")
            return None
        try:
            out = write_project(path, data)
        except OSError as exc:
            show_error(self.win, Exception(f"Não foi possível salvar {path}:\n{exc.strerror or exc}"), "Salvar projeto")
            return None
        self.path = out
        add_recent(out, "projects")
        self.mark_clean()
        self.win.statusBar().showMessage(f"Projeto salvo: {out}", 8000)
        return out

    def confirm_bundle(self, copied: list[str], left_out: list[tuple[str, str]]) -> bool:
        """Aviso antes do pacote (substituível nos testes)."""
        text = (f"O .zip vai levar uma cópia de {len(copied)} arquivo(s) de dados junto com o projeto.\n"
                "Atenção: os dados passam a ficar DENTRO do arquivo — quem receber o .zip terá acesso a eles.\n"
                "Nenhum caminho do seu computador é gravado (só caminhos relativos à pasta dados/).")
        box = QMessageBox(QMessageBox.Icon.Information, "Salvar projeto com cópia dos dados", text, parent=self.win)
        info = "Vão no pacote:\n" + "\n".join(f"• {n}" for n in copied)
        if left_out:
            info += "\n\nFicam de fora (localize ao abrir):\n" + "\n".join(f"⚠ {n}: {why}" for n, why in left_out)
        box.setInformativeText(info)
        ok = box.addButton("Salvar .zip…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is ok

    def save_bundle(self, dest: str | Path | None = None, max_bytes: int = BUNDLE_MAX_BYTES):  # type: ignore[no-untyped-def]
        """``.zip`` com o projeto e cópia dos dados pequenos (árvore, tabelas, iTOL); sem GFFs."""
        if self.win.tree is None:
            show_error(self.win, Exception("Abra uma árvore antes de salvar o projeto."), "Salvar projeto")
            return None
        base = self.base_dir()
        data = self.collect(base=base)
        take, left_out = plan_bundle(data, base, max_bytes)
        names = list(dict.fromkeys(p.name for _s, _i, p in take))
        if not self.confirm_bundle(names, left_out):
            return None
        if dest is None:
            stem = self.path.stem if self.path else self.win.tree_tab.path.stem
            dest = save_file(self.win, "Salvar projeto com cópia dos dados", "project", f"{stem}.zip", "Zip (*.zip)")
            if not dest:
                return None
        stem = self.path.stem if self.path else self.win.tree_tab.path.stem
        try:
            res = write_bundle(dest, data, base, stem, max_bytes)
        except OSError as exc:
            show_error(self.win, Exception(f"Não foi possível gravar {dest}:\n{exc.strerror or exc}"),
                       "Salvar projeto com cópia dos dados")
            return None
        extra = f"; {len(res.left_out)} de fora" if res.left_out else ""
        self.win.statusBar().showMessage(f"Pacote salvo: {res.path} ({len(res.copied)} arquivo(s) de dados{extra}).",
                                         12000)
        return res

    # ------------------------------------------------------------------ abrir
    def confirm_extract(self, dest: Path) -> str | None:
        """Pasta de extração já existe: "use" (abrir a que está lá), "replace" ou None (cancelar)."""
        box = QMessageBox(QMessageBox.Icon.Question, "Abrir projeto",
                          f"A pasta “{dest.name}” já existe ao lado do .zip.", parent=self.win)
        use = box.addButton("Abrir a pasta existente", QMessageBox.ButtonRole.AcceptRole)
        rep = box.addButton("Extrair de novo (substituir)", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return "use" if box.clickedButton() is use else "replace" if box.clickedButton() is rep else None

    def ask_missing(self, missing: list) -> dict | None:
        """Diálogo de ausentes; devolve {(seção, i): caminho ou None} ou None (cancelar)."""
        dlg = MissingFilesDialog(missing, self.win)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return dlg.result_paths

    def choose_and_open(self) -> bool:
        path = open_file(self.win, "Abrir projeto", "project", PROJECT_FILTER)
        return self.open(path) if path else False

    def open(self, path: str | Path, wait: bool = False) -> bool:
        if self.loading:
            self.win.statusBar().showMessage("Aguarde: um projeto está sendo aberto.", 6000)
            return False
        p = Path(path)
        try:
            if p.suffix.lower() == ".zip":
                if bundle_project_name(p) is None:
                    raise ProjectError("O .zip não contém um projeto do Jabuti.", p)
                dest = p.with_suffix("")
                inner = dest / str(bundle_project_name(p))
                if dest.exists() and any(dest.iterdir()):
                    choice = self.confirm_extract(dest)
                    if choice is None:
                        return False
                    p = inner if choice == "use" and inner.is_file() else extract_bundle(p, dest)
                else:
                    p = extract_bundle(p, dest)
            data, notes = read_project(p)
        except Exception as exc:  # noqa: BLE001
            show_error(self.win, exc, "Abrir projeto")
            return False
        base = p.parent
        found: dict[tuple[str, int], Path] = {}
        missing = []
        for section, i, ref in iter_refs(data):
            hit = resolve_ref(ref, base)
            if hit is None:
                missing.append((section, i, ref))
            else:
                found[(section, i)] = hit
        dangling: dict[str, list] = {}
        if missing:
            answer = self.ask_missing(missing)
            if answer is None:
                return False
            for section, i, ref in missing:
                loc = answer.get((section, i))
                if loc is not None:
                    found[(section, i)] = loc
                elif section == "tree":
                    show_error(self.win, ProjectError("Sem a árvore o projeto não pode ser aberto.", p),
                               "Abrir projeto")
                    return False
                else:
                    dangling.setdefault(section, []).append(ref)
        self._start(p, data, found, dangling, notes)
        if not wait:
            return True
        if self.loading:
            loop = QEventLoop()
            self.loaded.connect(loop.quit)
            if self.loading:
                loop.exec()
            self.loaded.disconnect(loop.quit)
        return self.path == p

    def _start(self, path: Path, data: dict, found: dict, dangling: dict, notes: list[str]) -> None:
        w = self.win
        self.loading = True
        self._data, self._found, self._notes = data, found, list(notes)
        self._pending_path = path
        self.dangling = dangling
        w.statusBar().showMessage(f"Abrindo projeto {path.name}…")
        # sessão anterior sai inteira
        w.gff_tab.clear()
        w.metadata_tab.clear()
        w.figure_panel.clear_tables()
        w.figure_panel.itol.clear_all()
        w.canvas.clear_selection()
        self._steps = [self._load_tree, self._load_metadata]
        self._steps += [lambda i=i: self._load_table(i) for i, _t in enumerate(data.get("tables") or [])]
        self._steps += [self._load_names, self._load_itol, self._load_gff, self._finish]
        QTimer.singleShot(0, self._next)

    def _next(self) -> None:
        if not self._steps:
            return
        step = self._steps.pop(0)
        try:
            waits = step()
        except Exception as exc:  # noqa: BLE001
            _log.exception("erro abrindo projeto")
            self._abort(exc)
            return
        if not waits:
            QTimer.singleShot(0, self._next)

    def _step_done(self, kind: str) -> None:
        if self.loading and self._waiting == kind:
            self._waiting = None
            QTimer.singleShot(0, self._next)

    def _abort(self, exc: BaseException) -> None:
        self.loading = False
        self._steps = []
        self._waiting = None
        show_error(self.win, exc, "Abrir projeto")
        self.update_title()
        self.loaded.emit(False)

    # etapas: devolvem True quando esperam um sinal de fim de leitura
    def _load_tree(self) -> bool:
        w = self.win
        if not w.tree_tab.load(self._found[("tree", 0)]):
            raise ProjectError("Não foi possível abrir a árvore do projeto.")
        note = w.tree_tab.apply_rooting_spec(self._data["tree"].get("rooting") or {})
        if note:
            self._notes.append(note)
        return False

    def _load_metadata(self) -> bool:
        md = self._data.get("metadata")
        p = self._found.get(("metadata", 0))
        if p is not None and self.win.metadata_tab.load(p) and isinstance(md, dict) and md.get("key_column"):
            combo = self.win.metadata_tab.key_combo
            if combo.findText(md["key_column"]) >= 0:
                combo.setCurrentText(md["key_column"])
        return False

    def _load_table(self, i: int) -> bool:
        p = self._found.get(("tables", i))
        if p is None:
            return False
        self._waiting = "table"
        self.win.figure_panel.load_table(p, wait=False)
        return True

    def _load_names(self) -> bool:
        p = self._found.get(("names", 0))
        if p is None:
            return False
        self._waiting = "table"
        self.win.figure_panel.load_name_table(p, wait=False)
        return True

    def _load_itol(self) -> bool:
        paths = [self._found[("itol", i)] for i in range(len((self._data.get("itol") or {}).get("files") or []))
                 if ("itol", i) in self._found]
        if not paths:
            return False
        # preferências (visível, cores, títulos) antes de importar: COLLAPSE respeita a visibilidade
        style = preset_from_dict(self._data.get("view") or {}).style
        self.win.figure_panel.itol.load_prefs(list(style.figure.itol))
        self._waiting = "itol"
        self.win.figure_panel.itol.import_files(paths, wait=False)
        return True

    def _load_gff(self) -> bool:
        files = (self._data.get("gff") or {}).get("files") or []
        paths = [self._found[("gff", i)] for i in range(len(files)) if ("gff", i) in self._found]
        if not paths:
            return False
        self._waiting = "gff"
        self.win.gff_tab.load_files(paths, wait=False)
        return self._waiting == "gff"          # leitura vazia termina na hora

    def _finish(self) -> bool:
        w = self.win
        data = self._data
        loaded = preset_from_dict(data.get("view") or {})
        notes = self._notes + w.apply_preset(loaded)
        # tabelas: mapeamentos manuais
        leaves = set(w.tree.leaf_names()) if w.tree is not None else set()
        by_name = {src.path.name if src.path else name: src for name, src in w.figure_panel.sources.items()}
        for i, t in enumerate(data.get("tables") or []):
            p = self._found.get(("tables", i))
            src = by_name.get(p.name) if p is not None else None
            if src is None:
                continue
            for key, leaf in (t.get("manual") or {}).items():
                if leaf in leaves and key in src.mapping.keys:
                    src.mapping.set(key, leaf)
        w.figure_panel.refresh_tables()
        # GFF: buscas, mapeamento manual e contexto
        g = data.get("gff") or {}
        gff = w.gff_tab
        gff.queries = []
        for q in g.get("queries") or []:
            try:
                gff.queries.append(GeneQuery(str(q["text"]), tuple(q.get("fields") or ()), bool(q.get("regex")),
                                             str(q.get("label") or "")))
            except (KeyError, TypeError):
                notes.append("uma busca de genes inválida foi ignorada")
        names = {x.name for x in gff.genomes}
        for genome, leaf in (g.get("manual") or {}).items():
            if genome in names and leaf in leaves:
                gff.set_mapping(genome, leaf)
        gff.refresh()
        gff._refresh_queries()
        ctx = g.get("context") or {}
        gff.ctx_n.setValue(int(ctx.get("n", gff.ctx_n.value())))
        idx = gff.ctx_anchor.findData(ctx.get("anchor"))
        if idx >= 0:
            gff.ctx_anchor.setCurrentIndex(idx)
        gff.ctx_enabled.setChecked(bool(ctx.get("enabled")))
        ex = data.get("export") or {}
        w.viz_tab.dpi.setValue(int(ex.get("png_dpi", w.viz_tab.dpi.value())))
        w.viz_tab.tiff_dpi.setValue(int(ex.get("tiff_dpi", w.viz_tab.tiff_dpi.value())))
        w.viz_tab.tiff_lzw.setChecked(bool(ex.get("tiff_lzw", w.viz_tab.tiff_lzw.isChecked())))
        w._live_timer.stop()
        self.loading = False
        self.path = self._pending_path
        w.generate()
        w._live_timer.stop()
        add_recent(self.path, "projects")
        self.mark_clean()
        skipped = sum(len(v) for v in self.dangling.values())
        msg = f"Projeto aberto: {self.path.name}" + (f" ({skipped} arquivo(s) ignorado(s))" if skipped else "")
        w.statusBar().showMessage(msg, 10000)
        if notes:
            show_error(w, Exception("Projeto aberto com avisos:\n• " + "\n• ".join(notes[:12])), "Abrir projeto")
        self.loaded.emit(True)
        return True


def project_from_argument(path: str | Path) -> bool:
    """O argumento é um projeto (``.jabuti`` ou ``.zip`` com projeto)?"""
    p = Path(path)
    return p.suffix.lower() == PROJECT_SUFFIX or (p.suffix.lower() == ".zip" and bundle_project_name(p) is not None)


__all__ = ["ProjectController", "MissingFilesDialog", "project_from_argument", "PROJECT_FILTER"]
