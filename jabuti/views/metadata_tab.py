"""Aba "Metadados": tabela TSV/CSV com uma linha por folha."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jabuti.views.theme import muted_css
from jabuti.settings import open_file
from jabuti.parsers.metadata import (
    MetadataMatch,
    MetadataTable,
    column_is_numeric,
    guess_key_column,
    load_metadata,
    match_table,
)
from jabuti.views.errors import show_error

TABLE_FILTER = "Tabelas (*.tsv *.tab *.csv *.txt);;Todos (*)"
PREVIEW_ROWS = 100


class MetadataTab(QWidget):
    changed = Signal()
    columns_changed = Signal(list)   # colunas disponíveis para colorir (sem a chave)
    status_message = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table: MetadataTable | None = None
        self.leaves: list[str] = []
        self.match: MetadataMatch | None = None

        open_btn = QPushButton("Abrir tabela (TSV/CSV)…")
        open_btn.clicked.connect(self._choose_file)
        clear_btn = QPushButton("Remover")
        clear_btn.clicked.connect(self.clear)
        row = QHBoxLayout()
        row.addWidget(open_btn, 1)
        row.addWidget(clear_btn)
        self.file_label = QLabel("Nenhuma tabela carregada. Uma linha por genoma, com cabeçalho.")
        self.file_label.setWordWrap(True)
        self.key_combo = QComboBox()
        self.key_combo.currentIndexChanged.connect(self._key_changed)
        form = QFormLayout()
        form.addRow("Coluna com o nome da folha:", self.key_combo)
        self.report = QLabel("")
        self.report.setWordWrap(True)
        self.preview = QTableWidget(0, 0)
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.verticalHeader().setVisible(False)
        self.preview.setMinimumHeight(240)
        hint = QLabel("Escolha a coluna para colorir e as faixas no painel <b>Estilo → Metadados e legenda</b>.")
        hint.setWordWrap(True)
        hint.setStyleSheet(muted_css())

        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addWidget(self.file_label)
        lay.addLayout(form)
        lay.addWidget(self.report)
        lay.addWidget(hint)
        lay.addWidget(self.preview)
        lay.addStretch(1)

    # ---------------------------------------------------------------- I/O
    def _choose_file(self) -> None:
        path = open_file(self, "Abrir metadados", "table", TABLE_FILTER)
        if path:
            self.load(path)

    def load(self, path: str | Path) -> bool:
        try:
            table = load_metadata(path)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Erro ao abrir metadados")
            return False
        self.table = table
        sep = {"\t": "TAB", ",": "vírgula", ";": "ponto e vírgula"}.get(table.delimiter, table.delimiter)
        text = f"<b>{Path(path).name}</b> — {len(table.rows)} linhas, {len(table.columns)} colunas (separador: {sep})"
        if table.warnings:
            text += "<br>⚠ " + "<br>⚠ ".join(table.warnings[:5])
        self.file_label.setText(text)
        self.key_combo.blockSignals(True)
        self.key_combo.clear()
        self.key_combo.addItems(table.columns)
        key = guess_key_column(table, self.leaves) if self.leaves else table.columns[0]
        self.key_combo.setCurrentText(key)
        self.key_combo.blockSignals(False)
        self._fill_preview()
        self._rematch()
        return True

    def clear(self) -> None:
        self.table = None
        self.match = None
        self.key_combo.clear()
        self.preview.setRowCount(0)
        self.preview.setColumnCount(0)
        self.file_label.setText("Nenhuma tabela carregada. Uma linha por genoma, com cabeçalho.")
        self.report.setText("")
        self.columns_changed.emit([])
        self.changed.emit()

    # --------------------------------------------------------------- dados
    def set_tree_leaves(self, leaves: list[str]) -> None:
        self.leaves = list(leaves)
        if self.table is not None:
            self._rematch()

    def key_column(self) -> str | None:
        return self.key_combo.currentText() or None

    def value_columns(self) -> list[str]:
        if self.table is None:
            return []
        return [c for c in self.table.columns if c != self.key_column()]

    def by_leaf(self) -> dict[str, dict[str, str]]:
        return self.match.by_leaf if self.match else {}

    def _key_changed(self) -> None:
        self._rematch()

    def _rematch(self) -> None:
        key = self.key_column()
        if self.table is None or not key:
            return
        self.match = match_table(self.table, key, self.leaves)
        m = self.match
        if self.leaves:
            parts = [f"{len(m.by_leaf)}/{len(self.leaves)} folhas com metadados."]
            if m.leaves_without:
                more = "…" if len(m.leaves_without) > 6 else ""
                parts.append(f"⚠ Sem metadados ({len(m.leaves_without)}): {', '.join(m.leaves_without[:6])}{more}")
            if m.unused_keys:
                more = "…" if len(m.unused_keys) > 6 else ""
                parts.append(f"Linhas sem folha na árvore ({len(m.unused_keys)}): {', '.join(m.unused_keys[:6])}{more}")
            self.report.setText("<br>".join(parts))
            self.report.setToolTip("\n".join(m.leaves_without))
        else:
            self.report.setText("Abra uma árvore para casar as linhas com as folhas.")
        self.columns_changed.emit(self.value_columns())
        self.changed.emit()

    def column_kind(self, column: str) -> str:
        if self.table is None:
            return ""
        return "numérica" if column_is_numeric(self.table.values(column)) else "categórica"

    def _fill_preview(self) -> None:
        t = self.table
        if t is None:
            return
        self.preview.setColumnCount(len(t.columns))
        self.preview.setHorizontalHeaderLabels(t.columns)
        rows = t.rows[:PREVIEW_ROWS]
        self.preview.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, c in enumerate(t.columns):
                self.preview.setItem(i, j, QTableWidgetItem(r.get(c, "")))
        self.preview.resizeColumnsToContents()
