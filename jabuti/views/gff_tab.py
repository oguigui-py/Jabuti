"""Aba "GFF": carregar GFF3 (um por genoma), mapear para folhas e buscar genes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jabuti.models.annotations import presence_matrix
from jabuti.parsers.errors import JabutiParseError
from jabuti.parsers.gff import GeneQuery, Genome, find_genes, parse_gff3
from jabuti.parsers.names import match_names
from jabuti.views.errors import show_error

GFF_FILTER = "GFF3 (*.gff *.gff3 *.gff.gz *.gff3.gz);;Todos (*)"
NO_LEAF = "— sem folha —"
PREVIEW_LIMIT = 300
COL_FILE, COL_GENES, COL_LEAF, COL_STATUS = range(4)


class GffTab(QWidget):
    changed = Signal()          # dados mudaram -> redesenhar
    status_message = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.genomes: list[Genome] = []
        self.mapping: dict[str, str | None] = {}   # genome.name -> folha
        self.manual: set[str] = set()               # mapeamentos editados à mão
        self.leaves: list[str] = []
        self.queries: list[GeneQuery] = []
        self._filling = False

        # --- arquivos
        add_btn = QPushButton("Adicionar GFF3…")
        add_btn.clicked.connect(self._choose_files)
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
        fields_row = QHBoxLayout()
        for cb in (self.f_product, self.f_name, self.f_locus, self.f_regex):
            fields_row.addWidget(cb)
        fields_row.addStretch(1)
        add_q = QPushButton("Adicionar coluna")
        add_q.clicked.connect(self.add_query)
        prev_q = QPushButton("Prévia")
        prev_q.setToolTip("Mostra os genes encontrados sem adicionar coluna")
        prev_q.clicked.connect(lambda: self.show_preview(self._current_query()))
        qrow = QHBoxLayout()
        qrow.addWidget(self.query_edit, 1)
        qrow.addWidget(prev_q)
        qrow.addWidget(add_q)

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
        lay.addWidget(auto_btn)
        lay.addWidget(self.progress)
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

    def load_files(self, paths: list[str | Path]) -> int:
        errors: list[str] = []
        loaded = 0
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self.progress.setVisible(len(paths) > 1)
        existing = {g.name for g in self.genomes}
        for i, path in enumerate(paths):
            self.status_message.emit(f"Lendo {Path(path).name} ({i + 1}/{len(paths)})…")
            QCoreApplication.processEvents()
            try:
                g = parse_gff3(path)
            except JabutiParseError as exc:
                errors.append(exc.user_message())
                continue
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{Path(path).name}: {exc}")
                continue
            base, n = g.name, 2
            while g.name in existing:  # mesmo nome de arquivo em pastas diferentes
                g.name = f"{base}_{n}"
                n += 1
            existing.add(g.name)
            self.genomes.append(g)
            loaded += 1
            self.progress.setValue(i + 1)
        self.progress.setVisible(False)
        self.auto_map(reset=False)
        if errors:
            show_error(self, Exception(f"{len(errors)} arquivo(s) não puderam ser lidos:\n\n" +
                                       "\n\n".join(errors[:8])), "Erro ao ler GFF")
        self.status_message.emit(f"{loaded} GFF3 carregado(s).")
        return loaded

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            g = self.genomes.pop(r)
            self.mapping.pop(g.name, None)
            self.manual.discard(g.name)
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

    def matrix(self) -> dict[str, dict[str, int]]:
        return presence_matrix(self.genomes_by_leaf(), self.queries)

    def _refresh_queries(self) -> None:
        current = self.query_list.currentRow()
        self.query_list.blockSignals(True)
        self.query_list.clear()
        by_leaf = self.genomes_by_leaf()
        matrix = presence_matrix(by_leaf, self.queries) if by_leaf else {}
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
                for f in find_genes(g, query):
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
