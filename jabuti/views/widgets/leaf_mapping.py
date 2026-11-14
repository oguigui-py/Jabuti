"""Tabela editável "nome no arquivo → folha" (aba GFF e tabelas do painel Figura)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

NO_LEAF = "— sem folha —"


@dataclass
class MappingRow:
    key: str                       # nome no arquivo (identifica a linha)
    leaf: str | None
    manual: bool = False
    info: str | None = None        # coluna extra opcional (ex.: nº de genes)
    tooltip: str = ""
    warnings: str = ""             # avisos extras na coluna de status


class LeafMappingTable(QTableWidget):
    """Colunas: nome, [info], folha (combo com busca), status (⚠ sem folha, ✎ à mão, ✓ automático)."""

    mapping_edited = Signal(str, object)   # chave, folha (ou None)

    def __init__(self, headers: list[str], with_info: bool = True, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(0, len(headers), parent)
        self.with_info = with_info
        self.col_name = 0
        self.col_info = 1 if with_info else -1
        self.col_leaf = 2 if with_info else 1
        self.col_status = self.col_leaf + 1
        self.setHorizontalHeaderLabels(headers)
        h = self.horizontalHeader()
        h.setSectionResizeMode(self.col_name, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(self.col_leaf, QHeaderView.ResizeMode.Stretch)
        if with_info:
            h.setSectionResizeMode(self.col_info, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(self.col_status, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.no_leaf_tip = "Sem folha: esta linha não entra no desenho"

    def fill(self, rows: list[MappingRow], leaves: list[str]) -> None:
        self.setRowCount(len(rows))
        for row, r in enumerate(rows):
            item = QTableWidgetItem(r.key)
            item.setToolTip(r.tooltip or r.key)
            self.setItem(row, self.col_name, item)
            if self.with_info:
                n = QTableWidgetItem(r.info or "")
                n.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.setItem(row, self.col_info, n)
            combo = QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.addItem(NO_LEAF, None)
            for leaf in leaves:
                combo.addItem(leaf, leaf)
            comp = QCompleter(leaves, combo)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            combo.setCompleter(comp)
            combo.setCurrentIndex(max(combo.findData(r.leaf), 0) if r.leaf else 0)
            combo.activated.connect(lambda _i, key=r.key, cb=combo: self.mapping_edited.emit(key, cb.currentData()))
            self.setCellWidget(row, self.col_leaf, combo)
            if not r.leaf:
                status, tip = "⚠", self.no_leaf_tip
            elif r.manual:
                status, tip = "✎", "Mapeado à mão"
            else:
                status, tip = "✓", "Mapeado automaticamente"
            if r.warnings:
                status += " !"
                tip += "\n\n" + r.warnings
            s = QTableWidgetItem(status)
            s.setToolTip(tip)
            self.setItem(row, self.col_status, s)
