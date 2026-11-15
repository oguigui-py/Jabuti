"""Janela principal: abas à esquerda, canvas à direita."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path


from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
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
from jabuti.models.datatables import numeric_column
from jabuti.models.document import apply_edits, collapsed_nodes
from jabuti.models.label_groups import LabelGroupSet
from jabuti.models.colormaps import SCALES
from jabuti.models.tracks import (
    CLADE_STRIP,
    GENE_BLOCK,
    BarTrack,
    StackedTrack,
    bar_track,
    fmt_value,
    matrix_columns,
    order_keys,
    select_features,
    stacked_track,
)
from jabuti.resources import BRAND_GREEN
from jabuti.settings import config_dir, open_file, pick_dir, save_file
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
from jabuti.views.export import export_pdf, export_png, export_svg, export_tiff
from jabuti.views.figure_panel import FigureDock, FigurePanel
from jabuti.views.tree_renderer import TreeRenderer
from jabuti.views.tooltips import apply_tooltips
from jabuti.views.tree_tab import TreeTab
from jabuti.views.viz_tab import VizTab


def user_default_preset_path() -> Path:
    """Arquivo do "meu padrão" (JABUTI_CONFIG_DIR sobrepõe, usado nos testes)."""
    return config_dir() / "default_preset.json"


README_URL = "https://github.com/oguigui-py/Jabuti#readme"


def readme_url() -> str:
    """README local (rodando do código-fonte) ou, se não houver, o do repositório."""
    from PySide6.QtCore import QUrl

    from jabuti.resources import readme_path

    p = readme_path()
    return QUrl.fromLocalFile(str(p)).toString() if p is not None else README_URL


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
        self.search_box.setMinimumWidth(140)
        self.search_box.setToolTip("Busca folhas pelo nome (parte do nome basta). Atalho: Cmd/Ctrl+F")
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

        # painel "Figura" fixo e recolhível na borda esquerda
        self.figure_panel = FigurePanel()
        self.figure_panel.metadata_by_leaf = self.metadata_tab.by_leaf
        self.figure_panel.metadata_columns = self.metadata_tab.value_columns
        self.figure_panel.edits = self.style_panel.edits          # mesmas edições da árvore
        self.figure_holder = FigureDock(self.figure_panel)
        self.figure_dock = QDockWidget("Figura", self)
        self.figure_dock.setObjectName("figure_dock")
        self.figure_dock.setTitleBarWidget(QWidget())
        self.figure_dock.setWidget(self.figure_holder)
        self.figure_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.figure_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.figure_dock)
        self.figure_holder.collapsed_changed.connect(self._figure_collapsed)
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is not None:
            self.resize(min(1640, screen.width()), min(900, screen.height()))

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
        self.figure_panel.changed.connect(self._live_timer.start)
        self.figure_panel.status_message.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.figure_panel.itol.collapse_changed.connect(self._itol_collapse)
        self.figure_panel.itol.export_requested.connect(self.export_itol)
        self.figure_panel.root_group_requested.connect(self.root_on_selection)
        self.figure_panel.hidden_changed.connect(self.canvas.clear_selection)
        self.figure_panel.clade_from_list_requested.connect(self.clade_from_list)
        self.metadata_tab.columns_changed.connect(lambda _c: self.figure_panel.metadata_changed())
        self.viz_tab.layout_cb.currentIndexChanged.connect(self._layout_changed)
        for w in (self.viz_tab.fan_angle, self.viz_tab.fan_start, self.viz_tab.rotation):
            w.valueChanged.connect(self._live_timer.start)
        for w in (self.viz_tab.mirror, self.viz_tab.daylight):
            w.toggled.connect(self._live_timer.start)
        self.metadata_tab.changed.connect(self._live_timer.start)
        self.metadata_tab.columns_changed.connect(self._metadata_columns_changed)
        self.metadata_tab.status_message.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.gff_tab.status_message.connect(lambda m: self.statusBar().showMessage(m, 8000))

        self.tree_tab.tree_changed.connect(self.on_tree_changed)
        self.viz_tab.generate_requested.connect(self.generate)
        self.viz_tab.export_requested.connect(self.export)
        self._build_menu()
        apply_tooltips(self)
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
        # só no macOS nativo: no Qt 6 isto liga WA_TranslucentBackground, e fora do Cocoa
        # (Windows, Linux, offscreen) o fundo da janela ficaria transparente
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.platformName() == "cocoa":
            self.setUnifiedTitleAndToolBarOnMac(True)

    def _action(self, menu: QMenu, text: str, slot, shortcut=None, tip: str = "") -> QAction:  # type: ignore[no-untyped-def]
        a = QAction(text, self)
        if shortcut is not None:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setStatusTip(tip)
            a.setToolTip(tip)
        a.triggered.connect(lambda _=False: slot())
        menu.addAction(a)
        return a

    def _build_menu(self) -> None:
        """Menus Arquivo, Editar, Exibir e Ajuda. Os atalhos usam ``QKeySequence.StandardKey``,
        que vira Cmd no macOS e Ctrl no Windows/Linux."""
        SK = QKeySequence.StandardKey
        bar = self.menuBar()
        self.actions_by_name: dict[str, QAction] = {}
        act = self.actions_by_name

        m = bar.addMenu("&Arquivo")
        act["open"] = self._action(m, "Abrir árvore…", self.tree_tab._choose_file, SK.Open,
                                   "Abre uma árvore Newick (.nwk, .treefile, .tre…)")
        self.recent_menu = m.addMenu("Abrir recente")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        self._fill_recent_menu()
        m.addSeparator()
        act["import_itol"] = self._action(m, "Importar anotação iTOL…", self.figure_panel.itol._choose, "Ctrl+Shift+I",
                                          "Arquivos de anotação do iTOL (cores, faixas, barras, símbolos…)")
        act["import_meta"] = self._action(m, "Importar metadados…", self._import_metadata, "Ctrl+Shift+M",
                                          "Tabela TSV/CSV com uma coluna de genomas")
        act["import_gff"] = self._action(m, "Adicionar GFF3…", self._import_gff, None,
                                         "Anotações de genes (GFF3) para o heatmap e o contexto gênico")
        m.addSeparator()
        exp = m.addMenu("Exportar")
        for fmt in ("svg", "pdf", "png", "tiff"):
            act[f"export_{fmt}"] = self._action(exp, f"Figura em {fmt.upper()}…", lambda f=fmt: self.export(f),
                                                "Ctrl+E" if fmt == "svg" else None)
        exp.addSeparator()
        act["export_itol"] = self._action(exp, "Para o iTOL…", lambda: self.export_itol(), "Ctrl+Shift+E",
                                          "Árvore + um arquivo por anotação, no formato do iTOL")
        m.addSeparator()
        act["quit"] = self._action(m, "Sair", self.close, SK.Quit)
        act["quit"].setMenuRole(QAction.MenuRole.QuitRole)

        m = bar.addMenu("&Editar")
        act["find"] = self._action(m, "Buscar folha", self._focus_search, SK.Find,
                                   "Busca pelo nome (parte do nome basta)")
        act["clear_sel"] = self._action(m, "Limpar seleção", self._clear_selection, "Esc")
        m.addSeparator()
        act["redraw"] = self._action(m, "Redesenhar", self.generate, SK.Refresh,
                                     "Gera a figura de novo com as opções atuais")
        if act["redraw"].shortcut().isEmpty():
            act["redraw"].setShortcut(QKeySequence("Ctrl+R"))

        m = bar.addMenu("E&xibir")
        act["zoom_in"] = self._action(m, "Ampliar", lambda: self.canvas.zoom_by(1.25), SK.ZoomIn)
        act["zoom_out"] = self._action(m, "Reduzir", lambda: self.canvas.zoom_by(1 / 1.25), SK.ZoomOut)
        act["fit"] = self._action(m, "Ajustar à janela", self.canvas.fit, "Ctrl+0")
        m.addSeparator()
        act["toggle_figure"] = self._action(
            m, "Mostrar/ocultar painel Figura",
            lambda: self.figure_holder.set_collapsed(not self.figure_holder.collapsed), "Ctrl+Shift+F")

        m = bar.addMenu("Aj&uda")
        act["about"] = self._action(m, "Sobre o Jabuti", self.show_about)
        act["about"].setMenuRole(QAction.MenuRole.AboutRole)
        act["readme"] = self._action(m, "Abrir o README (manual)", self.open_readme, SK.HelpContents)
        act["log"] = self._action(m, "Mostrar pasta do log de erros", self.open_log_dir)

    # ------------------------------------------------------------ menus: apoio
    def _focus_search(self) -> None:
        self.search_box.setFocus()
        self.search_box.selectAll()

    def _clear_selection(self) -> None:
        self.canvas.clear_selection()
        self.canvas.clear_highlights()
        if self.search_box.hasFocus():
            self.search_box.clear()

    def _import_metadata(self) -> None:
        self.tabs.setCurrentIndex(2)
        self.metadata_tab._choose_file()

    def _import_gff(self) -> None:
        self.tabs.setCurrentIndex(1)
        self.gff_tab._choose_files()

    def _fill_recent_menu(self) -> None:
        from jabuti.settings import clear_recent, recent_files

        menu = self.recent_menu
        menu.clear()
        try:
            items = recent_files()
        except Exception:  # noqa: BLE001
            items = []
        for p in items:
            a = menu.addAction(Path(p).name)
            a.setToolTip(p)
            a.setStatusTip(p)
            a.triggered.connect(lambda _=False, path=p: self.open_tree(path))
        if not items:
            menu.addAction("(nenhum arquivo recente)").setEnabled(False)
        menu.addSeparator()
        clear = menu.addAction("Limpar lista")
        clear.setEnabled(bool(items))
        clear.triggered.connect(lambda: (clear_recent(), self._fill_recent_menu()))

    def open_tree(self, path: str | Path) -> bool:
        """Abre uma árvore (menu, recentes, linha de comando)."""
        self.tabs.setCurrentIndex(0)
        return self.tree_tab.load(path)

    def about_text(self) -> str:
        from jabuti.logs import log_path

        return (f"<h2>Jabuti {__version__}</h2>"
                "<p>Visualizador offline de árvores filogenéticas de procariotos.</p>"
                "<p>Produced by Laboratório de Genômica Eco-evolutiva Microbiana<br>"
                "Designed by Guilherme Gonçalves</p>"
                f"<p><a href=\"{readme_url()}\">Manual (README)</a></p>"
                f"<p><small>Configuração: {config_dir()}<br>Log de erros: {log_path()}</small></p>")

    def show_about(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from jabuti.resources import load_logo_pixmap

        box = QMessageBox(self)
        box.setWindowTitle("Sobre o Jabuti")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(self.about_text())
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        try:
            pm = load_logo_pixmap(96, self.devicePixelRatioF())
            if not pm.isNull():
                box.setIconPixmap(pm)
        except Exception:  # noqa: BLE001
            pass
        box.exec()

    def open_readme(self) -> bool:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        return QDesktopServices.openUrl(QUrl(readme_url()))

    def open_log_dir(self) -> bool:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from jabuti.logs import log_dir

        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    # ------------------------------------------------------------ ações
    def on_tree_changed(self, tree: Tree) -> None:
        self.tree = tree
        self.style_panel.set_tree(tree, self.viz_tab.use_lengths.isChecked())
        self.gff_tab.set_tree_leaves(tree.leaf_names())
        self.metadata_tab.set_tree_leaves(tree.leaf_names())
        self.style_panel.label_panel.set_leaf_names(tree.leaf_names())
        self.figure_panel.set_leaves(tree.leaf_names())
        # clados automáticos acompanham a nova raiz; manuais são resolvidos por MRCA
        if self.style_panel.clade_set.auto_mode:
            self.style_panel.detect()
        self.generate()
        self.canvas.fit()

    def current_style(self):  # type: ignore[no-untyped-def]
        style = self.style_panel.apply_to(self.viz_tab.render_style())
        self.figure_panel.set_palette(style.palette_colors())
        return self.figure_panel.apply_to(style)

    def _layout_changed(self, _i: int = 0) -> None:
        kind = self.viz_tab.layout_cb.currentData()
        self.figure_panel.set_layout(kind)
        self.style_panel.set_layout(kind)

    def _figure_collapsed(self, on: bool) -> None:
        width = 30 if on else FigureDock.EXPANDED_WIDTH
        self.resizeDocks([self.figure_dock], [width], Qt.Orientation.Horizontal)

    def _metadata_columns_changed(self, columns: list) -> None:
        kinds = {c: self.metadata_tab.column_kind(c) for c in columns}
        self.style_panel.set_metadata_columns(columns, kinds)

    def annotation_columns(self, style: RenderStyle):  # type: ignore[no-untyped-def]
        """Trilhas de dados (na ordem do painel Figura), grupos de legenda e cores por metadado.

        Ordem padrão (da árvore para fora): faixa de clados, faixas de metadados, heatmap de
        genes e, por fim, as colunas do painel Figura (novas trilhas entram no fim).
        """
        groups = []
        meta_colors: dict[str, str] = {}
        palette = style.palette_colors()
        md = style.metadata
        fig = style.figure
        shown = set(self.display_tree.leaf_names()) if self.display_tree is not None else None

        def visible(rows: dict) -> dict:
            """Só folhas desenhadas: ocultas não entram em mínimos, máximos nem faixas."""
            return rows if shown is None else {k: v for k, v in rows.items() if k in shown}

        by_leaf = visible(self.metadata_tab.by_leaf())
        available = set(self.metadata_tab.value_columns())
        if by_leaf and md.color_by in available and (md.color_labels or md.color_branches):
            meta_colors, legend = metadata_colors(by_leaf, md.color_by, palette,
                                                  scale=style.scale_for(md.color_by))
            legend.title = f"Cor: {md.color_by}"
            groups.append(legend)
        blocks: dict[str, list] = {}
        labels: dict[str, str] = {}
        legends: dict[str, list] = {}     # legenda de cada trilha (some quando a trilha é ocultada)
        export_legends: dict[str, list] = {}   # legendas só para a exportação iTOL
        if style.clades.outer_strip:
            blocks[CLADE_STRIP] = [CLADE_STRIP]
            labels[CLADE_STRIP] = "Faixa de clados"
        for col_name in md.strips:
            if by_leaf and col_name in available:
                col, legend = metadata_column(by_leaf, col_name, palette, md.missing_color, md.strip_width,
                                              scale=style.scale_for(col_name))
                blocks[col.key] = [col]
                labels[col.key] = f"Faixa: {col_name}"
                if col_name != md.color_by or not meta_colors:
                    legend.title = f"Faixa: {col_name}"
                    legends[col.key] = [legend]
                export_legends[col.key] = [LegendGroup(col_name, list(legend.entries), legend.kind,
                                                       list(legend.stops), list(legend.ticks))]
        hm = style.heatmap
        if self.gff_tab.queries and self.gff_tab.genomes:
            blocks[GENE_BLOCK] = presence_columns(self.gff_tab.matrix(), hm.present_color, hm.absent_color,
                                                  hm.missing_color, hm.show_counts)
            labels[GENE_BLOCK] = f"Heatmap de genes ({len(blocks[GENE_BLOCK])} colunas)"
            legends[GENE_BLOCK] = [presence_legend(hm.present_color, hm.absent_color, hm.missing_color)]
        fp = self.figure_panel
        for b in fig.bars:
            rows = visible(fp.by_leaf(b.source))
            values = numeric_column(rows, b.column)
            if not values:
                self._render_notes.append(f"barras “{b.column}” sem dados ({fp.source_label(b.source)})")
                continue
            if b.color_mode == "metadata" and not meta_colors:
                self._render_notes.append(f"barras “{b.column}”: escolha “Colorir por” em Estilo → Metadados")
            blocks[f"bar:{b.id}"] = [bar_track(
                f"bar:{b.id}", b.column, values, vmin=b.vmin, vmax=b.vmax, color=b.color,
                color_mode=b.color_mode, colors=meta_colors, refs=list(b.refs), show_values=b.show_values,
                width=b.width, missing_color=md.missing_color, log=b.log)]
            labels[f"bar:{b.id}"] = f"Barras: {b.column}"
            if blocks[f"bar:{b.id}"][0].nonpositive:
                self._render_notes.append(f"barras “{b.column}” em escala log: {blocks[f'bar:{b.id}'][0].nonpositive} "
                                          "valor(es) ≤ 0 ficaram sem barra")
        for st in fig.stacked:
            rows = visible(fp.by_leaf(st.source))
            series = [c for c in st.columns if numeric_column(rows, c)]
            if not series:
                self._render_notes.append(f"barras empilhadas “{st.name or '/'.join(st.columns)}” sem dados")
                continue
            colors = [st.colors[st.columns.index(c)] if st.columns.index(c) < len(st.colors)
                      else palette[st.columns.index(c) % len(palette)] for c in series]
            header = st.name or "/".join(series)
            track = stacked_track(f"stacked:{st.id}", header, series, colors,
                                  {c: numeric_column(rows, c) for c in series}, st.vmax,
                                  width=st.width, missing_color=md.missing_color)
            blocks[track.key] = [track]
            labels[track.key] = f"Empilhadas: {header}"
            legends[track.key] = [LegendGroup(f"Séries: {header}", list(zip(series, colors)))]
        row_h = style.label.size * style.leaf_spacing
        for mx in fig.matrices:
            rows = visible(fp.by_leaf(mx.source))
            features = select_features(rows, fp.columns_of(mx.source), mx.select, mx.features, mx.top_n)
            title = mx.name or mx.source or "matriz"
            if not features:
                self._render_notes.append(f"matriz “{title}” sem características (ou tabela não carregada)")
                continue
            cols, cs = matrix_columns(f"matrix:{mx.id}", rows, features, mx.colormap, mx.scale, mx.vmin,
                                      mx.vmax, mx.show_values, row_h * mx.cell_width, md.missing_color,
                                      mx.header_rotation)
            blocks[f"matrix:{mx.id}"] = cols
            labels[f"matrix:{mx.id}"] = f"Matriz: {title} ({len(cols)} colunas)"
            scale = "" if mx.scale == "linear" else f" — escala {SCALES[mx.scale]}"
            legends[f"matrix:{mx.id}"] = [LegendGroup(f"{title}{scale}", [("sem dado", md.missing_color)], "colorbar",
                                      list(cs.stops), [(f, fmt_value(round(v, 1 if abs(v) < 10 else 0))) for f, v in cs.ticks(3)])]
        fx = self.itol_effects(style)
        for ic in fx.columns:
            blocks[ic.key] = list(ic.tracks)
            labels[ic.key] = ic.label
            if ic.legend is not None:
                legends[ic.key] = [ic.legend]
        groups.extend(fx.legends)
        keys = order_keys(list(blocks), fig.track_order, fig.hidden_tracks)
        self.figure_panel.set_available_tracks(
            [(k, labels.get(k, k)) for k in order_keys(list(blocks), fig.track_order)])
        for k in keys:
            groups.extend(legends.get(k, []))
        from jabuti.exporters.itol_export import TrackBlock

        self._export_blocks = [TrackBlock(k, labels.get(k, k), list(blocks[k]),
                                          export_legends.get(k) or legends.get(k, [])) for k in keys]
        columns = [t for k in keys for t in blocks[k]]
        rings = [t for t in columns if t != CLADE_STRIP]
        if LayoutKind(style.layout) == LayoutKind.UNROOTED:
            # sem colunas na não enraizada: só as legendas que não dependem delas
            if any(k != CLADE_STRIP for k in keys):
                self._render_notes.append("colunas de dados não se aplicam à árvore não enraizada")
            groups = [g for g in groups if not any(g in v for v in legends.values())]
            return [], groups, meta_colors
        if LayoutKind(style.layout).is_radial and rings:
            groups.append(LegendGroup("Anéis (de dentro para fora)",
                                      [(f"{i + 1}. {c.header}", self._ring_color(c, hm.present_color))
                                       for i, c in enumerate(rings)]))
        return columns, groups, meta_colors

    @staticmethod
    def _ring_color(track, present: str) -> str | None:  # type: ignore[no-untyped-def]
        if isinstance(track, BarTrack):
            return track.color
        if isinstance(track, StackedTrack):
            return track.colors[0]
        if track.kind == "binary":
            return track.shape_color
        if track.kind == "matrix":
            return None               # a cor depende do valor: só o nome (a escala está na barra de cor)
        return present if track.kind == "genes" else "#888888"

    def context_tracks(self, style: RenderStyle):  # type: ignore[no-untyped-def]
        """Trilhas de contexto gênico (só retangular) e a legenda de cores."""
        anchor = self.gff_tab.context_query()
        if anchor is None:
            return None, None
        if not LayoutKind(style.layout).is_rect:
            self._render_notes.append("contexto gênico aparece só nos layouts retangular e diagonal")
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
        self._prune_menu(menu, node, leaves)
        if not node.is_leaf:
            menu.addSeparator()
            menu.addAction("Girar nó (inverter filhos)", lambda: sp.rotate(leaves))
            if sp.edits.is_collapsed(leaves):
                menu.addAction("Expandir", lambda: sp.expand(leaves))
            elif node.parent is not None:
                menu.addAction("Colapsar em triângulo", lambda: sp.collapse(leaves))
        return menu

    def _prune_menu(self, menu: QMenu, node, leaves: frozenset[str]) -> None:  # type: ignore[no-untyped-def]
        """Enraizar no grupo, ocultar folhas e encurtar o ramo."""
        fp = self.figure_panel
        selected = list(self.canvas.selected)
        menu.addSeparator()
        if selected:
            menu.addAction(f"Enraizar no grupo selecionado ({len(selected)})", self.root_on_selection)
            menu.addAction(f"Ocultar folhas selecionadas ({len(selected)})", lambda: fp.hide_leaves(selected))
        elif node.is_leaf:
            menu.addAction("Ocultar esta folha", lambda: fp.hide_leaves([node.name]))
        else:
            menu.addAction(f"Ocultar estas {len(leaves)} folhas", lambda: fp.hide_leaves(leaves))
        if node.parent is None or self.tree is None:
            return
        edits = self.style_panel.edits
        if edits.short_branch(leaves) is not None:
            menu.addAction("Desfazer encurtamento do ramo", lambda: self.unshorten_branch(leaves))
        elif node.length:
            menu.addAction("Encurtar este ramo (marca //)", lambda: self.shorten_branch(leaves))

    def shorten_branch(self, leaves: frozenset[str]) -> None:
        """Encurta o ramo; o comprimento inicial é o maior dos outros ramos (editável no painel)."""
        tree = self.display_tree or self.tree
        if tree is None:
            return
        from jabuti.models.document import resolve_nodes

        nodes = resolve_nodes(tree, [leaves])
        target = nodes[0] if nodes else None
        others = [n.length for n in tree.root.traverse_preorder()
                  if n is not tree.root and n is not target and n.length is not None]
        current = target.length if target is not None and target.length else 0.0
        default = max(others, default=current / 2)
        if default >= current:
            default = current / 2
        self.style_panel.edits.set_short(leaves, round(default, 6))
        self.figure_panel.refresh_pruning()
        self.figure_panel.refresh_names()
        self.figure_panel.sections["pruning"].set_expanded(True)
        self.render_live()
        self.statusBar().showMessage("Ramo encurtado (comprimento ajustável no painel Figura → "
                                     "Enraizamento e poda).", 8000)

    def unshorten_branch(self, leaves: frozenset[str]) -> None:
        self.style_panel.edits.unshort(leaves)
        self.figure_panel.refresh_pruning()
        self.figure_panel.refresh_names()
        self.render_live()

    def display_names(self, style: RenderStyle) -> dict[str, str]:
        from jabuti.models.display_names import display_names

        if self.display_tree is None:
            return {}
        fp = self.figure_panel
        mapping = {**self.itol_effects(style).names, **fp.name_map}    # a tabela de nomes vence o LABELS
        return display_names(self.display_tree.leaf_names(), style.figure.names, mapping,
                             self.style_panel.edits.marked)

    def _itol_collapse(self, entry, on: bool) -> None:  # type: ignore[no-untyped-def]
        """COLLAPSE do iTOL: entra nos colapsos normais (o "Expandir" funciona como sempre);
        desligar ou remover o dataset expande de novo os clados que ele colapsou."""
        from jabuti.models.itol_apply import collapse_sets

        edits = self.style_panel.edits
        if on:
            if self.tree is None:
                return
            tree = self.display_tree or apply_edits(self.tree, edits)
            entry.collapsed_sets = collapse_sets(entry, tree, edits.hidden)
            for leaves in entry.collapsed_sets:
                edits.collapse(leaves)
        else:
            for leaves in entry.collapsed_sets:
                edits.expand(leaves)
            entry.collapsed_sets = []
        self._live_timer.start()

    def itol_effects(self, style: RenderStyle):  # type: ignore[no-untyped-def]
        """Anotações iTOL aplicadas à árvore desenhada (calculadas uma vez por desenho)."""
        from jabuti.models.itol_apply import ItolEffects, apply_itol

        tree = self.display_tree
        entries = self.figure_panel.itol.entries
        if tree is None or not entries:
            return ItolEffects()
        cache = getattr(self, "_itol_cache", None)
        if cache is not None and cache[0] is tree:
            return cache[1]
        fx = apply_itol(entries, tree, self.style_panel.edits.hidden, style.metadata.missing_color)
        self._itol_cache = (tree, fx)
        return fx

    def clade_from_list(self, names: list, name: str, color: str) -> None:
        """Clado pelo ancestral comum dos nomes colados (avisa se não for monofilético)."""
        from PySide6.QtWidgets import QMessageBox

        from jabuti.models.clades import clade_from_names

        fp = self.figure_panel
        if self.tree is None:
            fp.list_report.setText("Abra uma árvore primeiro.")
            return
        tree = self.display_tree or self.tree
        leaves, unknown, extras = clade_from_names(tree, names)
        notes = []
        if unknown:
            more = "…" if len(unknown) > 5 else ""
            notes.append(f"⚠ Não encontrados ({len(unknown)}): {', '.join(unknown[:5])}{more}")
        if not leaves:
            fp.list_report.setText("<br>".join(notes) or "Nenhum nome encontrado na árvore.")
            return
        if extras:
            shown = "\n".join(f"• {e}" for e in extras[:15]) + ("\n…" if len(extras) > 15 else "")
            answer = QMessageBox.question(
                self, "Grupo não monofilético",
                f"Os nomes não formam um clado. O ancestral comum inclui mais {len(extras)} folha(s):\n\n"
                f"{shown}\n\nCriar o clado mesmo assim (com essas folhas)?")
            if answer != QMessageBox.StandardButton.Yes:
                fp.list_report.setText("<br>".join(notes + [f"Cancelado: {len(extras)} folha(s) extra(s)."]))
                return
            notes.append(f"Inclui {len(extras)} folha(s) extra(s) (não monofilético).")
        sp = self.style_panel
        clade = sp.clade_set.add_manual(leaves, name or None, color)
        sp.clade_list.refresh()
        sp.changed.emit()
        fp.list_report.setText("<br>".join([f"Clado “{clade.name}” criado com {len(leaves)} folhas."] + notes))

    def root_on_selection(self) -> None:
        names = list(self.canvas.selected)
        if not names:
            self.statusBar().showMessage("Selecione folhas (Cmd/Shift+clique ou busca) para enraizar no grupo.", 8000)
            return
        if self.tree_tab.root_on_group(names):
            self.statusBar().showMessage(f"Enraizado no ancestral comum de {len(names)} folha(s).", 8000)

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
        self.figure_panel.set_selection(names)
        self.tree_tab.set_group(names)
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
            self._itol_cache = None
            itol = self.itol_effects(style)
            columns, groups, meta_colors = self.annotation_columns(style)
            context, ctx_group = self.context_tracks(style)
            if ctx_group is not None:
                groups.append(ctx_group)
            label_groups = self.style_panel.label_groups
            groups.extend(self._label_legend(label_groups))
            if itol.label_groups:       # estilos do iTOL por baixo dos grupos do usuário (os seus vencem)
                label_groups = LabelGroupSet(itol.label_groups + label_groups.groups, label_groups.show_in_legend)
            lv = style.figure.support_levels
            if lv.enabled and lv.legend and self.display_tree.max_support_values():
                from jabuti.models.support import level_labels, value_name

                name = value_name(lv.index, self.display_tree.max_support_values())
                groups.append(LegendGroup(f"Suporte ({name})", list(zip(level_labels(lv.cutoffs), lv.colors))))
            if self.display_tree.broken and style.figure.break_legend:
                groups.append(LegendGroup("Escala", [(f"// {style.figure.break_legend_text}", None)]))
            result = self.renderer.render(self.display_tree, style, self.style_panel.clade_set.clades,
                                          edits.collapsed, columns, meta_colors, context, label_groups,
                                          legend=groups, hidden=edits.hidden,
                                          names=self.display_names(style), highlights=edits.highlights,
                                          branch_looks=itol.branch_looks, ranges=itol.ranges,
                                          marks=itol.marks)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Erro ao desenhar")
            return
        self._render_notes += [n for n in result.notes if n not in self._render_notes]
        self._snapshot = self._make_snapshot(style, result, meta_colors, label_groups, itol, context)
        from jabuti.models.support import tree_summary

        self.figure_panel.set_summary(tree_summary(self.display_tree, len(edits.hidden & set(self.tree.leaf_names()))))
        self.canvas.show_transparency(style.background is None)
        self.canvas.set_result(result)
        self.style_panel.update_status(result.clades, groups)
        self.style_panel.label_panel.refresh()
        if self.search_box.text().strip():
            self.do_search()
        n_hidden = len(edits.hidden & set(self.tree.leaf_names()))
        msg = f"{len(self.display_tree.leaves())} folhas desenhadas."
        if n_hidden:
            msg += f" {n_hidden} oculta(s)."
        if self._render_notes:
            msg += " Obs.: " + "; ".join(self._render_notes) + "."
        self.statusBar().showMessage(msg)
        # depois da mensagem acima: o resumo de uma importação iTOL recém-feita fica visível
        self.figure_panel.itol.set_effects(itol if self.figure_panel.itol.entries else None)

    def _make_snapshot(self, style, result, meta_colors, label_groups, itol, context):  # type: ignore[no-untyped-def]
        """O que acabou de ser desenhado, para a exportação iTOL."""
        from jabuti.exporters.itol_export import FigureSnapshot

        edits = self.style_panel.edits
        tree = self.display_tree
        original: dict = {}
        if tree.broken:
            full = apply_edits(self.tree, replace(edits, shortened=[]))
            by_leaves = {frozenset(l.name for l in n.leaves()): n.length for n in full.root.traverse_preorder()}
            for n in tree.broken:
                length = by_leaves.get(frozenset(l.name for l in n.leaves()))
                if length is not None:
                    original[n] = length
        extras = []
        if context:
            extras.append("contexto gênico (setas dos vizinhos) não tem equivalente no iTOL")
        if edits.highlights:
            extras.append(f"{len(edits.highlights)} faixa(s) de destaque de linha não têm equivalente no iTOL")
        if style.figure.support_levels.enabled:
            extras.append("cores por nível de suporte não vão (o valor do suporte está no Newick)")
        name = self.tree_tab.path.stem if self.tree_tab.path else "arvore"
        return FigureSnapshot(
            tree=tree, style=style, clades=list(result.clades),
            collapsed=list(collapsed_nodes(tree, edits)), blocks=list(getattr(self, "_export_blocks", [])),
            meta_colors=dict(meta_colors), groups=label_groups.effective(tree.leaf_names()),
            names=self.display_names(style), branch_looks=itol.branch_looks, ranges=list(itol.ranges),
            marks=list(itol.marks), original_lengths=original,
            hidden_count=len(edits.hidden & set(self.tree.leaf_names())), extras=extras, tree_name=name)

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
        warnings = list(loaded.warnings) + sp.load_style(loaded.style) + self.figure_panel.load_style(loaded.style)
        sp.load_detection(loaded.detection)
        sp.load_tree_state(loaded.clade_set, loaded.edits)
        if loaded.edits is not None and self.tree is not None:
            names = set(self.tree.leaf_names())
            unknown = sp.edits.hidden - names
            if unknown:
                sp.edits.hidden -= unknown
                warnings.append(f"{len(unknown)} folha(s) oculta(s) no preset não existem na árvore aberta.")
            sp.edits.marked &= names
            kept = []
            for hl in sp.edits.highlights:
                if hl.leaves & names:
                    hl.leaves = frozenset(hl.leaves & names)
                    kept.append(hl)
            sp.edits.highlights = kept
        self.figure_panel.refresh_pruning()
        self.figure_panel.refresh_names()
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
                path = save_file(self, "Salvar preset", "preset", "jabuti_preset.json", "Preset (*.json)")
                if path:
                    save_preset(path if path.lower().endswith(".json") else path + ".json", self.collect_preset())
                    self.statusBar().showMessage(f"Preset salvo: {path}", 8000)
            elif action == "load":
                path = open_file(self, "Carregar preset", "preset", "Preset (*.json);;Todos (*)")
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
            pruned = [n for n in self.style_panel.edits.hidden if q.strip().lower() in n.lower()]
            if pruned:
                self.statusBar().showMessage(f"“{q}” está oculta (painel Figura → Enraizamento e poda → Restaurar).")
            elif hidden:
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
        filters = {"svg": "SVG (*.svg)", "pdf": "PDF (*.pdf)", "png": "PNG (*.png)", "tiff": "TIFF (*.tif *.tiff)"}
        path = save_file(self, f"Exportar {fmt.upper()}", "export", f"{base}.{fmt}", filters[fmt])
        if not path:
            return
        if not path.lower().endswith(f".{fmt}") and not (fmt == "tiff" and path.lower().endswith(".tif")):
            path += f".{fmt}"
        scene = self.canvas.tree_scene
        from PySide6.QtWidgets import QApplication

        self.statusBar().showMessage(f"Exportando {fmt.upper()}… (figuras grandes em PNG/TIFF podem levar alguns segundos)")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            if fmt == "svg":
                export_svg(scene, path)
            elif fmt == "pdf":
                export_pdf(scene, path)
            elif fmt == "tiff":
                export_tiff(scene, path, self.viz_tab.tiff_dpi.value(), self.viz_tab.tiff_lzw.isChecked())
            else:
                export_png(scene, path, self.viz_tab.dpi.value())
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            show_error(self, exc, "Erro ao exportar")
            self.statusBar().clearMessage()
            return
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(f"Exportado: {path}")

    def export_itol(self, dest: str | None = None, as_zip: bool | None = None) -> Path | None:
        """Resumo do que será gerado + avisos; depois grava a pasta ou o .zip.

        ``dest``/``as_zip`` pulam os diálogos (testes)."""
        from PySide6.QtWidgets import QMessageBox

        from jabuti.exporters.itol_export import plan_export, write_export

        if self.tree is None:
            show_error(self, Exception("Abra uma árvore primeiro."), "Exportar para o iTOL")
            return None
        self.generate()                                      # exporta exatamente o que está na tela
        snap = getattr(self, "_snapshot", None)
        if snap is None:
            return None
        try:
            plan = plan_export(snap)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Exportar para o iTOL")
            return None
        if dest is None:
            box = QMessageBox(QMessageBox.Icon.Information, "Exportar para o iTOL",
                              f"Serão gerados {len(plan.files)} arquivo(s) + LEIAME.txt:", parent=self)
            info = plan.summary()
            if plan.warnings:
                info += "\n\nSem equivalente ou aproximado no iTOL:\n" + "\n".join(f"⚠ {w}" for w in plan.warnings)
            box.setInformativeText(info)
            folder = box.addButton("Salvar pasta…", QMessageBox.ButtonRole.AcceptRole)
            zipped = box.addButton("Salvar .zip…", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked not in (folder, zipped):
                return None
            as_zip = clicked is zipped
            base = f"{snap.tree_name}_itol"
            if as_zip:
                dest = save_file(self, "Salvar .zip para o iTOL", "export", f"{base}.zip", "Zip (*.zip)")
            else:
                parent = pick_dir(self, "Pasta onde criar a exportação", "export")
                dest = str(Path(parent) / base) if parent else ""
            if not dest:
                return None
            target = Path(dest)
            if not as_zip and target.exists() and any(target.iterdir()):
                answer = QMessageBox.question(self, "Exportar para o iTOL",
                                              f"A pasta “{target.name}” já existe e tem arquivos. Sobrescrever?")
                if answer != QMessageBox.StandardButton.Yes:
                    return None
        try:
            out = write_export(plan, dest, bool(as_zip))
        except OSError as exc:
            show_error(self, Exception(f"Não foi possível gravar em {dest}:\n{exc.strerror or exc}"),
                       "Exportar para o iTOL")
            return None
        self.statusBar().showMessage(f"Exportado para o iTOL: {out} ({len(plan.files)} arquivo(s)).", 12000)
        return out

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self.gff_tab.shutdown()  # não deixa thread de leitura viva ao fechar
        self.figure_panel.shutdown()
        super().closeEvent(event)

    # ---------------------------------------------------- drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        from jabuti.parsers.itol import sniff_itol

        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        itol = [u for u in urls if sniff_itol(u)]
        others = [u for u in urls if u not in itol]
        if others:
            self.tabs.setCurrentIndex(0)
            self.tree_tab.load(Path(others[0]))
        if itol:
            self.import_itol(itol, wait=False)

    def import_itol(self, paths, wait: bool = True) -> bool:  # type: ignore[no-untyped-def]
        """Anotações iTOL (botão do painel Figura ou arrastar e soltar)."""
        self.figure_holder.set_collapsed(False)
        self.figure_panel.sections["itol"].set_expanded(True)
        return self.figure_panel.itol.import_files(paths, wait=wait)
