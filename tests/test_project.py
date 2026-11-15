"""Projeto .jabuti: ida e volta (mesma cena), pasta movida, ausentes, versões, pacote .zip."""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from jabuti.models.itol_apply import dataset_entries  # noqa: E402
from jabuti.parsers.gff import GeneQuery  # noqa: E402
from jabuti.presets import preset_from_dict  # noqa: E402
from jabuti.project import (  # noqa: E402
    PROJECT_VERSION,
    ProjectError,
    file_ref,
    migrate,
    read_project,
    resolve_ref,
)
from scene_baseline import same, signature  # noqa: E402

EX = Path("examples")
ROB = "Robbsia_andropogonis_LMG2129"
A01 = "Paraburkholderia_phymatum_A01"


# ------------------------------------------------------------------ modelo (sem Qt)
def test_refs_relative_first_then_absolute(tmp_path):
    base = tmp_path / "proj"
    (base / "dados").mkdir(parents=True)
    f = base / "dados" / "a.nwk"
    f.write_text("(a,b);")
    ref = file_ref(f, base)
    assert ref["rel"] == "dados/a.nwk" and ref["abs"] == str(f) and ref["name"] == "a.nwk"
    moved = tmp_path / "movido"
    shutil.move(str(base), moved)
    assert resolve_ref(ref, moved) == moved / "dados" / "a.nwk"          # relativo vence
    assert resolve_ref({"abs": str(moved / "dados" / "a.nwk")}, tmp_path) is not None
    assert resolve_ref(ref, tmp_path / "nada") is None


def test_versions_old_migrates_new_refuses(tmp_path):
    old = {"format": "jabuti-project", "version": 0, "tree_file": {"rel": "t.nwk"}, "preset": {"version": 1}}
    data, notes = migrate(dict(old))
    assert data["version"] == PROJECT_VERSION and data["tree"]["file"] == {"rel": "t.nwk"} and "view" in data
    assert notes and "formato 0" in notes[0]
    new = tmp_path / "novo.jabuti"
    new.write_text(json.dumps({"format": "jabuti-project", "version": PROJECT_VERSION + 1, "tree": {"file": "x"}}))
    with pytest.raises(ProjectError, match="versão mais nova"):
        read_project(new)
    other = tmp_path / "outro.jabuti"
    other.write_text('{"app": "jabuti", "version": 1}')
    with pytest.raises(ProjectError, match="não é um projeto"):
        read_project(other)
    bad = tmp_path / "ruim.jabuti"
    bad.write_text("{nada")
    with pytest.raises(ProjectError, match="inválido"):
        read_project(bad)


# ------------------------------------------------------------------ janela
@pytest.fixture
def make_window(qtbot, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    shown: list[str] = []
    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)

    def make():  # type: ignore[no-untyped-def]
        w = MainWindow()
        w.shown = shown
        qtbot.addWidget(w)
        return w
    return make


def _workdir(tmp_path: Path) -> Path:
    """Cópia dos exemplos numa pasta de trabalho (o projeto mora nela)."""
    work = tmp_path / "trabalho"
    d = work / "dados"
    (d / "gff").mkdir(parents=True)
    (d / "itol").mkdir()
    shutil.copy(EX / "paraburkholderia_40.treefile", d)
    shutil.copy(EX / "metadata.tsv", d)
    shutil.copy(EX / "traits.tsv", d)
    for n in ("A00", "A01", "A02", "A03", "A05"):
        shutil.copy(EX / "gff" / f"{n}.gff3", d / "gff")
    for n in ("tree_colors", "colorstrip", "binary", "symbol", "text", "collapse"):
        shutil.copy(EX / "itol" / f"{n}.txt", d / "itol")
    (d / "nomes.tsv").write_text(f"original\texibido\n{ROB}\tRobbsia (externo)\n", encoding="utf-8")
    return work


def _build(w, work: Path) -> None:  # type: ignore[no-untyped-def]
    d = work / "dados"
    assert w.open_tree(d / "paraburkholderia_40.treefile")
    tt = w.tree_tab
    tt.rb_out.setChecked(True)
    tt.outgroup.setCurrentText(ROB)
    assert tt.apply_rooting()
    assert w.metadata_tab.load(d / "metadata.tsv")
    fp = w.figure_panel
    assert fp.load_table(d / "traits.tsv", wait=True)
    fp.add_bar()
    src = fp.sources["traits.tsv"]
    key = next(k for k in src.mapping.keys if src.mapping.mapping.get(k) == A01)
    src.mapping.set(key, "Paraburkholderia_tropica_A02")         # mapeamento manual (A02 perde a linha)
    assert fp.load_name_table(d / "nomes.tsv", wait=True)
    fp.itol.import_files(sorted((d / "itol").glob("*.txt")), wait=True)
    strip = next(e for e in fp.itol.entries if e.dataset.kind == "DATASET_COLORSTRIP")
    orig = dataset_entries(strip.dataset)[0][0]
    fp.itol.set_color(strip.key, orig, "#123456")
    strip.title = "Faixa editada"
    gff = w.gff_tab
    gff.load_files(sorted((d / "gff").glob("*.gff3")), wait=True)
    gff.queries = [GeneQuery("nitrogenase iron protein", ("product",), False),
                   GeneQuery("nod[A-Z]", ("name", "gene"), True, "nod")]
    gff.set_mapping("A05", "Paraburkholderia_xenovorans_B20")
    gff._refresh_queries()
    gff.ctx_enabled.setChecked(True)
    gff.ctx_n.setValue(2)
    w.viz_tab.dpi.setValue(450)
    # estilo, clados, edições e grupos pelo mesmo caminho dos presets
    data = w.collect_preset()
    st = data["style"]
    st["metadata"]["color_by"] = "habitat"
    st["metadata"]["strips"] = ["symbiont"]
    st["legend"]["in_figure"] = True
    st["figure"]["names"]["underscore_to_space"] = True
    data["edits"]["ladderize"] = "asc"
    data["edits"]["hidden"] = ["Paraburkholderia_hospita_A09"]
    data["edits"]["rotations"] = [["Paraburkholderia_xenovorans_A00", "Paraburkholderia_phymatum_A01"]]
    data["edits"]["highlights"] = [{"leaves": ["Paraburkholderia_tropica_A02"], "color": "#ffe066", "alpha": 0.5,
                                    "outline": False, "outline_width": 1.0, "thickness": 1.0}]
    data["label_groups"] = {"show_in_legend": True, "groups": [
        {"name": "tipo", "leaves": ["Paraburkholderia_terrae_B28"], "source": "manual", "visible": True,
         "look": {"bold": True, "text_color": "#8e44ad"}}]}
    w.apply_preset(preset_from_dict(data))
    w.style_panel.detect()
    w.generate()


def _norm(data: dict) -> dict:
    return json.loads(json.dumps(data, sort_keys=True))


def test_roundtrip_same_scene_and_state(make_window, tmp_path):
    work = _workdir(tmp_path)
    a = make_window()
    _build(a, work)
    sig_a = signature(a.renderer.scene)
    path = a.project._write(work / "figura.jabuti")
    assert path == work / "figura.jabuti" and not a.project.is_dirty()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["format"] == "jabuti-project" and raw["version"] == PROJECT_VERSION
    assert raw["tree"]["rooting"] == {"mode": "outgroup", "leaf": ROB}
    assert raw["tree"]["file"]["rel"] == "dados/paraburkholderia_40.treefile"
    assert len(raw["gff"]["files"]) == 5 and len(raw["itol"]["files"]) == 6 and raw["export"]["png_dpi"] == 450

    b = make_window()
    assert b.open_project(path, wait=True)
    assert not b.shown, b.shown
    assert same(signature(b.renderer.scene), sig_a) is None
    assert _norm(b.project.collect(base=work)) == _norm(a.project.collect(base=work))
    assert b.windowTitle() == "figura.jabuti[*] — Jabuti" and not b.isWindowModified()
    # itol: ordem, título e cor editados; GFF: buscas, manual e contexto
    assert [p.name for p in b.figure_panel.itol.paths()] == [p.name for p in a.figure_panel.itol.paths()]
    assert any(e.title == "Faixa editada" and "#123456" in e.colors.values() for e in b.figure_panel.itol.entries)
    assert [q.title for q in b.gff_tab.queries] == ["nitrogenase iron protein", "nod"]
    assert b.gff_tab.mapping["A05"] == "Paraburkholderia_xenovorans_B20" and "A05" in b.gff_tab.manual
    assert b.gff_tab.ctx_enabled.isChecked() and b.gff_tab.ctx_n.value() == 2
    assert b.viz_tab.dpi.value() == 450


def test_moved_folder_still_opens(make_window, tmp_path):
    work = _workdir(tmp_path)
    a = make_window()
    _build(a, work)
    sig = signature(a.renderer.scene)
    a.project._write(work / "figura.jabuti")
    moved = tmp_path / "outro_lugar" / "copia"
    moved.parent.mkdir()
    shutil.move(str(work), moved)                      # o absoluto não existe mais
    b = make_window()
    assert b.open_project(moved / "figura.jabuti", wait=True)
    assert not b.shown and same(signature(b.renderer.scene), sig) is None
    assert b.tree_tab.path == moved / "dados" / "paraburkholderia_40.treefile"


def test_missing_files_locate_and_ignore(make_window, tmp_path, monkeypatch):
    work = _workdir(tmp_path)
    a = make_window()
    _build(a, work)
    path = a.project._write(work / "figura.jabuti")
    elsewhere = tmp_path / "achei"
    elsewhere.mkdir()
    shutil.move(str(work / "dados" / "traits.tsv"), elsewhere / "traits.tsv")      # vai ser localizado
    (work / "dados" / "gff" / "A02.gff3").unlink()                                  # vai ser ignorado
    b = make_window()
    asked = []

    def answer(missing):  # type: ignore[no-untyped-def]
        asked.extend((s, Path(r["name"]).name) for s, _i, r in missing)
        return {(s, i): (elsewhere / "traits.tsv" if s == "tables" else None) for s, i, _r in missing}
    monkeypatch.setattr(b.project, "ask_missing", answer)
    assert b.open_project(path, wait=True)
    assert sorted(asked) == [("gff", "A02.gff3"), ("tables", "traits.tsv")]
    assert "traits.tsv" in b.figure_panel.sources and len(b.gff_tab.genomes) == 4
    assert b.figure_panel.bars and b.figure_panel.bars[0].source == "traits.tsv"
    # o ignorado continua no projeto (para não perder a referência)
    data = b.project.collect(base=work)
    assert any(r.get("name") == "A02.gff3" for r in data["gff"]["files"])
    # cancelar a abertura não mexe na sessão aberta
    c = make_window()
    monkeypatch.setattr(c.project, "ask_missing", lambda missing: None)
    assert not c.open_project(path, wait=True) and c.tree is None


def test_missing_tree_cannot_be_ignored(make_window, tmp_path, monkeypatch):
    work = _workdir(tmp_path)
    a = make_window()
    assert a.open_tree(work / "dados" / "paraburkholderia_40.treefile")
    path = a.project._write(work / "so_arvore.jabuti")
    (work / "dados" / "paraburkholderia_40.treefile").unlink()
    b = make_window()
    monkeypatch.setattr(b.project, "ask_missing", lambda missing: {(s, i): None for s, i, _r in missing})
    assert not b.open_project(path, wait=True)
    assert b.tree is None and any("Sem a árvore" in m for m in b.shown)


def test_newer_version_warns_without_breaking(make_window, tmp_path):
    p = tmp_path / "futuro.jabuti"
    p.write_text(json.dumps({"format": "jabuti-project", "version": 99, "tree": {"file": {"rel": "x.nwk"}}}))
    w = make_window()
    assert not w.open_project(p, wait=True)
    assert any("versão mais nova" in m for m in w.shown) and w.tree is None


def test_bundle_copies_small_data_skips_gff_and_has_no_absolute_paths(make_window, tmp_path, monkeypatch):
    work = _workdir(tmp_path)
    a = make_window()
    _build(a, work)
    sig = signature(a.renderer.scene)
    a.project._write(work / "figura.jabuti")
    seen = {}
    monkeypatch.setattr(a.project, "confirm_bundle",
                        lambda copied, left: seen.update(copied=copied, left=left) or True)
    (tmp_path / "envio").mkdir()
    res = a.project.save_bundle(tmp_path / "envio" / "figura.zip")
    assert res is not None and res.path.is_file()
    assert all(why.startswith("GFF3") for _n, why in seen["left"]) and len(seen["left"]) == 5
    with zipfile.ZipFile(res.path) as z:
        names = z.namelist()
        text = z.read("figura.jabuti").decode("utf-8")
    assert "figura.jabuti" in names and "dados/paraburkholderia_40.treefile" in names
    assert "dados/traits.tsv" in names and "dados/nomes.tsv" in names and "dados/tree_colors.txt" in names
    assert not any(n.endswith(".gff3") for n in names)
    # nenhum caminho do computador: nem "abs", nem a pasta temporária, nem a pasta pessoal
    data = json.loads(text)
    assert '"abs"' not in text and str(tmp_path) not in text and str(Path.home()) not in text
    assert data["tree"]["file"] == {"name": "paraburkholderia_40.treefile", "rel": "dados/paraburkholderia_40.treefile"}
    assert all(set(r) == {"name"} for r in data["gff"]["files"])           # GFFs: só o nome
    # abrir o .zip: extrai ao lado e abre; GFFs aparecem como ausentes (ignorados aqui)
    b = make_window()
    monkeypatch.setattr(b.project, "ask_missing", lambda missing: {(s, i): None for s, i, _r in missing})
    assert b.open_project(res.path, wait=True)
    assert b.project.path == tmp_path / "envio" / "figura" / "figura.jabuti"
    assert b.tree is not None and "traits.tsv" in b.figure_panel.sources and len(b.figure_panel.itol.entries) == 6
    sig_b = signature(b.renderer.scene)
    assert sig_b and len(sig_b) <= len(sig)          # sem GFF: sem as colunas de genes


def test_dirty_title_and_ask_on_close(make_window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    work = _workdir(tmp_path)
    w = make_window()
    assert w.open_tree(work / "dados" / "paraburkholderia_40.treefile")
    assert w.windowTitle() == "paraburkholderia_40.treefile[*] — Jabuti" and not w.isWindowModified()
    w.style_panel.edits.ladderize = "left"
    w.render_live()
    assert w.isWindowModified() and w.project.is_dirty()
    w.style_panel.edits.ladderize = "none"                       # desfazer à mão tira o asterisco
    w.render_live()
    assert not w.isWindowModified()
    w.style_panel.edits.ladderize = "left"
    w.render_live()
    w.ask_on_close = True
    clicked = {"which": "Cancelar"}

    def fake_exec(box):  # type: ignore[no-untyped-def]
        for b in box.buttons():
            if b.text() == clicked["which"]:
                box._clicked = b
        return 0
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: getattr(box, "_clicked", None))
    assert w.maybe_save() is False                               # Cancelar
    clicked["which"] = "Descartar"
    assert w.maybe_save() is True
    clicked["which"] = "Salvar"
    monkeypatch.setattr("jabuti.views.project_io.save_file", lambda *a, **k: str(work / "salvo.jabuti"))
    assert w.maybe_save() is True and (work / "salvo.jabuti").is_file() and not w.project.is_dirty()
    assert w.windowTitle() == "salvo.jabuti[*] — Jabuti"


def test_cli_and_drop_open_project(make_window, tmp_path, qtbot):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    from jabuti.app import Launcher
    from jabuti.settings import recent_files

    work = _workdir(tmp_path)
    a = make_window()
    assert a.open_tree(work / "dados" / "paraburkholderia_40.treefile")
    path = a.project._write(work / "p.jabuti")
    launcher = Launcher(["jabuti", str(path)], use_splash=False)
    launcher.start()
    win = launcher.window
    qtbot.addWidget(win)
    qtbot.waitUntil(lambda: win.project.path == path and not win.project.loading, timeout=10000)
    assert win.tree is not None and recent_files("projects")[0] == str(path.resolve())
    b = make_window()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    ev = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier)
    b.dropEvent(ev)
    qtbot.waitUntil(lambda: b.project.path == path and not b.project.loading, timeout=10000)
    assert b.tree is not None


def test_menu_actions_and_shortcuts(make_window):
    from PySide6.QtGui import QKeySequence

    w = make_window()
    act = w.actions_by_name
    assert act["save_project"].shortcut() == QKeySequence(QKeySequence.StandardKey.Save)
    assert act["open_project"].shortcut() == QKeySequence("Ctrl+Shift+O")
    assert not act["save_project_as"].shortcut().isEmpty() and "save_bundle" in act
    shortcuts = [a.shortcut().toString() for a in act.values() if not a.shortcut().isEmpty()]
    assert len(shortcuts) == len(set(shortcuts))


def test_no_project_files_tracked_in_repo():
    import subprocess

    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=Path(__file__).parent.parent)
    tracked = out.stdout.splitlines()
    assert not [f for f in tracked if f.endswith((".jabuti", ".jabuti.zip"))]
    ignore = (Path(__file__).parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "*.jabuti" in ignore


def test_missing_dialog_buttons(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    from jabuti.views import project_io

    target = tmp_path / "achado.tsv"
    target.write_text("a\tb\n")
    monkeypatch.setattr(project_io, "open_file", lambda *a, **k: str(target))
    missing = [("tree", 0, {"name": "t.nwk"}), ("tables", 0, {"name": "x.tsv", "abs": "/outro/x.tsv"}),
               ("gff", 0, {"name": "g.gff3"})]
    dlg = project_io.MissingFilesDialog(missing)
    qtbot.addWidget(dlg)
    buttons = [b for b in dlg.findChildren(QPushButton) if b.text() in ("Localizar…", "Ignorar")]
    assert [b.text() for b in buttons].count("Localizar…") == 3
    assert [b.text() for b in buttons].count("Ignorar") == 2          # a árvore não pode ser ignorada
    next(b for b in buttons if b.text() == "Localizar…").click()        # árvore
    loc = [b for b in buttons if b.text() == "Localizar…"]
    loc[1].click()                                                       # tabela
    [b for b in buttons if b.text() == "Ignorar"][1].click()           # GFF
    assert dlg.result_paths == {("tree", 0): target, ("tables", 0): target, ("gff", 0): None}
    assert dlg.status[("gff", 0)].text() == "ignorado"
