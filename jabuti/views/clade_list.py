"""Tabela de clados: cor, nome (editável), nº de folhas, visível, remover."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QWidget,
)

from jabuti.models.clades import Clade, CladeSet, ResolvedClade
from jabuti.views.widgets.swatches import color_menu, swatch_button

COL_COLOR, COL_NAME, COL_N, COL_VIS, COL_DEL = range(5)


class CladeList(QTableWidget):
    changed = Signal()

    def __init__(self, clade_set: CladeSet, parent: QWidget | None = None) -> None:
        super().__init__(0, 5, parent)
        self.clade_set = clade_set
        self.palette: list[str] = ["#4e79a7"]
        self._resolved: dict[int, ResolvedClade] = {}
        self._filling = False
        self.setHorizontalHeaderLabels(["", "Nome", "Folhas", "Ver", ""])
        h = self.horizontalHeader()
        h.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for c in (COL_COLOR, COL_N, COL_VIS, COL_DEL):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setMinimumHeight(120)
        self.itemChanged.connect(self._on_item_changed)

    # ---------------------------------------------------------------- API
    def set_status(self, resolved: list[ResolvedClade]) -> None:
        """Atualiza cores efetivas e avisos sem emitir ``changed``."""
        self._resolved = {id(rc.clade): rc for rc in resolved}
        self.refresh()

    def color_of(self, index: int, clade: Clade) -> str:
        rc = self._resolved.get(id(clade))
        if rc is not None:
            return rc.color
        return clade.color or self.palette[index % len(self.palette)]

    def refresh(self) -> None:
        self._filling = True
        clades = self.clade_set.clades
        self.setRowCount(len(clades))
        for row, clade in enumerate(clades):
            color = self.color_of(row, clade)
            btn = swatch_button(color, "Trocar cor deste clado", 18, checkable=False)
            btn.clicked.connect(lambda _=False, c=clade, b=btn: self._pick_color(c, b))
            self.setCellWidget(row, COL_COLOR, btn)

            name = QTableWidgetItem(clade.name)
            rc = self._resolved.get(id(clade))
            if rc is not None and not rc.valid:
                name.setText(f"⚠ {clade.name}")
                name.setToolTip(f"Não desenhado: {rc.problem}")
                name.setForeground(Qt.GlobalColor.darkRed)
            elif clade.source == "manual":
                name.setToolTip("Clado manual (mantido ao detectar automaticamente)")
            self.setItem(row, COL_NAME, name)

            n = QTableWidgetItem(str(len(clade.leaves)))
            n.setFlags(n.flags() & ~Qt.ItemFlag.ItemIsEditable)
            n.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, COL_N, n)

            vis = QCheckBox()
            vis.setChecked(clade.visible)
            vis.toggled.connect(lambda on, c=clade: self._set_visible(c, on))
            self.setCellWidget(row, COL_VIS, vis)

            rm = QToolButton()
            rm.setText("✕")
            rm.setToolTip("Remover clado")
            rm.setAutoRaise(True)
            rm.clicked.connect(lambda _=False, c=clade: self._remove(c))
            self.setCellWidget(row, COL_DEL, rm)
        self._filling = False

    # ------------------------------------------------------------ ações
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != COL_NAME:
            return
        row = item.row()
        if 0 <= row < len(self.clade_set.clades):
            text = item.text().removeprefix("⚠ ").strip()
            if text:
                self.clade_set.clades[row].name = text
                self.changed.emit()

    def _pick_color(self, clade: Clade, anchor: QToolButton) -> None:
        def pick(color: str | None) -> None:
            clade.color = color
            self.changed.emit()

        menu = color_menu(self, self.palette, pick)
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _set_visible(self, clade: Clade, on: bool) -> None:
        clade.visible = on
        self.changed.emit()

    def _remove(self, clade: Clade) -> None:
        self.clade_set.remove(clade)
        self.refresh()
        self.changed.emit()
