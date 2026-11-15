"""Exportação em lote: diálogo (modal), execução com progresso/Cancelar e resumo.

Cada combinação layout × estilo é desenhada uma vez numa cena própria
(``MainWindow.render_to_scene``) e exportada em cada formato. A tela, os painéis e o estilo
do projeto não mudam: não há nada a restaurar ao terminar ou cancelar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGraphicsScene,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from jabuti.exporters.batch import (
    CURRENT_PRESET,
    DEFAULT_TEMPLATE,
    FORMATS,
    LAYOUT_NAMES,
    BatchReport,
    TemplateError,
    plan_batch,
    visual_style,
)
from jabuti.logs import get_logger
from jabuti.presets import load_preset
from jabuti.settings import last_dir, open_file, pick_dir
from jabuti.style import LayoutKind, RenderStyle
from jabuti.views.errors import error_text, show_error
from jabuti.views.export import ExportError, export_pdf, export_png, export_svg, export_tiff
from jabuti.views.theme import error_color, muted_css

_log = get_logger("batch")


@dataclass
class BatchRequest:
    layouts: list[LayoutKind]
    presets: list[tuple[str, RenderStyle | None]]       # (nome, estilo do preset; None = estilo atual)
    formats: list[str]
    dest: Path
    template: str = DEFAULT_TEMPLATE
    png_dpi: int = 300
    tiff_dpi: int = 600
    tiff_lzw: bool = True
    project: str = "figura"
    extra: dict = field(default_factory=dict)


class BatchDialog(QDialog):
    """Escolhas do lote. Modal (como os demais diálogos do sistema)."""

    def __init__(self, win, parent: QWidget | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent or win)
        self.win = win
        self.setWindowTitle("Exportar em lote")
        self.setModal(True)
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)

        box = QGroupBox("Layouts")
        g = QGridLayout(box)
        current = win.current_style().layout
        self.layout_boxes: dict[LayoutKind, QCheckBox] = {}
        for k, kind in enumerate(LAYOUT_NAMES):
            cb = QCheckBox(LAYOUT_NAMES[kind])
            cb.setChecked(kind == current)
            cb.toggled.connect(self._update)
            g.addWidget(cb, k // 3, k % 3)
            self.layout_boxes[kind] = cb
        v.addWidget(box)

        box = QGroupBox("Estilos")
        bl = QVBoxLayout(box)
        self.preset_list = QListWidget()
        self.preset_list.setMaximumHeight(110)
        self.preset_list.setToolTip("Marque os estilos a exportar. Um preset muda só o visual (cores, fontes, "
                                    "ramos, rótulos, legenda); colunas, anotações e nomes continuam os do projeto.")
        item = QListWidgetItem("Estilo atual (do projeto)")
        item.setData(Qt.ItemDataRole.UserRole, (CURRENT_PRESET, None))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        self.preset_list.addItem(item)
        self.preset_list.itemChanged.connect(self._update)
        bl.addWidget(self.preset_list)
        row = QHBoxLayout()
        add = QPushButton("+ Adicionar preset…")
        add.setToolTip("Arquivo .json salvo em Estilo → Presets")
        add.clicked.connect(self._add_preset)
        rm = QPushButton("Remover")
        rm.clicked.connect(self._remove_preset)
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch(1)
        bl.addLayout(row)
        v.addWidget(box)

        box = QGroupBox("Formatos")
        f = QFormLayout(box)
        frow = QHBoxLayout()
        self.format_boxes: dict[str, QCheckBox] = {}
        for fmt in FORMATS:
            cb = QCheckBox(fmt.upper())
            cb.setChecked(fmt == "svg")
            cb.toggled.connect(self._update)
            frow.addWidget(cb)
            self.format_boxes[fmt] = cb
        frow.addStretch(1)
        f.addRow(frow)
        self.png_dpi = QSpinBox()
        self.png_dpi.setRange(72, 1200)
        self.png_dpi.setSuffix(" dpi")
        self.png_dpi.setValue(win.viz_tab.dpi.value())
        self.tiff_dpi = QSpinBox()
        self.tiff_dpi.setRange(72, 2400)
        self.tiff_dpi.setSuffix(" dpi")
        self.tiff_dpi.setValue(win.viz_tab.tiff_dpi.value())
        self.tiff_lzw = QCheckBox("Compressão LZW")
        self.tiff_lzw.setChecked(win.viz_tab.tiff_lzw.isChecked())
        f.addRow("PNG:", self.png_dpi)
        trow = QHBoxLayout()
        trow.addWidget(self.tiff_dpi)
        trow.addWidget(self.tiff_lzw)
        trow.addStretch(1)
        f.addRow("TIFF:", trow)
        v.addWidget(box)

        box = QGroupBox("Destino")
        f = QFormLayout(box)
        drow = QHBoxLayout()
        self.dest = QLineEdit(last_dir("batch") or last_dir("export") or str(Path.home()))
        self.dest.textChanged.connect(self._update)
        choose = QPushButton("Escolher…")
        choose.clicked.connect(self._choose_dest)
        drow.addWidget(self.dest, 1)
        drow.addWidget(choose)
        f.addRow("Pasta:", drow)
        self.template = QLineEdit(DEFAULT_TEMPLATE)
        self.template.setToolTip("Campos: {projeto}, {layout}, {preset}, {ext}. Nomes repetidos ganham _2, _3…")
        self.template.textChanged.connect(self._update)
        f.addRow("Nome dos arquivos:", self.template)
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(muted_css())
        f.addRow(self.preview)
        v.addWidget(box)

        self.buttons = QDialogButtonBox()
        self.ok = self.buttons.addButton("Exportar", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        v.addWidget(self.buttons)
        self._update()

    def _add_preset(self) -> None:
        path = open_file(self, "Adicionar preset", "preset", "Preset (*.json);;Todos (*)")
        if not path:
            return
        try:
            loaded = load_preset(path)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "Preset")
            return
        self.add_preset(Path(path).stem, loaded.style)

    def add_preset(self, name: str, style: RenderStyle) -> None:
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, (name, style))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        self.preset_list.addItem(item)

    def _remove_preset(self) -> None:
        row = self.preset_list.currentRow()
        if row > 0:                                   # o estilo atual não sai da lista
            self.preset_list.takeItem(row)
            self._update()

    def _choose_dest(self) -> None:
        path = pick_dir(self, "Pasta para a exportação em lote", "batch")
        if path:
            self.dest.setText(path)

    def request(self) -> BatchRequest:
        presets = []
        for i in range(self.preset_list.count()):
            it = self.preset_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                presets.append(it.data(Qt.ItemDataRole.UserRole))
        return BatchRequest(
            layouts=[k for k, cb in self.layout_boxes.items() if cb.isChecked()],
            presets=presets,
            formats=[f for f, cb in self.format_boxes.items() if cb.isChecked()],
            dest=Path(self.dest.text().strip()).expanduser(),
            template=self.template.text().strip(),
            png_dpi=self.png_dpi.value(), tiff_dpi=self.tiff_dpi.value(), tiff_lzw=self.tiff_lzw.isChecked(),
            project=project_name(self.win),
        )

    def _update(self, *_a) -> None:  # type: ignore[no-untyped-def]
        r = self.request()
        try:
            if not self.dest.text().strip():
                raise TemplateError("Escolha a pasta de destino.")
            plan = plan_batch(r.project, r.layouts, [n for n, _s in r.presets], r.formats, r.template, r.dest)
        except TemplateError as exc:
            self.preview.setText(f"⚠ {exc}")
            self.preview.setStyleSheet(f"color: {error_color()};")
            self.ok.setEnabled(False)
            return
        self.preview.setStyleSheet(muted_css())
        first = plan.items[0].path.name
        more = f" … ({len(plan.items)} arquivos)" if len(plan.items) > 1 else ""
        self.preview.setText(f"Ex.: {first}{more}")
        self.ok.setEnabled(True)


def project_name(win) -> str:  # type: ignore[no-untyped-def]
    if win.project.path is not None:
        return win.project.path.stem
    if win.tree_tab.path is not None:
        return win.tree_tab.path.stem
    return "figura"


class BatchRunner:
    """Executa o lote. ``is_canceled`` e ``confirm_overwrite`` podem ser trocados nos testes."""

    def __init__(self, win, request: BatchRequest, show_progress: bool = True) -> None:  # type: ignore[no-untyped-def]
        self.win = win
        self.request = request
        self.show_progress = show_progress
        self.progress: QProgressDialog | None = None

    def is_canceled(self) -> bool:
        return self.progress is not None and self.progress.wasCanceled()

    def confirm_overwrite(self, existing: list[Path]) -> str | None:
        """"overwrite", "skip" (pular os existentes) ou None (cancelar)."""
        box = QMessageBox(QMessageBox.Icon.Question, "Exportar em lote",
                          f"{len(existing)} arquivo(s) já existem na pasta de destino.", parent=self.win)
        box.setInformativeText("\n".join(p.name for p in existing[:15]) + ("\n…" if len(existing) > 15 else ""))
        over = box.addButton("Sobrescrever", QMessageBox.ButtonRole.DestructiveRole)
        skip = box.addButton("Pular existentes", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return "overwrite" if box.clickedButton() is over else "skip" if box.clickedButton() is skip else None

    def export_one(self, scene: QGraphicsScene, fmt: str, path: Path) -> None:
        r = self.request
        if fmt == "svg":
            export_svg(scene, path)
        elif fmt == "pdf":
            export_pdf(scene, path)
        elif fmt == "png":
            export_png(scene, path, r.png_dpi)
        else:
            export_tiff(scene, path, r.tiff_dpi, r.tiff_lzw)

    def run(self) -> BatchReport | None:
        r = self.request
        win = self.win
        try:
            plan = plan_batch(r.project, r.layouts, [n for n, _s in r.presets], r.formats, r.template, r.dest)
            r.dest.mkdir(parents=True, exist_ok=True)
        except (TemplateError, OSError) as exc:
            show_error(win, exc, "Exportar em lote")
            return None
        report = BatchReport()
        skip_existing: set[Path] = set()
        existing = [it.path for it in plan.items if it.path.exists()]
        if existing:
            choice = self.confirm_overwrite(existing)
            if choice is None:
                return None
            if choice == "skip":
                skip_existing = set(existing)
        styles = dict(r.presets)
        current = win.current_style()
        total = len(plan.items)
        if self.show_progress:
            self.progress = QProgressDialog("Exportando…", "Cancelar", 0, total, win)
            self.progress.setWindowTitle("Exportar em lote")
            self.progress.setWindowModality(Qt.WindowModality.WindowModal)
            self.progress.setMinimumDuration(0)
            self.progress.setValue(0)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        scenes: dict[tuple, tuple[QGraphicsScene | None, str]] = {}
        try:
            for k, item in enumerate(plan.items):
                QApplication.processEvents()
                if self.is_canceled():
                    report.cancelled = True
                    report.not_run = total - k
                    break
                if self.progress is not None:
                    self.progress.setLabelText(f"Exportando… {k + 1} de {total}\n{item.path.name}")
                    self.progress.setValue(k)
                QApplication.processEvents()
                if item.path in skip_existing:
                    report.skipped.append((item.path.name, "já existia (pulado)"))
                    continue
                key = (item.layout, item.preset)
                if key not in scenes:
                    # uma cena por layout × estilo, reaproveitada por todos os formatos
                    for old in [kk for kk in scenes if kk != key]:
                        scenes.pop(old)
                    try:
                        scene = QGraphicsScene()
                        win.render_to_scene(visual_style(current, styles.get(item.preset), item.layout), scene)
                        scenes[key] = (scene, "")
                    except Exception as exc:  # noqa: BLE001
                        _log.error("lote: erro ao desenhar %s", key, exc_info=True)
                        scenes[key] = (None, f"erro ao desenhar: {error_text(exc)}")
                scene, err = scenes[key]
                if scene is None:
                    report.failed.append((item.path.name, err))
                    continue
                try:
                    self.export_one(scene, item.fmt, item.path)
                    report.generated.append(item.path)
                except ExportError as exc:
                    report.skipped.append((item.path.name, str(exc)))
                except Exception as exc:  # noqa: BLE001 — um item não para o lote
                    _log.error("lote: erro exportando %s", item.path, exc_info=True)
                    report.failed.append((item.path.name, error_text(exc)))
        finally:
            scenes.clear()
            QApplication.restoreOverrideCursor()
            if self.progress is not None:
                self.progress.setValue(total)
                self.progress.close()
                self.progress.deleteLater()
                self.progress = None
        return report


def show_report(win, report: BatchReport, dest: Path) -> None:  # type: ignore[no-untyped-def]
    ok = not report.failed and not report.skipped and not report.cancelled
    head = (f"Exportação em lote {'cancelada' if report.cancelled else 'concluída'}: "
            f"{len(report.generated)} gerado(s), {len(report.skipped)} pulado(s), {len(report.failed)} com erro.")
    box = QMessageBox(QMessageBox.Icon.Information if ok else QMessageBox.Icon.Warning, "Exportar em lote", head,
                      parent=win)
    box.setInformativeText(f"Pasta: {dest}")
    box.setDetailedText(report.summary())
    box.exec()
