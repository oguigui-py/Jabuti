"""Aba "GFF": carregar GFF3 (um por genoma), mapear para folhas e buscar genes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jabuti.models.annotations import presence_matrix
from jabuti.parsers.gff import GeneQuery, Genome, file_signature, find_genes, genome_name_from_path, parse_gff3
from jabuti.parsers.names import match_names
from jabuti.views.errors import show_error
from jabuti.workers import FileLoader

GFF_FILTER = "GFF3 (*.gff *.gff3 *.gff.gz *.gff3.gz);;Todos (*)"
NO_LEAF = "— sem folha —"
PREVIEW_LIMIT = 300
COL_FILE, COL_GENES, COL_LEAF, COL_STATUS = range(4)


class GffTab(QWidget):
    changed = Signal()          # dados mudaram -> redesenhar
    status_message = Signal(str)
    loading_finished = Signal(int, bool)   # genomas novos, cancelado?

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.genomes: list[Genome] = []
        self.mapping: dict[str, str | None] = {}   # genome.name -> folha
        self.manual: set[str] = set()               # mapeamentos editados à mão
        self.leaves: list[str] = []
        self.queries: list[GeneQuery] = []
        self._filling = False
        self._cache: dict[str, Genome] = {}          # caminho -> genoma lido (com mtime/tamanho)
        self._search_cache: dict[tuple, list] = {}
        self._worker: FileLoader | None = None   # leitura em andamento
        self._loaders: list[FileLoader] = []     # mantidos vivos até a thread terminar
        self._load_errors: list[str] = []
        self._load_new = 0
        self._skipped = 0

        # --- arquivos
        add_btn = QPushButton("Adicionar GFF3…")
        add_btn.clicked.connect(self._choose_files)
        self.add_btn = add_btn
        self.reload_btn = QPushButton("Recarregar")
        self.reload_btn.setToolTip("Relê só os arquivos modificados desde a leitura")
        self.reload_btn.clicked.connect(self.reload_changed)
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_loading)
        rm_btn = QPushButton("Remover")
        rm_btn.clicked.connect(self.remove_selected)
        clear_btn = QPushButton("Limpar")
        clear_btn.clicked.connect(self.clear)
        auto_btn = QPushButton("Mapear automaticamente")
        auto_btn.setToolTip("Casa nome do arquivo e folha (ignora maiúsculas, _ / espaço / . / -, e prefixos únicos)")
        auto_btn.clicked.connect(lambda: self.auto_map(reset=True))
        row1 = QHBoxLayout()
        row1.addWidget(add_btn)
        row1.addWidget(rm_btn)
        row1.addWidget(clear_btn)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMinimumWidth(60)
        self.progress.setTextVisible(True)
        self.cancel_btn.setMinimumWidth(self.cancel_btn.sizeHint().width())
        self.problems_box = QGroupBox("Problemas na leitura")
        self.problems = QPlainTextEdit()
        self.problems.setReadOnly(True)
        self.problems.setMaximumHeight(110)
        QVBoxLayout(self.problems_box).addWidget(self.problems)
        self.problems_box.setVisible(False)
        self.summary = QLabel("Nenhum GFF carregado. O nome do arquivo é usado para achar a folha.")
        self.summary.setWordWrap(True)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Arquivo", "Genes", "Folha", ""])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(COL_LEAF, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(COL_GENES, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(140)

        # --- busca
        search_box = QGroupBox("Buscar genes")
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("ex.: nifH, nitrogenase, BXE_0001, ^nod[ABC]$")
        self.query_edit.returnPressed.connect(self.add_query)
        self.f_product = QCheckBox("produto")
        self.f_name = QCheckBox("nome/gene")
        self.f_locus = QCheckBox("locus_tag")
        for cb in (self.f_product, self.f_name, self.f_locus):
            cb.setChecked(True)
        self.f_regex = QCheckBox("regex")
        fields_row = QGridLayout()
        for i, cb in enumerate((self.f_product, self.f_name, self.f_locus, self.f_regex)):
            fields_row.addWidget(cb, i // 2, i % 2)
        add_q = QPushButton("Adicionar coluna")
        add_q.clicked.connect(self.add_query)
        prev_q = QPushButton("Prévia")
        prev_q.setToolTip("Mostra os genes encontrados sem adicionar coluna")
        prev_q.clicked.connect(lambda: self.show_preview(self._current_query()))
        qrow = QVBoxLayout()
        qrow.addWidget(self.query_edit)
        qbtn_row = QHBoxLayout()
        qbtn_row.addWidget(prev_q)
        qbtn_row.addWidget(add_q)
        qrow.addLayout(qbtn_row)

        self.query_list = QListWidget()
        self.query_list.setMaximumHeight(120)
        self.query_list.currentRowChanged.connect(self._query_selected)
        rm_q = QPushButton("Remover coluna")
        rm_q.clicked.connect(self.remove_query)
        up_q = QPushButton("↑")
        dn_q = QPushButton("↓")
        up_q.clicked.connect(lambda: self.move_query(-1))
        dn_q.clicked.connect(lambda: self.move_query(1))
        qbtns = QHBoxLayout()
        qbtns.addWidget(rm_q)
        qbtns.addWidget(up_q)
        qbtns.addWidget(dn_q)
        qbtns.addStretch(1)

        self.preview_label = QLabel("")
        self.preview = QTableWidget(0, 4)
        self.preview.setHorizontalHeaderLabels(["Genoma", "locus_tag", "gene", "produto"])
        self.preview.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.preview.verticalHeader().setVisible(False)
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setMinimumHeight(140)

        sl = QVBoxLayout(search_box)
        sl.addLayout(qrow)
        sl.addLayout(fields_row)
        sl.addWidget(QLabel("Colunas do heatmap (ordem = da árvore para fora):"))
        sl.addWidget(self.query_list)
        sl.addLayout(qbtns)
        sl.addWidget(self.preview_label)
        sl.addWidget(self.preview)

        ctx_box = QGroupBox("Contexto gênico (layout retangular)")
        self.ctx_enabled = QCheckBox("Mostrar vizinhos do gene âncora")
        self.ctx_enabled.toggled.connect(lambda _on: self.changed.emit())
        self.ctx_anchor = QComboBox()
        self.ctx_anchor.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.ctx_n = QSpinBox()
        self.ctx_n.setRange(1, 15)
        self.ctx_n.setValue(3)
        self.ctx_n.setPrefix("± ")
        self.ctx_n.setSuffix(" genes")
        self.ctx_n.valueChanged.connect(lambda _v: self.changed.emit())
        cl = QFormLayout(ctx_box)
        cl.addRow(self.ctx_enabled)
        cl.addRow("Âncora:", self.ctx_anchor)
        cl.addRow("Vizinhos:", self.ctx_n)
        ctx_hint = QLabel("Usa o primeiro gene que casa com a coluna escolhida. A janela é espelhada para o "
                          "âncora apontar sempre para a direita; genes que casam com outras colunas "
                          "ficam com a cor delas.")
        ctx_hint.setWordWrap(True)
        ctx_hint.setStyleSheet("color: #888;")
        cl.addRow(ctx_hint)

        lay = QVBoxLayout(self)
        lay.addLayout(row1)
        auto_row = QHBoxLayout()
        auto_row.addWidget(auto_btn, 1)
        auto_row.addWidget(self.reload_btn)
        lay.addLayout(auto_row)
        prog_row = QHBoxLayout()
        prog_row.addWidget(self.progress, 1)
        prog_row.addWidget(self.cancel_btn)
        lay.addLayout(prog_row)
        lay.addWidget(self.problems_box)
        lay.addWidget(self.summary)
        lay.addWidget(self.table)
        lay.addWidget(search_box)
        lay.addWidget(ctx_box)
        lay.addStretch(1)

    # ------------------------------------------------------------ arquivos
    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Adicionar GFF3", "", GFF_FILTER)
        if paths:
            self.load_files(paths)

    # ------------------------------------------------- leitura em 2º plano
    def is_loading(self) -> bool:
        return self._worker is not None

    def load_files(self, paths: list[str | Path], wait: bool = True) -> int:
        """Lê GFF3 numa thread separada (a janela continua respondendo).

        Arquivos já carregados e sem alteração não são relidos; os alterados são relidos e
        substituem a versão anterior (mantendo nome e mapeamento). Com ``wait=True`` espera
        terminar (processando eventos) e devolve quantos genomas entraram; com ``wait=False``
        devolve na hora (o resultado chega por ``loading_finished``).
        """
        if self.is_loading():
            self.status_message.emit("Aguarde a leitura em andamento (ou clique em Cancelar).")
            return 0
        self._load_errors = []
        self._load_new = 0
        to_parse: list[Path] = []
        skipped = 0
        loaded_by_path = {g.key: g for g in self.genomes}
        seen: set[str] = set()
        for raw in paths:
            path = Path(raw)
            key = self._key(path)
            if key in seen:            # mesmo arquivo repetido na seleção
                continue
            seen.add(key)
            try:
                sig = file_signature(path)
            except OSError:
                to_parse.append(path)  # o parser gera a mensagem de "não encontrado"
                continue
            path = Path(key)  # a thread recebe o caminho já resolvido (a GUI não refaz isso)
            current = loaded_by_path.get(key)
            if current is not None and (current.mtime_ns, current.size) == sig:
                skipped += 1           # já carregado e igual
                continue
            cached = self._cache.get(key)
            if current is None and cached is not None and (cached.mtime_ns, cached.size) == sig:
                cached.key = key
                self._add_genome(cached)   # já lido antes (ex.: removido e readicionado)
                continue
            to_parse.append(path)
        self._skipped = skipped
        if not to_parse:
            self._finish_loading(False)
            return self._load_new
        self.progress.setRange(0, len(to_parse))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.add_btn.setEnabled(False)
        self.reload_btn.setEnabled(False)
        worker = FileLoader(to_parse, parse_gff3)
        # QueuedConnection explícita: os slots SEMPRE rodam na thread da GUI
        q = Qt.ConnectionType.QueuedConnection
        worker.progress.connect(self._on_progress, q)
        worker.items.connect(self._on_items, q)
        worker.finished.connect(self._finish_loading, q)
        self._worker = worker
        self._loaders = [w for w in self._loaders if w.is_running()] + [worker]
        worker.start()
        if wait:
            loop = QEventLoop()
            self.loading_finished.connect(loop.quit)
            if self.is_loading():
                loop.exec()
            self.loading_finished.disconnect(loop.quit)
        return self._load_new

    def cancel_loading(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status_message.emit("Cancelando a leitura…")

    def reload_changed(self) -> int:
        """Relê só os GFFs cujo arquivo mudou desde a leitura."""
        changed = []
        for g in self.genomes:
            try:
                if file_signature(g.path) != (g.mtime_ns, g.size):
                    changed.append(g.path)
            except OSError:
                self._load_errors.append(f"Arquivo: {g.path.name}\nNão encontrado (foi movido ou apagado?).")
        if not changed:
            self.status_message.emit("Nenhum GFF foi alterado desde a leitura.")
            return 0
        return self.load_files(changed, wait=False) or len(changed)

    def shutdown(self, timeout_ms: int = 5000) -> None:
        """Cancela e espera as threads (ao fechar a janela)."""
        if self._worker is not None:
            self._worker.cancel()
        for worker in self._loaders:
            worker.cancel()
            worker.join(timeout_ms / 1000)
        self._loaders = [w for w in self._loaders if w.is_running()]

    @staticmethod
    def _key(path: str | Path) -> str:
        try:
            return str(Path(path).resolve())
        except OSError:
            return str(path)

    @Slot(int, int, str)
    def _on_progress(self, done: int, total: int, name: str) -> None:
        self.progress.setValue(done)
        self.progress.setFormat("%v/%m")  # o nome do arquivo vai na barra de status (cabe melhor)
        if name:
            self.status_message.emit(f"Lendo {name} ({done + 1}/{total})…")
            self.progress.setToolTip(name)

    @Slot(list)
    def _on_items(self, items: list) -> None:
        for ok, path, payload in items:
            if ok:
                self._on_item_loaded(path, payload)
            else:
                self._load_errors.append(payload)

    def _on_item_loaded(self, path: str, genome: Genome) -> None:
        key = path                    # já resolvido em load_files
        genome.key = key
        self._cache[key] = genome
        for i, old in enumerate(self.genomes):   # arquivo alterado: substitui no lugar
            if old.key == key:
                genome.name = old.name
                self.genomes[i] = genome
                self._drop_search_cache(old)
                return
        self._add_genome(genome)

    def _add_genome(self, genome: Genome) -> None:
        existing = {g.name for g in self.genomes}
        base, n = genome_name_from_path(genome.path), 2
        genome.name = base
        while genome.name in existing:  # mesmo nome de arquivo em pastas diferentes
            genome.name = f"{base}_{n}"
            n += 1
        self.genomes.append(genome)
        self._load_new += 1

    @Slot(bool)
    def _finish_loading(self, cancelled: bool) -> None:
        self._worker = None
        try:
            self.progress.setVisible(False)
            self.cancel_btn.setVisible(False)
            self.add_btn.setEnabled(True)
            self.reload_btn.setEnabled(True)
            self.auto_map(reset=False)
            self._show_problems()
            parts = [f"{self._load_new} GFF3 carregado(s)"]
            if self._skipped:
                parts.append(f"{self._skipped} já estava(m) carregado(s) sem alteração")
            if self._load_errors:
                parts.append(f"{len(self._load_errors)} com erro (veja “Problemas na leitura”)")
            if cancelled:
                parts.append("leitura cancelada")
            self.status_message.emit("; ".join(parts) + ".")
        finally:
            # sempre sinaliza o fim (senão load_files(wait=True) ficaria esperando para sempre)
            self.loading_finished.emit(self._load_new, cancelled)

    def _show_problems(self) -> None:
        lines = []
        for msg in self._load_errors:
            lines.append("✗ " + msg.replace("\n", " — "))
        warned = [g for g in self.genomes if g.warnings]
        for g in warned:
            lines.append(f"! {g.name}: " + " | ".join(g.warnings[:3]) + (" …" if len(g.warnings) > 3 else ""))
        self.problems.setPlainText("\n".join(lines))
        self.problems_box.setVisible(bool(lines))
        self.problems_box.setTitle(f"Problemas na leitura ({len(self._load_errors)} erro(s), "
                                   f"{len(warned)} arquivo(s) com avisos)")

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            g = self.genomes.pop(r)
            self.mapping.pop(g.name, None)
            self.manual.discard(g.name)  # a leitura fica no cache: readicionar não relê
        if rows:
            self.refresh()
            self.changed.emit()

    def clear(self) -> None:
        self.genomes.clear()
        self.mapping.clear()
        self.manual.clear()
        self.refresh()
        self.changed.emit()

    # ---------------------------------------------------------- mapeamento
    def set_tree_leaves(self, leaves: list[str]) -> None:
        self.leaves = list(leaves)
        # mapeamentos para folhas que não existem mais são descartados
        for name, leaf in list(self.mapping.items()):
            if leaf is not None and leaf not in self.leaves:
                self.mapping[name] = None
                self.manual.discard(name)
        self.auto_map(reset=False)

    def auto_map(self, reset: bool = True) -> None:
        if reset:
            self.manual.clear()
        keep = {n: l for n, l in self.mapping.items() if n in self.manual and l}
        free_leaves = [l for l in self.leaves if l not in keep.values()]
        names = [g.name for g in self.genomes if g.name not in keep]
        auto = match_names(names, free_leaves)
        self.mapping = {g.name: keep.get(g.name, auto.get(g.name)) for g in self.genomes}
        self.refresh()
        self.changed.emit()

    def set_mapping(self, genome_name: str, leaf: str | None) -> None:
        if leaf is not None:  # uma folha só pode ter um GFF
            for n, l in self.mapping.items():
                if l == leaf and n != genome_name:
                    self.mapping[n] = None
                    self.manual.discard(n)
        self.mapping[genome_name] = leaf
        self.manual.add(genome_name)
        self.refresh()
        self.changed.emit()

    def genomes_by_leaf(self) -> dict[str, Genome]:
        return {self.mapping[g.name]: g for g in self.genomes if self.mapping.get(g.name)}  # type: ignore[misc]

    def refresh(self) -> None:
        self._filling = True
        self.table.setRowCount(len(self.genomes))
        for row, g in enumerate(self.genomes):
            item = QTableWidgetItem(g.name)
            item.setToolTip(str(g.path))
            self.table.setItem(row, COL_FILE, item)
            n = QTableWidgetItem(str(g.n_genes))
            n.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, COL_GENES, n)
            combo = QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.addItem(NO_LEAF, None)
            for leaf in self.leaves:
                combo.addItem(leaf, leaf)
            comp = QCompleter(self.leaves, combo)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            combo.setCompleter(comp)
            leaf = self.mapping.get(g.name)
            combo.setCurrentIndex(max(combo.findData(leaf), 0) if leaf else 0)
            combo.activated.connect(lambda _i, name=g.name, cb=combo: self.set_mapping(name, cb.currentData()))
            self.table.setCellWidget(row, COL_LEAF, combo)
            if not leaf:
                status, tip = "⚠", "Sem folha: este GFF não entra no heatmap"
            elif g.name in self.manual:
                status, tip = "✎", "Mapeado à mão"
            else:
                status, tip = "✓", "Mapeado automaticamente"
            if g.warnings:
                status += " !"
                tip += "\n\nAvisos de leitura:\n" + "\n".join(g.warnings)
            s = QTableWidgetItem(status)
            s.setToolTip(tip)
            self.table.setItem(row, COL_STATUS, s)
        mapped = sum(1 for g in self.genomes if self.mapping.get(g.name))
        if self.genomes:
            no_gff = len(self.leaves) - mapped if self.leaves else 0
            self.summary.setText(
                f"{len(self.genomes)} GFF3 · {mapped} mapeado(s) a folhas"
                + (f" · {no_gff} folha(s) sem GFF (aparecem como “sem GFF”)" if self.leaves else "")
            )
        else:
            self.summary.setText("Nenhum GFF carregado. O nome do arquivo é usado para achar a folha.")
        self._filling = False
        self._refresh_queries()

    # -------------------------------------------------------------- busca
    def _current_query(self) -> GeneQuery | None:
        text = self.query_edit.text().strip()
        if not text:
            return None
        fields = tuple(f for f, cb in (("product", self.f_product), ("name", self.f_name),
                                         ("gene", self.f_name), ("locus_tag", self.f_locus)) if cb.isChecked())
        if not fields:
            self.status_message.emit("Marque pelo menos um campo de busca.")
            return None
        return GeneQuery(text, fields, self.f_regex.isChecked())

    def add_query(self) -> None:
        q = self._current_query()
        if q is None:
            return
        try:
            q.matcher()
        except ValueError as exc:
            show_error(self, exc, "Busca")
            return
        if any(x.title == q.title for x in self.queries):
            self.status_message.emit(f"A coluna “{q.title}” já existe.")
            return
        self.queries.append(q)
        self.query_edit.clear()
        self._refresh_queries()
        self.query_list.setCurrentRow(len(self.queries) - 1)
        self.changed.emit()

    def remove_query(self) -> None:
        row = self.query_list.currentRow()
        if 0 <= row < len(self.queries):
            self.queries.pop(row)
            self._refresh_queries()
            self.changed.emit()

    def move_query(self, delta: int) -> None:
        row = self.query_list.currentRow()
        new = row + delta
        if 0 <= row < len(self.queries) and 0 <= new < len(self.queries):
            self.queries[row], self.queries[new] = self.queries[new], self.queries[row]
            self._refresh_queries()
            self.query_list.setCurrentRow(new)
            self.changed.emit()

    def genes_for(self, genome: Genome, query: GeneQuery) -> list:
        """``find_genes`` com cache por (arquivo, versão, consulta): mudar o mapeamento,
        a ordem das colunas ou o estilo não refaz buscas."""
        key = (genome.key or str(genome.path), genome.mtime_ns, genome.size, query)
        hit = self._search_cache.get(key)
        if hit is None:
            hit = find_genes(genome, query)
            self._search_cache[key] = hit
        return hit

    def _drop_search_cache(self, genome: Genome) -> None:
        k = genome.key or str(genome.path)
        for key in [key for key in self._search_cache if key[0] == k]:
            del self._search_cache[key]

    def matrix(self) -> dict[str, dict[str, int]]:
        return presence_matrix(self.genomes_by_leaf(), self.queries, self.genes_for)

    def _refresh_queries(self) -> None:
        current = self.query_list.currentRow()
        self.query_list.blockSignals(True)
        self.query_list.clear()
        by_leaf = self.genomes_by_leaf()
        matrix = presence_matrix(by_leaf, self.queries, self.genes_for) if by_leaf else {}
        for q in self.queries:
            counts = matrix.get(q.title, {})
            hits = sum(1 for n in counts.values() if n > 0)
            mode = "regex" if q.regex else "texto"
            item = QListWidgetItem(f"{q.title}  —  {hits}/{len(by_leaf)} genomas  ({mode})")
            item.setToolTip(f"Campos: {', '.join(dict.fromkeys(q.fields))}")
            self.query_list.addItem(item)
        self.query_list.blockSignals(False)
        if 0 <= current < len(self.queries):
            self.query_list.setCurrentRow(current)
        anchor = self.ctx_anchor.currentData()
        self.ctx_anchor.blockSignals(True)
        self.ctx_anchor.clear()
        for q in self.queries:
            self.ctx_anchor.addItem(q.title, q.title)
        idx = self.ctx_anchor.findData(anchor)
        self.ctx_anchor.setCurrentIndex(idx if idx >= 0 else 0)
        self.ctx_anchor.blockSignals(False)

    def context_query(self) -> GeneQuery | None:
        """Consulta âncora se o contexto estiver ligado (e houver GFFs)."""
        if not (self.ctx_enabled.isChecked() and self.genomes):
            return None
        title = self.ctx_anchor.currentData()
        return next((q for q in self.queries if q.title == title), None)

    def _query_selected(self, row: int) -> None:
        if 0 <= row < len(self.queries):
            self.show_preview(self.queries[row])

    def show_preview(self, query: GeneQuery | None) -> None:
        if query is None:
            return
        rows: list[tuple[str, str, str, str]] = []
        try:
            for g in self.genomes:
                for f in self.genes_for(g, query):
                    rows.append((self.mapping.get(g.name) or g.name, f.locus_tag, f.gene or f.name, f.product))
        except ValueError as exc:
            show_error(self, exc, "Busca")
            return
        self.preview_label.setText(
            f"“{query.title}”: {len(rows)} gene(s)" + (f" (mostrando {PREVIEW_LIMIT})" if len(rows) > PREVIEW_LIMIT else "")
        )
        self.preview.setRowCount(min(len(rows), PREVIEW_LIMIT))
        for i, vals in enumerate(rows[:PREVIEW_LIMIT]):
            for j, v in enumerate(vals):
                self.preview.setItem(i, j, QTableWidgetItem(v))
