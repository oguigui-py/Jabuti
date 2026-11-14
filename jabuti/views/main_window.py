"""Janela principal: abas à esquerda, canvas à direita."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from jabuti import __version__
from jabuti.models.document import apply_edits
from jabuti.models.tree import Tree
from jabuti.views.canvas import TreeCanvas
from jabuti.views.style_panel import StylePanel
from jabuti.views.errors import show_error
from jabuti.views.export import export_pdf, export_png, export_svg
from jabuti.views.tree_renderer import TreeRenderer
from jabuti.views.tree_tab import TreeTab
from jabuti.views.viz_tab import VizTab


def _placeholder(text: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
    lay.addWidget(lbl)
    return w


def _scroll(w: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidget(w)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Jabuti {__version__}")
        self.resize(1300, 850)
        self.setAcceptDrops(True)
        self.tree: Tree | None = None
        self.display_tree: Tree | None = None

        self.tree_tab = TreeTab()
        self.viz_tab = VizTab()
        self.tabs = QTabWidget()
        self.tabs.addTab(_scroll(self.tree_tab), "Árvore")
        self.tabs.addTab(_placeholder("Carregamento de GFF3 e busca de genes — próxima etapa."), "GFF")
        self.tabs.addTab(_placeholder("Metadados TSV/CSV — próxima etapa."), "Metadados")
        self.tabs.addTab(_scroll(self.viz_tab), "Visualização")
        self.tabs.setMinimumWidth(320)

        self.canvas = TreeCanvas()
        self.renderer = TreeRenderer(self.canvas.tree_scene)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Buscar folha…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.returnPressed.connect(self.do_search)
        self.search_box.textChanged.connect(lambda t: t or self.canvas.clear_highlights())
        tb = QHBoxLayout()
        tb.addWidget(self.search_box, 1)
        for label, slot in (
            ("Buscar", self.do_search),
            ("−", lambda: self.canvas.zoom_by(1 / 1.25)),
            ("+", lambda: self.canvas.zoom_by(1.25)),
            ("Ajustar", self.canvas.fit),
        ):
            b = QPushButton(label)
            b.clicked.connect(slot)
            tb.addWidget(b)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addLayout(tb)
        rl.addWidget(self.canvas, 1)

        split = QSplitter()
        split.addWidget(self.tabs)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([360, 940])
        self.setCentralWidget(split)

        # painel de estilo fixo (não flutua, não fecha, não se move)
        self.style_panel = StylePanel()
        self.style_dock = QDockWidget("Estilo", self)
        self.style_dock.setObjectName("style_dock")
        self.style_dock.setWidget(_scroll(self.style_panel))
        self.style_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.style_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.style_dock.setMinimumWidth(340)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.style_dock)

        # redesenho ao vivo com debounce
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(120)
        self._live_timer.timeout.connect(self.render_live)
        self.style_panel.changed.connect(self._live_timer.start)
        self.style_panel.status_message.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.canvas.node_context_requested.connect(self.show_node_menu)

        self.tree_tab.tree_changed.connect(self.on_tree_changed)
        self.viz_tab.generate_requested.connect(self.generate)
        self.viz_tab.export_requested.connect(self.export)
        self._build_menu()
        self.statusBar().showMessage("Abra uma árvore (aba Árvore) ou arraste um arquivo para a janela.")

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("Arquivo")
        a = QAction("Abrir árvore…", self)
        a.setShortcut(QKeySequence.StandardKey.Open)
        a.triggered.connect(self.tree_tab._choose_file)
        m.addAction(a)
        for fmt in ("svg", "pdf", "png"):
            act = QAction(f"Exportar {fmt.upper()}…", self)
            act.triggered.connect(lambda _=False, f=fmt: self.export(f))
            m.addAction(act)
        find = QAction("Buscar folha", self)
        find.setShortcut(QKeySequence.StandardKey.Find)
        find.triggered.connect(lambda: (self.search_box.setFocus(), self.search_box.selectAll()))
        self.addAction(find)

    # ------------------------------------------------------------ ações
    def on_tree_changed(self, tree: Tree) -> None:
        self.tree = tree
        self.style_panel.set_tree(tree, self.viz_tab.use_lengths.isChecked())
        # clados automáticos acompanham a nova raiz; manuais são resolvidos por MRCA
        if self.style_panel.clade_set.auto_mode:
            self.style_panel.detect()
        self.generate()
        self.canvas.fit()

    def current_style(self):  # type: ignore[no-untyped-def]
        return self.style_panel.apply_to(self.viz_tab.render_style())

    def render_live(self) -> None:
        """Redesenha preservando zoom e posição (mudanças no painel de estilo)."""
        self._live_timer.stop()
        if self.tree is None:
            return
        center = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        self.generate()
        self.canvas.centerOn(center)

    def show_node_menu(self, node, global_pos: QPoint) -> None:  # type: ignore[no-untyped-def]
        menu = self.build_node_menu(node)
        if menu is not None:
            menu.exec(global_pos)

    def build_node_menu(self, node) -> QMenu | None:  # type: ignore[no-untyped-def]
        if self.tree is None:
            return None
        leaves = frozenset(l.name for l in node.leaves())
        menu = QMenu(self)
        title = node.name if node.is_leaf else f"Nó interno ({len(leaves)} folhas)"
        menu.addSection(title)
        sp = self.style_panel
        existing = sp.clade_set.find(leaves)
        if existing is None:
            menu.addAction("Definir como clado", lambda: sp.add_manual_clade(leaves))
        else:
            menu.addAction(f"Remover clado “{existing.name}”", lambda: sp.remove_clade_with(leaves))
        if not node.is_leaf:
            menu.addSeparator()
            menu.addAction("Girar nó (inverter filhos)", lambda: sp.rotate(leaves))
            if sp.edits.is_collapsed(leaves):
                menu.addAction("Expandir", lambda: sp.expand(leaves))
            elif node.parent is not None:
                menu.addAction("Colapsar em triângulo", lambda: sp.collapse(leaves))
        return menu

    def generate(self) -> None:
        if self.tree is None:
            self.statusBar().showMessage("Nenhuma árvore carregada.")
            return
        style = self.current_style()
        if self.style_panel.use_lengths != style.use_lengths:
            self.style_panel.set_tree(self.tree, style.use_lengths)
        edits = self.style_panel.edits
        try:
            self.display_tree = apply_edits(self.tree, edits)
            result = self.renderer.render(self.display_tree, style, self.style_panel.clade_set.clades,
                                          edits.collapsed)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Erro ao desenhar")
            return
        self.canvas.show_transparency(style.background is None)
        self.canvas.set_result(result)
        self.style_panel.update_status(result.clades)
        if self.search_box.text().strip():
            self.do_search()
        self.statusBar().showMessage(f"{len(self.tree.leaves())} folhas desenhadas.")

    def do_search(self) -> None:
        q = self.search_box.text()
        if not q.strip():
            self.canvas.clear_highlights()
            return
        matches = self.canvas.search(q)
        if not matches:
            hidden = self.tree is not None and any(q.strip().lower() in n.lower() for n in self.tree.leaf_names())
            if hidden:
                self.statusBar().showMessage(f"“{q}” está dentro de um clado colapsado (clique direito → Expandir).")
            else:
                self.statusBar().showMessage(f"Nenhuma folha contém “{q}”.")
        elif len(matches) == 1:
            self.statusBar().showMessage(f"Encontrada: {matches[0]}")
        else:
            self.statusBar().showMessage(f"{len(matches)} folhas encontradas (centralizado na primeira).")

    def export(self, fmt: str) -> None:
        if self.tree is None:
            show_error(self, Exception("Carregue e gere uma árvore antes de exportar."), "Exportar")
            return
        base = self.tree_tab.path.stem if self.tree_tab.path else "arvore"
        filters = {"svg": "SVG (*.svg)", "pdf": "PDF (*.pdf)", "png": "PNG (*.png)"}
        path, _ = QFileDialog.getSaveFileName(self, f"Exportar {fmt.upper()}", f"{base}.{fmt}", filters[fmt])
        if not path:
            return
        if not path.lower().endswith(f".{fmt}"):
            path += f".{fmt}"
        scene = self.canvas.tree_scene
        try:
            if fmt == "svg":
                export_svg(scene, path)
            elif fmt == "pdf":
                export_pdf(scene, path)
            else:
                export_png(scene, path, self.viz_tab.dpi.value())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Erro ao exportar")
            return
        self.statusBar().showMessage(f"Exportado: {path}")

    # ---------------------------------------------------- drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.tabs.setCurrentIndex(0)
            self.tree_tab.load(Path(urls[0]))
