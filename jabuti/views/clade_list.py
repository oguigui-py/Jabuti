"""Tabela de clados: cor, nome (editável), nº de folhas, estilizar rótulos, visível, remover."""

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

COL_COLOR, COL_NAME, COL_N, COL_LABELS, COL_VIS, COL_DEL = range(6)



def drop_cell_widgets(table, cols) -> None:  # type: ignore[no-untyped-def]
    """Solta e esconde já os widgets das células: o Qt só os apaga no próximo
    ciclo do loop e, até lá, eles continuariam visíveis sob os novos."""
    for row in range(table.rowCount()):
        for col in cols:
            w = table.cellWidget(row, col)
            if w is not None:
                table.removeCellWidget(row, col)
                w.hide()
                w.setParent(None)
                w.deleteLater()

class CladeList(QTableWidget):
    changed = Signal()
    style_labels_requested = Signal(object)  # Clade

    def __init__(self, clade_set: CladeSet, parent: QWidget | None = None) -> None:
        super().__init__(0, 6, parent)
        self.clade_set = clade_set
        self.palette: list[str] = ["#4e79a7"]
        self._resolved: dict[int, ResolvedClade] = {}
        self._filling = False
        self.setHorizontalHeaderLabels(["", "Nome", "Folhas", "Aa", "Ver", ""])
        h = self.horizontalHeader()
        h.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(COL_N, QHeaderView.ResizeMode.ResizeToContents)
        # colunas com widgets: largura fixa (ResizeToContents ignora os widgets e eles se sobrepõem)
        for c, w in ((COL_COLOR, 26), (COL_LABELS, 30), (COL_VIS, 30), (COL_DEL, 26)):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(c, w)
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
        drop_cell_widgets(self, (COL_COLOR, COL_LABELS, COL_VIS, COL_DEL))
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

            aa = QToolButton()
            aa.setText("Aa")
            aa.setToolTip("Estilizar os rótulos deste clado (grupo de rótulos próprio, sem mudar os ramos)")
            aa.setAutoRaise(True)
            aa.clicked.connect(lambda _=False, c=clade: self.style_labels_requested.emit(c))
            self.setCellWidget(row, COL_LABELS, aa)

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
