"""Leitura de GFF em segundo plano: loop de eventos livre, cancelar, caches."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

N_FILES = 100
GENES_PER_FILE = 3000   # ~6 mil linhas (gene + CDS) por arquivo, ~0,6 MB


def write_big_gff(path, idx: int, genes: int = GENES_PER_FILE) -> None:
    lines = ["##gff-version 3", f"##sequence-region contig_1 1 {genes * 1200}"]
    pos = 1
    for g in range(genes):
        end = pos + 900
        lt = f"S{idx:03d}_{g:05d}"
        name = "nifH" if g == 10 and idx % 3 == 0 else f"gene{g % 500}"
        strand = "+" if g % 2 else "-"
        lines.append(f"contig_1\tsyn\tgene\t{pos}\t{end}\t.\t{strand}\t.\tID=g{g};locus_tag={lt};gene={name}")
        lines.append(f"contig_1\tsyn\tCDS\t{pos}\t{end}\t.\t{strand}\t0\tID=c{g};Parent=g{g};"
                     f"product=synthetic protein {g % 700}")
        pos = end + 200
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture(scope="module")
def big_gffs(tmp_path_factory):
    d = tmp_path_factory.mktemp("big_gffs")
    paths = []
    for i in range(N_FILES):
        p = d / f"strain{i:03d}.gff3"
        write_big_gff(p, i)
        paths.append(p)
    return paths


@pytest.fixture
def tab(qtbot):
    from jabuti.views.gff_tab import GffTab

    t = GffTab()
    qtbot.addWidget(t)
    t.set_tree_leaves([f"Paraburkholderia_sp_strain{i:03d}" for i in range(N_FILES)])
    yield t
    t.shutdown()


def test_loading_does_not_block_event_loop(qtbot, tab, big_gffs):
    from PySide6.QtCore import QTimer

    ticks: list[float] = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    timer.start()
    progress_seen: list[int] = []
    tab.progress.valueChanged.connect(progress_seen.append)

    t0 = time.perf_counter()
    with qtbot.waitSignal(tab.loading_finished, timeout=180_000) as blocker:
        assert tab.load_files(big_gffs, wait=False) == 0   # devolve na hora
        assert tab.is_loading()
        assert tab.cancel_btn.isVisibleTo(tab) and tab.progress.isVisibleTo(tab)
        assert not tab.add_btn.isEnabled()
    elapsed = time.perf_counter() - t0
    timer.stop()

    new, cancelled = blocker.args
    assert new == N_FILES and not cancelled
    assert len(tab.genomes) == N_FILES and all(g.n_genes == GENES_PER_FILE for g in tab.genomes)
    assert sum(1 for v in tab.mapping.values() if v) == N_FILES      # casou por sufixo
    # a GUI continuou processando eventos durante toda a leitura
    during = [t for t in ticks if t - t0 < elapsed]
    gaps = [b - a for a, b in zip(during, during[1:])]
    assert len(during) > 20
    assert max(gaps) < 0.25, f"maior pausa do loop de eventos: {max(gaps):.3f}s"  # medido: ~0,05 s
    assert len(set(progress_seen)) > 10                                 # progresso incremental
    assert not tab.is_loading() and tab.add_btn.isEnabled() and not tab.cancel_btn.isVisibleTo(tab)


def test_cancel_stops_early(qtbot, tab, big_gffs):
    with qtbot.waitSignal(tab.loading_finished, timeout=180_000) as blocker:
        tab.load_files(big_gffs, wait=False)
        qtbot.waitUntil(lambda: tab.progress.value() >= 3, timeout=60_000)
        tab.cancel_btn.click()
    new, cancelled = blocker.args
    assert cancelled
    assert 3 <= new < N_FILES
    assert len(tab.genomes) == new
    assert tab.add_btn.isEnabled()


def test_unchanged_files_are_not_reparsed(qtbot, tab, big_gffs, monkeypatch):
    from jabuti.views import gff_tab as mod

    subset = big_gffs[:5]
    assert tab.load_files(subset) == 5
    calls: list[str] = []
    real = mod.parse_gff3
    monkeypatch.setattr(mod, "parse_gff3", lambda p, stop=None: calls.append(str(p)) or real(p, stop))

    assert tab.load_files(subset) == 0                  # já carregados e iguais
    assert calls == [] and not tab.is_loading()

    tab.table.selectRow(0)
    tab.remove_selected()
    assert len(tab.genomes) == 4
    assert tab.load_files([subset[0]]) == 1             # volta do cache, sem reler
    assert calls == []

    # arquivo alterado: só ele é relido, mantendo nome e mapeamento
    target = next(g for g in tab.genomes if g.path == subset[1])
    name = target.name
    leaf = tab.mapping[name]
    time.sleep(0.01)
    write_big_gff(subset[1], 1001, genes=50)   # 1001 % 3 != 0: sem nifH
    with qtbot.waitSignal(tab.loading_finished, timeout=60_000):
        tab.reload_changed()
    assert calls == [str(subset[1])]
    g = next(g for g in tab.genomes if g.name == name)
    assert g.n_genes == 50 and tab.mapping[name] == leaf


def test_mapping_change_does_not_redo_searches(qtbot, tab, big_gffs, monkeypatch):
    from jabuti.parsers.gff import GeneQuery
    from jabuti.views import gff_tab as mod

    tab.load_files(big_gffs[:6])
    tab.queries.append(GeneQuery("nifH"))
    first = tab.matrix()
    assert sum(1 for n in first["nifH"].values() if n) == 2         # strain000 e strain003

    calls: list[int] = []
    real = mod.find_genes
    monkeypatch.setattr(mod, "find_genes", lambda g, q: calls.append(1) or real(g, q))
    name = tab.genomes[0].name
    tab.set_mapping(name, None)
    tab.set_mapping(name, "Paraburkholderia_sp_strain000")
    for _ in range(3):
        tab.matrix()
    assert calls == []                                  # tudo do cache de buscas
    tab.queries.append(GeneQuery("synthetic protein 5"))
    tab.matrix()
    assert len(calls) == 6                              # só a busca nova, uma vez por genoma


def test_parse_can_be_cancelled_mid_file(big_gffs):
    from jabuti.parsers.gff import LoadCancelled, parse_gff3

    checks = {"n": 0}

    def stop() -> bool:
        checks["n"] += 1
        return checks["n"] > 2      # deixa começar e para no meio do arquivo

    with pytest.raises(LoadCancelled):
        parse_gff3(big_gffs[0], stop)
    assert checks["n"] == 3


def test_close_window_while_loading(qtbot, big_gffs, monkeypatch):
    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    win = MainWindow()
    qtbot.addWidget(win)
    win.gff_tab.load_files(big_gffs, wait=False)
    qtbot.waitUntil(lambda: win.gff_tab.progress.value() >= 1, timeout=60_000)
    win.close()                                         # cancela e espera a thread
    assert not any(w.is_running() for w in win.gff_tab._loaders)
