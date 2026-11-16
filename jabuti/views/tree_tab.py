"""Aba "Árvore": carregar, resumo e enraizamento."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QCompleter,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from jabuti.settings import add_recent, open_file
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
        self.group: list[str] = []          # folhas do "grupo selecionado" (enraizamento)
        self.rooting: dict = {"mode": "file"}   # último enraizamento aplicado (vai para o projeto)

        self.open_btn = QPushButton("Abrir árvore (Newick / .treefile)…")
        self.open_btn.clicked.connect(self._choose_file)
        self.file_label = QLabel("Nenhuma árvore carregada.")
        self.file_label.setWordWrap(True)
        self.summary_label = QLabel("")
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary_label.setWordWrap(True)

        root_box = QGroupBox("Enraizamento")
        self.rb_orig = QRadioButton("Como no arquivo")
        self.rb_mid = QRadioButton("Ponto médio (midpoint)")
        self.rb_out = QRadioButton("Por folha (outgroup):")
        self.rb_group = QRadioButton("No grupo selecionado")
        self.rb_group.setToolTip("Ancestral comum das folhas selecionadas no desenho (Cmd/Shift+clique ou busca)")
        self.rb_group.setEnabled(False)
        self.rb_orig.setChecked(True)
        group = QButtonGroup(self)
        for rb in (self.rb_orig, self.rb_mid, self.rb_out, self.rb_group):
            group.addButton(rb)
        self.outgroup = QComboBox()
        self.outgroup.setEditable(True)
        self.outgroup.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.apply_root_btn = QPushButton("Aplicar enraizamento")
        self.apply_root_btn.clicked.connect(self.apply_rooting)
        rl = QVBoxLayout(root_box)
        for w in (self.rb_orig, self.rb_mid, self.rb_out, self.outgroup, self.rb_group, self.apply_root_btn):
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
        path = open_file(self, "Abrir árvore", "tree", TREE_FILTER)
        if path:
            self.load(path)

    def load(self, path: str | Path, remember: bool = True) -> bool:
        """Abre a árvore; ``remember=False`` não a põe nos recentes (árvore de um projeto)."""
        try:
            tree = load_tree(path)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Erro ao abrir árvore")
            return False
        self.original = tree
        self.path = Path(path)
        try:
            if remember:
                add_recent(self.path)
        except Exception:  # noqa: BLE001 — preferência não pode impedir a abertura
            pass
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
        self.rooting = {"mode": "file"}
        self.tree_changed.emit(tree.copy())
        return True

    def set_group(self, names: list[str]) -> None:
        """Folhas selecionadas no desenho (para "No grupo selecionado")."""
        if names:
            self.group = list(names)
        self.rb_group.setEnabled(bool(self.group))
        self.rb_group.setText(f"No grupo selecionado ({len(self.group)} folhas)" if self.group
                              else "No grupo selecionado")

    def root_on_group(self, names: list[str]) -> bool:
        """Enraíza no ancestral comum de ``names``; pergunta antes se o grupo não for monofilético."""
        if self.original is None:
            return False
        self.set_group(names)
        self.rb_group.setChecked(True)
        return self.apply_rooting()

    def confirm_extras(self, extras: list[str], n_group: int) -> bool:
        shown = "\n".join(f"• {e}" for e in extras[:15]) + ("\n…" if len(extras) > 15 else "")
        answer = QMessageBox.question(
            self, "Grupo não monofilético",
            f"As {n_group} folhas selecionadas não formam um clado com esta árvore.\n"
            f"O ancestral comum inclui mais {len(extras)} folha(s):\n\n{shown}\n\nEnraizar mesmo assim?")
        return answer == QMessageBox.StandardButton.Yes

    def apply_rooting(self) -> bool:
        if self.original is None:
            return False
        tree = self.original.copy()
        rooting: dict = {"mode": "file"}
        try:
            if self.rb_mid.isChecked():
                tree.reroot_midpoint()
                rooting = {"mode": "midpoint"}
            elif self.rb_out.isChecked():
                leaf = self.outgroup.currentText().strip()
                tree.reroot_outgroup(leaf)
                rooting = {"mode": "outgroup", "leaf": leaf}
            elif self.rb_group.isChecked():
                group = set(self.group) & set(tree.leaf_names())
                extras = tree.group_extras(group)
                if extras and not self.confirm_extras(extras, len(group)):
                    return False
                tree.reroot_on_group(group)
                rooting = {"mode": "group", "leaves": sorted(group)}
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Erro ao enraizar")
            return False
        self.rooting = rooting
        self.tree_changed.emit(tree)
        return True

    def reset_rooting(self) -> None:
        """Volta à raiz do arquivo (desfazer um enraizamento)."""
        if self.original is None:
            return
        self.rb_orig.setChecked(True)
        self.rooting = {"mode": "file"}
        self.tree_changed.emit(self.original.copy())

    def apply_rooting_spec(self, spec: dict) -> str | None:
        """Reaplica um enraizamento salvo no projeto (sem perguntas). Devolve um aviso ou None."""
        if self.original is None or not isinstance(spec, dict):
            return None
        mode = spec.get("mode", "file")
        names = set(self.original.leaf_names())
        if mode == "file":
            return None
        tree = self.original.copy()
        try:
            if mode == "midpoint":
                tree.reroot_midpoint()
                self.rb_mid.setChecked(True)
            elif mode == "outgroup":
                leaf = str(spec.get("leaf", ""))
                if leaf not in names:
                    return f"enraizamento: a folha “{leaf}” não está na árvore (mantida a raiz do arquivo)"
                tree.reroot_outgroup(leaf)
                self.outgroup.setCurrentText(leaf)
                self.rb_out.setChecked(True)
            elif mode == "group":
                group = set(spec.get("leaves") or []) & names
                if not group:
                    return "enraizamento: nenhuma folha do grupo está na árvore (mantida a raiz do arquivo)"
                tree.reroot_on_group(group)
                self.set_group(sorted(group))
                self.rb_group.setChecked(True)
            else:
                return f"enraizamento “{mode}” desconhecido (mantida a raiz do arquivo)"
        except Exception as exc:  # noqa: BLE001
            return f"enraizamento não reaplicado: {exc}"
        self.rooting = dict(spec)
        self.tree_changed.emit(tree)
        return None
