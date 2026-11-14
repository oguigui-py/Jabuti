"""Janela principal: abas à esquerda, canvas à direita."""

from __future__ import annotations

from pathlib import Path

import os

from PySide6.QtCore import QPoint, QStandardPaths, Qt, QTimer
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
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from jabuti import __version__
from jabuti.models.annotations import (
    OTHER_GENE_COLOR,
    LegendGroup,
    gene_context,
    metadata_colors,
    metadata_column,
    presence_columns,
    presence_legend,
)
from jabuti.models.document import apply_edits
from jabuti.resources import BRAND_GREEN
from jabuti.presets import (
    LoadedPreset,
    load_preset,
    preset_from_dict,
    preset_to_dict,
    save_preset,
)
from jabuti.style import LayoutKind, RenderStyle
from jabuti.models.tree import Tree
from jabuti.views.canvas import TreeCanvas
from jabuti.views.style_panel import StylePanel
from jabuti.views.errors import show_error
from jabuti.views.gff_tab import GffTab
from jabuti.views.metadata_tab import MetadataTab
from jabuti.views.export import export_pdf, export_png, export_svg
from jabuti.views.tree_renderer import TreeRenderer
from jabuti.views.tree_tab import TreeTab
from jabuti.views.viz_tab import VizTab


def user_default_preset_path() -> Path:
    """Arquivo do "meu padrão" (JABUTI_CONFIG_DIR sobrepõe, usado nos testes)."""
    base = os.environ.get("JABUTI_CONFIG_DIR") or QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(base) / "default_preset.json"


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
        self.setWindowTitle("Jabuti")
        self.resize(1300, 850)
        self.setAcceptDrops(True)
        self.tree: Tree | None = None
        self.display_tree: Tree | None = None

        self.tree_tab = TreeTab()
        self.viz_tab = VizTab()
        self.tabs = QTabWidget()
        self.tabs.addTab(_scroll(self.tree_tab), "Árvore")
        self.gff_tab = GffTab()
        self.tabs.addTab(_scroll(self.gff_tab), "GFF")
        self.metadata_tab = MetadataTab()
        self.tabs.addTab(_scroll(self.metadata_tab), "Metadados")
        self.tabs.addTab(_scroll(self.viz_tab), "Visualização")
        self.tabs.setMinimumWidth(360)

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
        split.setSizes([390, 910])
        self.setCentralWidget(split)
        self._build_brand_bar()

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
        self.canvas.selection_changed.connect(self._selection_changed)
        self.style_panel.label_panel.select_leaves.connect(self._select_from_panel)
        self.style_panel.preset_action.connect(self.on_preset_action)
        self.gff_tab.changed.connect(self._live_timer.start)
        self.metadata_tab.changed.connect(self._live_timer.start)
        self.metadata_tab.columns_changed.connect(self._metadata_columns_changed)
        self.metadata_tab.status_message.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.gff_tab.status_message.connect(lambda m: self.statusBar().showMessage(m, 8000))

        self.tree_tab.tree_changed.connect(self.on_tree_changed)
        self.viz_tab.generate_requested.connect(self.generate)
        self.viz_tab.export_requested.connect(self.export)
        self._build_menu()
        self.statusBar().showMessage("Abra uma árvore (aba Árvore) ou arraste um arquivo para a janela.")
        self._load_user_default()

    def _build_brand_bar(self) -> None:
        """Nome "Jabuti" fixo no canto superior esquerdo da janela.

        No macOS o título do sistema é centralizado e não pode ser movido; esta
        barra fixa (unificada com a barra de título no macOS) mostra o nome à
        esquerda em qualquer sistema."""
        bar = QToolBar("Jabuti", self)
        bar.setObjectName("brand_bar")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.toggleViewAction().setVisible(False)
        self.brand_label = QLabel("Jabuti")
        self.brand_label.setObjectName("brand_label")
        self.brand_label.setToolTip(f"Jabuti {__version__}")
        bf = self.brand_label.font()
        bf.setBold(True)
        bf.setPointSizeF(bf.pointSizeF() + 3)
        self.brand_label.setFont(bf)
        dark = self.palette().window().color().lightness() < 110
        # no tema escuro o verde da logo some no fundo; usa um tom mais claro do mesmo verde
        self.brand_label.setStyleSheet(f"color: {'#6fbf8f' if dark else BRAND_GREEN}; padding: 2px 8px;")
        bar.addWidget(self.brand_label)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        self.setUnifiedTitleAndToolBarOnMac(True)

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
        self.gff_tab.set_tree_leaves(tree.leaf_names())
        self.metadata_tab.set_tree_leaves(tree.leaf_names())
        self.style_panel.label_panel.set_leaf_names(tree.leaf_names())
        # clados automáticos acompanham a nova raiz; manuais são resolvidos por MRCA
        if self.style_panel.clade_set.auto_mode:
            self.style_panel.detect()
        self.generate()
        self.canvas.fit()

    def current_style(self):  # type: ignore[no-untyped-def]
        return self.style_panel.apply_to(self.viz_tab.render_style())

    def _metadata_columns_changed(self, columns: list) -> None:
        kinds = {c: self.metadata_tab.column_kind(c) for c in columns}
        self.style_panel.set_metadata_columns(columns, kinds)

    def annotation_columns(self, style: RenderStyle):  # type: ignore[no-untyped-def]
        """Faixas de metadados + heatmap de genes, grupos de legenda e cores por metadado.

        Ordem (da árvore para fora): faixa de clados, faixas de metadados, colunas de genes.
        """
        columns, groups = [], []
        meta_colors: dict[str, str] = {}
        palette = style.palette_colors()
        md = style.metadata
        by_leaf = self.metadata_tab.by_leaf()
        available = set(self.metadata_tab.value_columns())
        if by_leaf and md.color_by in available and (md.color_labels or md.color_branches):
            meta_colors, legend = metadata_colors(by_leaf, md.color_by, palette)
            legend.title = f"Cor: {md.color_by}"
            groups.append(legend)
        for col_name in md.strips:
            if by_leaf and col_name in available:
                col, legend = metadata_column(by_leaf, col_name, palette, md.missing_color, md.strip_width)
                columns.append(col)
                if col_name != md.color_by or not meta_colors:
                    legend.title = f"Faixa: {col_name}"
                    groups.append(legend)
        hm = style.heatmap
        if self.gff_tab.queries and self.gff_tab.genomes:
            gene_cols = presence_columns(self.gff_tab.matrix(), hm.present_color, hm.absent_color,
                                         hm.missing_color, hm.show_counts)
            columns += gene_cols
            groups.append(presence_legend(hm.present_color, hm.absent_color, hm.missing_color))
        if style.layout == LayoutKind.CIRCULAR and columns:
            groups.append(LegendGroup("Anéis (de dentro para fora)",
                                      [(f"{i + 1}. {c.header}", hm.present_color if c.kind == "genes" else "#888888")
                                       for i, c in enumerate(columns)]))
        return columns, groups, meta_colors

    def context_tracks(self, style: RenderStyle):  # type: ignore[no-untyped-def]
        """Trilhas de contexto gênico (só retangular) e a legenda de cores."""
        anchor = self.gff_tab.context_query()
        if anchor is None:
            return None, None
        if style.layout == LayoutKind.CIRCULAR:
            self._render_notes.append("contexto gênico aparece só no layout retangular")
            return None, None
        palette = style.palette_colors()
        color_queries = [(q, palette[i % len(palette)]) for i, q in enumerate(self.gff_tab.queries)]
        tracks = gene_context(self.gff_tab.genomes_by_leaf(), anchor, self.gff_tab.ctx_n.value(), color_queries)
        legend = LegendGroup(f"Contexto de {anchor.title} (±{self.gff_tab.ctx_n.value()})",
                             [(q.title, c) for q, c in color_queries] + [("outros genes", OTHER_GENE_COLOR)])
        return tracks, legend

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
        self._label_menu(menu, node, leaves)
        if not node.is_leaf:
            menu.addSeparator()
            menu.addAction("Girar nó (inverter filhos)", lambda: sp.rotate(leaves))
            if sp.edits.is_collapsed(leaves):
                menu.addAction("Expandir", lambda: sp.expand(leaves))
            elif node.parent is not None:
                menu.addAction("Colapsar em triângulo", lambda: sp.collapse(leaves))
        return menu

    # ------------------------------------------------- rótulos e seleção
    def _label_menu(self, menu: QMenu, node, leaves: frozenset[str]) -> None:  # type: ignore[no-untyped-def]
        """Estilo rápido de rótulos: a seleção atual, ou as folhas do nó clicado."""
        lp = self.style_panel.label_panel
        selected = list(self.canvas.selected)
        if selected:
            target, title = selected, f"Estilizar rótulos selecionados ({len(selected)})"
        else:
            target = sorted(leaves)
            title = "Estilizar rótulo desta folha" if node.is_leaf else f"Estilizar rótulos deste nó ({len(leaves)})"
        menu.addSeparator()
        sub = menu.addMenu(title)
        from jabuti.models.label_groups import HIGHLIGHT_COLORS
        from jabuti.views.widgets.swatches import color_menu

        bg = color_menu(sub, HIGHLIGHT_COLORS, lambda c: c and lp.style_leaves(target, background=c),
                        allow_auto=False)
        bg.setTitle("Fundo (marca-texto)")
        sub.addMenu(bg)
        tx = color_menu(sub, self.style_panel.palette_colors(), lambda c: c and lp.style_leaves(target, text_color=c),
                        allow_auto=False)
        tx.setTitle("Cor do texto")
        sub.addMenu(tx)
        sub.addAction("Negrito", lambda: lp.style_leaves(target, bold=True))
        sub.addAction("Criar grupo (editar no painel)…", lambda: self._create_label_group(target))
        if selected:
            menu.addAction("Limpar seleção", self.canvas.clear_selection)

    def _create_label_group(self, leaves) -> None:  # type: ignore[no-untyped-def]
        sp = self.style_panel
        if sp.label_panel.create_group(leaves, "selection") is not None:
            sp.sections["labels"].set_expanded(True)

    def _label_legend(self, label_groups) -> list:  # type: ignore[no-untyped-def]
        if not label_groups.show_in_legend:
            return []
        entries = [(g.name, g.look.background or g.look.text_color or self.current_style().label.color)
                   for g in label_groups.groups if g.visible]
        return [LegendGroup("Grupos de rótulos", entries)] if entries else []

    def _selection_changed(self, names: list) -> None:
        lp = self.style_panel.label_panel
        lp.set_selection(names)
        if len(names) == 1:
            self.statusBar().showMessage(lp.describe_leaf(names[0]), 8000)
        elif names:
            self.statusBar().showMessage(f"{len(names)} folhas selecionadas (clique direito → Estilizar rótulos).",
                                         8000)

    def _select_from_panel(self, names: list) -> None:
        self.canvas.set_selection(names)
        drawn = len(self.canvas.selected)
        hidden = len(names) - drawn
        msg = f"{drawn} folha(s) selecionada(s)."
        if hidden:
            msg += f" {hidden} estão dentro de clados colapsados."
        self.statusBar().showMessage(msg, 8000)

    def generate(self) -> None:
        if self.tree is None:
            self.statusBar().showMessage("Nenhuma árvore carregada.")
            return
        style = self.current_style()
        self._render_notes: list[str] = []
        if self.style_panel.use_lengths != style.use_lengths:
            self.style_panel.set_tree(self.tree, style.use_lengths)
        edits = self.style_panel.edits
        try:
            self.display_tree = apply_edits(self.tree, edits)
            columns, groups, meta_colors = self.annotation_columns(style)
            context, ctx_group = self.context_tracks(style)
            if ctx_group is not None:
                groups.append(ctx_group)
            label_groups = self.style_panel.label_groups
            groups.extend(self._label_legend(label_groups))
            result = self.renderer.render(self.display_tree, style, self.style_panel.clade_set.clades,
                                          edits.collapsed, columns, meta_colors, context, label_groups)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Erro ao desenhar")
            return
        self.canvas.show_transparency(style.background is None)
        self.canvas.set_result(result)
        self.style_panel.update_status(result.clades, groups)
        self.style_panel.label_panel.refresh()
        if self.search_box.text().strip():
            self.do_search()
        msg = f"{len(self.tree.leaves())} folhas desenhadas."
        if self._render_notes:
            msg += " Obs.: " + "; ".join(self._render_notes) + "."
        self.statusBar().showMessage(msg)

    # ------------------------------------------------------------ presets
    def collect_preset(self, include_tree_state: bool = True) -> dict:
        sp = self.style_panel
        style = self.current_style()
        if include_tree_state:
            return preset_to_dict(style, sp.clade_set, sp.edits, sp.detection_dict(), sp.label_groups)
        return preset_to_dict(style, detection=sp.detection_dict())

    def apply_preset(self, loaded: LoadedPreset) -> list[str]:
        sp = self.style_panel
        self.viz_tab.load_style(loaded.style)
        warnings = list(loaded.warnings) + sp.load_style(loaded.style)
        sp.load_detection(loaded.detection)
        sp.load_tree_state(loaded.clade_set, loaded.edits)
        if loaded.label_groups is not None:
            groups = loaded.label_groups
            if self.tree is not None:
                groups, ignored, dropped = groups.restricted_to(self.tree.leaf_names())
                if ignored:
                    note = f"{ignored} folha(s) de grupos de rótulo ignoradas (não existem na árvore aberta)"
                    if dropped:
                        note += f"; {dropped} grupo(s) ficaram vazios e foram descartados"
                    warnings.append(note + ".")
                    self._label_note = note + "."
            sp.label_panel.load_groups(groups)
        if self.tree is not None:
            self.render_live()
        return warnings

    def _report_preset(self, what: str, warnings: list[str]) -> None:
        if warnings:
            show_error(self, Exception(f"{what} com avisos:\n• " + "\n• ".join(warnings[:12])), "Preset")
        note, self._label_note = getattr(self, "_label_note", ""), ""
        self.statusBar().showMessage(f"{what} — {note}" if note else what, 12000)

    def _load_user_default(self) -> None:
        path = user_default_preset_path()
        self.style_panel.set_default_info(str(path) if path.exists() else None)
        if not path.exists():
            return
        try:
            loaded = load_preset(path)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Meu padrão não pôde ser lido")
            return
        # o padrão pessoal traz só estilo e detecção
        self.apply_preset(loaded._replace(clade_set=None, edits=None, label_groups=None))

    def on_preset_action(self, action: str) -> None:
        try:
            if action == "save":
                path, _ = QFileDialog.getSaveFileName(self, "Salvar preset", "jabuti_preset.json", "Preset (*.json)")
                if path:
                    save_preset(path if path.lower().endswith(".json") else path + ".json", self.collect_preset())
                    self.statusBar().showMessage(f"Preset salvo: {path}", 8000)
            elif action == "load":
                path, _ = QFileDialog.getOpenFileName(self, "Carregar preset", "", "Preset (*.json);;Todos (*)")
                if path:
                    self._report_preset(f"Preset carregado: {Path(path).name}", self.apply_preset(load_preset(path)))
            elif action == "save_default":
                path = save_preset(user_default_preset_path(), self.collect_preset(include_tree_state=False))
                self.style_panel.set_default_info(str(path))
                self.statusBar().showMessage("Estilo atual salvo como seu padrão.", 8000)
            elif action == "restore":
                factory = preset_from_dict(preset_to_dict(RenderStyle()))
                self._report_preset("Padrão de fábrica restaurado (clados, rotações e colapsos mantidos).",
                                    self.apply_preset(factory))
            elif action == "forget_default":
                user_default_preset_path().unlink(missing_ok=True)
                self.style_panel.set_default_info(None)
                self.statusBar().showMessage("Padrão pessoal removido.", 8000)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Preset")

    def do_search(self) -> None:
        q = self.search_box.text()
        if not q.strip():
            self.canvas.clear_highlights()
            return
        matches = self.canvas.search(q)
        self.canvas.set_selection(matches)   # resultados da busca viram a seleção
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

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self.gff_tab.shutdown()  # não deixa thread de leitura viva ao fechar
        super().closeEvent(event)

    # ---------------------------------------------------- drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.tabs.setCurrentIndex(0)
            self.tree_tab.load(Path(urls[0]))
