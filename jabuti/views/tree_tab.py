"""Aba "Árvore": carregar, resumo e enraizamento."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QCompleter,
    QFileDialog,
    QGroupBox,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from jabuti.models.tree import Tree
from jabuti.parsers.newick import load_tree
from jabuti.views.errors import show_error

TREE_FILTER = "Árvores (*.nwk *.newick *.tree *.treefile *.tre *.contree *.txt);;Todos (*)"


class TreeTab(QWidget):
    tree_changed = Signal(object)  # Tree

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.original: Tree | None = None
        self.path: Path | None = None

        self.open_btn = QPushButton("Abrir árvore (Newick / .treefile)…")
        self.open_btn.clicked.connect(self._choose_file)
        self.file_label = QLabel("Nenhuma árvore carregada.")
        self.file_label.setWordWrap(True)
        self.summary_label = QLabel("")
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary_label.setWordWrap(True)

        root_box = QGroupBox("Enraizamento")
        self.rb_orig = QRadioButton("Como no arquivo")
        self.rb_mid = QRadioButton("Midpoint")
        self.rb_out = QRadioButton("Por folha (outgroup):")
        self.rb_orig.setChecked(True)
        group = QButtonGroup(self)
        for rb in (self.rb_orig, self.rb_mid, self.rb_out):
            group.addButton(rb)
        self.outgroup = QComboBox()
        self.outgroup.setEditable(True)
        self.outgroup.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.apply_root_btn = QPushButton("Aplicar enraizamento")
        self.apply_root_btn.clicked.connect(self.apply_rooting)
        rl = QVBoxLayout(root_box)
        for w in (self.rb_orig, self.rb_mid, self.rb_out, self.outgroup, self.apply_root_btn):
            rl.addWidget(w)
        root_box.setEnabled(False)
        self.root_box = root_box

        lay = QVBoxLayout(self)
        lay.addWidget(self.open_btn)
        lay.addWidget(self.file_label)
        lay.addWidget(self.summary_label)
        lay.addWidget(root_box)
        lay.addStretch(1)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir árvore", "", TREE_FILTER)
        if path:
            self.load(path)

    def load(self, path: str | Path) -> bool:
        try:
            tree = load_tree(path)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Erro ao abrir árvore")
            return False
        self.original = tree
        self.path = Path(path)
        self.file_label.setText(f"<b>{self.path.name}</b>")
        self.summary_label.setText(tree.summary().describe())
        names = sorted(tree.leaf_names(), key=str.lower)
        self.outgroup.clear()
        self.outgroup.addItems(names)
        comp = QCompleter(names, self.outgroup)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        self.outgroup.setCompleter(comp)
        self.root_box.setEnabled(True)
        self.rb_orig.setChecked(True)
        self.tree_changed.emit(tree.copy())
        return True

    def apply_rooting(self) -> None:
        if self.original is None:
            return
        tree = self.original.copy()
        try:
            if self.rb_mid.isChecked():
                tree.reroot_midpoint()
            elif self.rb_out.isChecked():
                tree.reroot_outgroup(self.outgroup.currentText().strip())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Erro ao enraizar")
            return
        self.tree_changed.emit(tree)
