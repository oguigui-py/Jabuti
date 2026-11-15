"""Seção "Anotações iTOL" do painel Figura: importar, ligar/desligar, ordenar, remover e editar.

Os arquivos são lidos numa thread (``FileLoader``); a aplicação na árvore acontece a cada
desenho (``jabuti.models.itol_apply``), então nada aqui altera clados, grupos ou nomes do usuário.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jabuti.views.theme import muted_css
from jabuti.settings import open_files
from jabuti.models.itol_apply import ItolEffects, ItolEntry, dataset_entries
from jabuti.parsers.itol import KIND_NAMES, parse_itol
from jabuti.style import BRANCH_TEXT_ORIENTATIONS, BranchTextStyle, ItolPref
from jabuti.views.errors import show_error
from jabuti.views.widgets.swatches import ColorButton
from jabuti.workers import FileLoader

ITOL_FILTER = "Anotações iTOL (*.txt *.tsv *.csv *.itol);;Todos (*)"


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(muted_css())
    return lbl


def _parse(path: Path, _stop):  # type: ignore[no-untyped-def]
    return parse_itol(path)


class ItolPanel(QWidget):
    changed = Signal()
    status_message = Signal(str)
    loaded = Signal(bool)              # terminou de ler (algum ok?)
    collapse_changed = Signal(object, bool)   # ItolEntry de COLLAPSE, aplicar (True) / desfazer (False)
    export_requested = Signal()               # "Exportar para o iTOL…" (a janela monta e grava)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entries: list[ItolEntry] = []
        self.prefs: dict[str, ItolPref] = {}        # do preset: aplicados ao (re)importar
        self.palette: list[str] = []
        self._loaders: list[FileLoader] = []
        self._loading = False
        self._last_ok = False
        self._new_keys: list[str] = []
        self._read_errors: list[str] = []
        self._report_pending = False
        self._filling = False
        self.stats: dict = {}

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 0, 0, 6)
        self.import_btn = QPushButton("Importar…")
        self.import_btn.setToolTip("Importar anotações do iTOL (TREE_COLORS, LABELS, DATASET_COLORSTRIP, "
                                   "DATASET_STYLE…). Também dá para arrastar os arquivos para a janela.")
        self.import_btn.clicked.connect(self._choose)
        self.export_btn = QPushButton("Exportar…")
        self.export_btn.setToolTip("Exportar para o iTOL: gera a árvore (Newick) e um arquivo por anotação, no formato do iTOL, "
                                   "reproduzindo a figura atual. Mostra um resumo antes de gravar.")
        self.export_btn.clicked.connect(self.export_requested)
        row = QHBoxLayout()
        row.addWidget(self.import_btn, 1)
        row.addWidget(self.export_btn, 1)
        v.addLayout(row)
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setMaximumHeight(130)
        self.list.setToolTip("Marque para mostrar. Arraste para mudar a prioridade (o de baixo vence em "
                             "conflito); a posição das faixas fica em “Ordem das colunas”.")
        self.list.itemChanged.connect(self._item_changed)
        self.list.model().rowsMoved.connect(self._rows_moved)
        self.list.currentRowChanged.connect(self._selected)
        v.addWidget(self.list)
        row = QHBoxLayout()
        self.remove_btn = QPushButton("Remover")
        self.remove_btn.clicked.connect(self.remove_current)
        row.addStretch(1)
        row.addWidget(self.remove_btn)
        v.addLayout(row)

        ed = QWidget()
        ev = QVBoxLayout(ed)
        ev.setContentsMargins(0, 0, 0, 0)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Título:"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("vazio = DATASET_LABEL")
        self.title_edit.editingFinished.connect(self._title_edited)
        trow.addWidget(self.title_edit, 1)
        ev.addLayout(trow)
        self.colors = QTableWidget(0, 2)
        self.colors.setHorizontalHeaderLabels(["Cor", "Legenda"])
        self.colors.verticalHeader().setVisible(False)
        self.colors.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.colors.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.colors.setMaximumHeight(140)
        self.colors.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.colors.itemChanged.connect(self._label_edited)
        ev.addWidget(self.colors)
        self.editor = ed
        v.addWidget(ed)
        # textos sobre os ramos (DATASET_TEXT com posição 0–1)
        brow = QHBoxLayout()
        brow.addWidget(QLabel("Textos nos ramos:"))
        self.bt_orient = QComboBox()
        for key, name in BRANCH_TEXT_ORIENTATIONS.items():
            self.bt_orient.addItem(name, key)
        self.bt_orient.setToolTip("Orientação dos textos do iTOL desenhados sobre os ramos. Na circular, no leque "
                                  "e na não enraizada, “Ao longo do ramo” acompanha a direção do ramo e fica "
                                  "sempre de pé; “Horizontal” é o comportamento antigo.")
        self.bt_orient.currentIndexChanged.connect(self._bt_changed)
        brow.addWidget(self.bt_orient, 1)
        v.addLayout(brow)
        brow = QHBoxLayout()
        brow.addWidget(QLabel("Distância do ramo:"))
        self.bt_offset = QDoubleSpinBox()
        self.bt_offset.setRange(0.0, 30.0)
        self.bt_offset.setSingleStep(0.5)
        self.bt_offset.setSuffix(" px")
        self.bt_offset.setToolTip("Espaço mínimo entre o texto e o ramo, para não encostar na linha.")
        self.bt_offset.valueChanged.connect(self._bt_changed)
        brow.addWidget(self.bt_offset)
        self.bt_halo = QCheckBox("Halo claro")
        self.bt_halo.setToolTip("Contorno claro atrás do texto: continua legível sobre ramos e fundos coloridos.")
        self.bt_halo.toggled.connect(self._bt_changed)
        brow.addStretch(1)
        v.addLayout(brow)
        v.addWidget(self.bt_halo)
        self.set_branch_text(BranchTextStyle())
        v.addWidget(QLabel("<b>Problemas na leitura</b>"))
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(110)
        self.report.setPlaceholderText("Nenhum problema.")
        v.addWidget(self.report)
        self.hint = _hint("Nenhuma anotação importada.")
        v.addWidget(self.hint)
        self._refresh()

    # ------------------------------------------------------------ textos nos ramos
    def branch_text(self) -> BranchTextStyle:
        return BranchTextStyle(self.bt_orient.currentData() or "along", self.bt_offset.value(),
                               self.bt_halo.isChecked())

    def set_branch_text(self, bt: BranchTextStyle) -> None:
        widgets = (self.bt_orient, self.bt_offset, self.bt_halo)
        for w in widgets:
            w.blockSignals(True)
        try:
            i = self.bt_orient.findData(bt.orientation)
            self.bt_orient.setCurrentIndex(i if i >= 0 else 0)
            self.bt_offset.setValue(bt.offset)
            self.bt_halo.setChecked(bt.halo)
        finally:
            for w in widgets:
                w.blockSignals(False)

    def _bt_changed(self, *_a) -> None:  # type: ignore[no-untyped-def]
        self.changed.emit()

    # ------------------------------------------------------------ leitura
    def _choose(self) -> None:
        paths = open_files(self, "Importar anotação iTOL", "itol", ITOL_FILTER)
        if paths:
            self.import_files(paths, wait=False)

    def is_loading(self) -> bool:
        return self._loading

    def import_files(self, paths, wait: bool = True) -> bool:  # type: ignore[no-untyped-def]
        """Lê os arquivos numa thread; com ``wait=True`` espera (processando eventos)."""
        if self._loading:
            self.status_message.emit("Aguarde a leitura em andamento.")
            return False
        ps = [Path(p) for p in paths]
        if not ps:
            return False
        loader = FileLoader(ps, _parse)
        q = Qt.ConnectionType.QueuedConnection
        loader.items.connect(self._on_items, q)
        loader.finished.connect(self._on_finished, q)
        self._loaders = [w for w in self._loaders if w.is_running()] + [loader]
        self._loading = True
        self._last_ok = False
        self._new_keys = []
        self._read_errors = []
        self.import_btn.setEnabled(False)
        self.status_message.emit(f"Lendo {len(ps)} anotação(ões) iTOL…")
        loader.start()
        if wait:
            loop = QEventLoop()
            self.loaded.connect(loop.quit)
            if self._loading:
                loop.exec()
            self.loaded.disconnect(loop.quit)
        return self._last_ok

    def _unique_key(self, label: str) -> str:
        base = f"itol:{label}"
        used = {e.key for e in self.entries}
        key, n = base, 2
        while key in used:
            key, n = f"{base} #{n}", n + 1
        return key

    @Slot(list)
    def _on_items(self, items: list) -> None:
        for ok, path, result in items:
            if not ok:
                self._read_errors.append(result.replace("\n", " — "))
                continue
            entry = ItolEntry(self._unique_key(result.label), result)
            pref = self.prefs.get(entry.key)
            if pref is not None:
                self._apply_pref(entry, pref)
            self.entries.append(entry)
            self._new_keys.append(entry.key)
            self._last_ok = True

    @Slot(bool)
    def _on_finished(self, _cancelled: bool) -> None:
        self._loading = False
        self.import_btn.setEnabled(True)
        if self._read_errors:
            show_error(self, Exception("\n\n".join(self._read_errors)), "Erro ao ler anotação iTOL")
        if self._last_ok:
            self._report_pending = True
            self._refresh(select=len(self.entries) - 1)
            for e in self.entries:
                if e.key in self._new_keys and e.dataset.kind == "COLLAPSE" and e.visible:
                    self.collapse_changed.emit(e, True)
            self.changed.emit()
        self.loaded.emit(self._last_ok)

    def shutdown(self, timeout_ms: int = 5000) -> None:
        for loader in self._loaders:
            loader.cancel()
            loader.join(timeout_ms / 1000)
        self._loaders = [w for w in self._loaders if w.is_running()]

    # ------------------------------------------------------------ lista
    def visible_entries(self) -> list[ItolEntry]:
        return [e for e in self.entries if e.visible]

    def current(self) -> ItolEntry | None:
        row = self.list.currentRow()
        return self.entries[row] if 0 <= row < len(self.entries) else None

    def _item_text(self, e: ItolEntry) -> str:
        kind = KIND_NAMES.get(e.dataset.kind, e.dataset.kind)
        st = self.stats.get(e.key)
        if not e.dataset.supported:
            tail = " — ignorado"
        elif st is None or not e.visible:
            tail = ""
        else:
            tail = f" — {st.applied} aplicadas" + (f", {st.ignored} ignoradas" if st.ignored else "")
        return f"{e.name} ({kind}){tail}"

    def _refresh(self, select: int | None = None) -> None:
        row = self.list.currentRow() if select is None else select
        self._filling = True
        self.list.blockSignals(True)
        try:
            self.list.clear()
            for e in self.entries:
                item = QListWidgetItem(self._item_text(e))
                item.setData(Qt.ItemDataRole.UserRole, e.key)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
                item.setCheckState(Qt.CheckState.Checked if e.visible else Qt.CheckState.Unchecked)
                item.setToolTip(f"{e.dataset.path}\n{e.dataset.kind}, separador {e.dataset.separator}, "
                                f"{len(e.dataset.rows)} linhas de dados")
                self.list.addItem(item)
            if self.entries:
                self.list.setCurrentRow(max(0, min(row, len(self.entries) - 1)))
        finally:
            self.list.blockSignals(False)
            self._filling = False
        has = bool(self.entries)
        self.list.setVisible(has)
        self.remove_btn.setVisible(has)
        self.hint.setVisible(not has)
        self._selected(self.list.currentRow())
        self._fill_report()

    def _item_changed(self, item: QListWidgetItem) -> None:
        if self._filling:
            return
        row = self.list.row(item)
        if 0 <= row < len(self.entries):
            on = item.checkState() == Qt.CheckState.Checked
            if self.entries[row].visible != on:
                self.entries[row].visible = on
                self._collapse_toggled(self.entries[row])
                self.changed.emit()

    def _rows_moved(self, *_a) -> None:  # type: ignore[no-untyped-def]
        if self._filling:
            return
        by_key = {e.key: e for e in self.entries}
        new = [by_key[self.list.item(i).data(Qt.ItemDataRole.UserRole)] for i in range(self.list.count())]
        if len(new) == len(self.entries):
            self.entries = new
            self.changed.emit()

    def move(self, row: int, new: int) -> None:
        """Muda a prioridade (usado também pelos testes)."""
        if 0 <= row < len(self.entries) and 0 <= new < len(self.entries):
            self.entries.insert(new, self.entries.pop(row))
            self._refresh(select=new)
            self.changed.emit()

    def remove_current(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.entries):
            e = self.entries.pop(row)
            self.prefs.pop(e.key, None)
            if e.dataset.kind == "COLLAPSE":
                self.collapse_changed.emit(e, False)
            self._refresh(select=row)
            self.changed.emit()

    def set_visible(self, key: str, on: bool) -> None:
        for i, e in enumerate(self.entries):
            if e.key == key and e.visible != on:
                e.visible = on
                self._collapse_toggled(e)
                self._refresh(select=i)
                self.changed.emit()

    def _collapse_toggled(self, e: ItolEntry) -> None:
        if e.dataset.kind == "COLLAPSE":
            self.collapse_changed.emit(e, e.visible)

    # ------------------------------------------------------------ editor
    def _selected(self, row: int) -> None:
        e = self.entries[row] if 0 <= row < len(self.entries) else None
        self.editor.setVisible(e is not None and e.dataset.supported)
        if e is None:
            return
        self._filling = True
        self.colors.blockSignals(True)
        try:
            self.title_edit.setText(e.title)
            self.title_edit.setPlaceholderText(e.dataset.label)
            items = dataset_entries(e.dataset)
            self.colors.setRowCount(len(items))
            for i, (orig, label) in enumerate(items):
                btn = ColorButton(e.color(orig), self.palette)
                btn.setToolTip(f"cor no arquivo: {orig}")
                btn.color_changed.connect(lambda c, o=orig: self._color_edited(o, c))
                self.colors.setCellWidget(i, 0, btn)
                it = QTableWidgetItem(e.labels.get(orig, label))
                it.setData(Qt.ItemDataRole.UserRole, orig)
                self.colors.setItem(i, 1, it)
            self.colors.setVisible(bool(items))
        finally:
            self.colors.blockSignals(False)
            self._filling = False

    def _title_edited(self) -> None:
        e = self.current()
        if e is not None and e.title != self.title_edit.text().strip():
            e.title = self.title_edit.text().strip()
            self._refresh()
            self.changed.emit()

    def _color_edited(self, orig: str, color: str) -> None:
        e = self.current()
        if e is None:
            return
        if color == orig:
            e.colors.pop(orig, None)
        else:
            e.colors[orig] = color
        self.changed.emit()

    def set_color(self, key: str, orig: str, color: str) -> None:
        for e in self.entries:
            if e.key == key:
                e.colors[orig] = color
        self.changed.emit()

    def _label_edited(self, item: QTableWidgetItem) -> None:
        e = self.current()
        if e is None or self._filling:
            return
        orig = item.data(Qt.ItemDataRole.UserRole)
        e.labels[orig] = item.text().strip()
        self.changed.emit()

    # ------------------------------------------------------------ relatório
    def set_effects(self, fx: ItolEffects | None) -> None:
        """Chamado a cada desenho: atualiza contagens e problemas (sem redesenhar)."""
        self.stats = fx.stats if fx is not None else {}
        for i, e in enumerate(self.entries):
            item = self.list.item(i)
            if item is not None:
                self._filling = True
                item.setText(self._item_text(e))
                self._filling = False
        self._fill_report()
        if self._report_pending and fx is not None:
            self._report_pending = False
            news = [self.stats.get(k) for k in self._new_keys]
            applied = sum(s.applied for s in news if s)
            ignored = sum(s.ignored for s in news if s)
            n_prob = sum(len(s.problems) for s in news if s)
            msg = f"{len(self._new_keys)} anotação(ões) iTOL: {applied} linhas aplicadas"
            if ignored:
                msg += f", {ignored} ignoradas"
            if n_prob:
                msg += f" — {n_prob} aviso(s) em “Problemas na leitura” (painel Figura)"
            self.status_message.emit(msg + ".")

    def _fill_report(self) -> None:
        lines = []
        for e in self.entries:
            st = self.stats.get(e.key)
            probs = st.problems if st is not None else e.dataset.warnings
            for line, msg in probs:
                where = f"{e.dataset.path.name}:{line}" if line else e.dataset.path.name
                lines.append(f"{where} → {msg}")
            if st is not None and st.tolerant:
                lines.append(f"{e.dataset.path.name} → {st.tolerant} ID(s) casados por nome aproximado")
        self.report.setPlainText("\n".join(lines))

    # ------------------------------------------------------------ preset
    @staticmethod
    def _apply_pref(entry: ItolEntry, pref: ItolPref) -> None:
        entry.visible = pref.visible
        entry.title = pref.title
        entry.colors = {o: n for o, n in zip(pref.orig_colors, pref.new_colors) if o != n}
        entry.labels = {o: l for o, l in zip(pref.orig_colors, pref.entry_labels) if l}

    def to_prefs(self) -> list[ItolPref]:
        out = []
        for e in self.entries:
            origs = sorted(set(e.colors) | set(e.labels))
            out.append(ItolPref(e.key, e.visible, e.title, origs, [e.color(o) for o in origs],
                                [e.labels.get(o, "") for o in origs]))
        # ajustes de datasets não importados nesta sessão continuam no preset
        keys = {e.key for e in self.entries}
        out += [p for k, p in self.prefs.items() if k not in keys]
        return out

    def load_prefs(self, prefs: list[ItolPref]) -> None:
        self.prefs = {p.key: p for p in prefs if p.key}
        for e in self.entries:
            if e.key in self.prefs:
                self._apply_pref(e, self.prefs[e.key])
        self._refresh()
