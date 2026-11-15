"""Diálogo "Sobre o Jabuti": logo, nome e versão, créditos (com a logo do LGEM pequena),
manual e as pastas de configuração e log."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from jabuti import __version__
from jabuti.credits import CREDIT_AUTHOR, CREDIT_LAB, TAGLINE
from jabuti.resources import JABUTI_GREEN, JABUTI_LOGO, LGEM_LOGO, load_pixmap
from jabuti.views.theme import is_dark, muted_css


class AboutDialog(QDialog):
    def __init__(self, readme_url: str, config_dir: str, log_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sobre o Jabuti")
        self.setModal(True)
        dpr = self.devicePixelRatioF()
        v = QVBoxLayout(self)
        v.setSpacing(10)
        head = QHBoxLayout()
        self.logo = QLabel()
        self.logo.setObjectName("about_logo")
        pm = load_pixmap(JABUTI_LOGO, 150, dpr, trim=True)
        if not pm.isNull():
            self.logo.setPixmap(pm)
        head.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignVCenter)
        titles = QVBoxLayout()
        self.title = QLabel("Jabuti")
        f = QFont(self.title.font())
        f.setPointSizeF(f.pointSizeF() * 2.0)
        f.setWeight(QFont.Weight.DemiBold)
        self.title.setFont(f)
        self.title.setStyleSheet(f"color: {'#6fbf8f' if is_dark() else JABUTI_GREEN};")
        titles.addWidget(self.title)
        self.version = QLabel(f"Versão {__version__}")
        titles.addWidget(self.version)
        tag = QLabel(TAGLINE)
        titles.addWidget(tag)
        titles.addStretch(1)
        head.addLayout(titles, 1)
        v.addLayout(head)

        credits = QGridLayout()
        credits.setHorizontalSpacing(8)
        self.lgem = QLabel()
        self.lgem.setObjectName("about_lgem")
        lpm = load_pixmap(LGEM_LOGO, 60, dpr)
        if not lpm.isNull():
            self.lgem.setPixmap(lpm)
        self.lgem.setToolTip("Laboratório de Genômica Eco-evolutiva Microbiana (LGEM)")
        self.credit_lab = QLabel(CREDIT_LAB)
        self.credit_author = QLabel(CREDIT_AUTHOR)
        credits.addWidget(self.lgem, 0, 0, 2, 1, Qt.AlignmentFlag.AlignVCenter)
        credits.addWidget(self.credit_lab, 0, 1)
        credits.addWidget(self.credit_author, 1, 1)
        credits.setColumnStretch(1, 1)
        v.addLayout(credits)

        self.links = QLabel(f'<a href="{readme_url}">Manual (README)</a>')
        self.links.setOpenExternalLinks(True)
        self.links.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        v.addWidget(self.links)
        self.paths = QLabel(f"Configuração: {config_dir}\nLog de erros: {log_path}")
        self.paths.setStyleSheet(muted_css())
        self.paths.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.paths.setWordWrap(True)
        v.addWidget(self.paths)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        box.accepted.connect(self.accept)
        v.addWidget(box)
        # altura calculada para a largura final (os caminhos quebram em várias linhas)
        width = 600
        v.activate()
        height = v.totalHeightForWidth(width) if v.hasHeightForWidth() else v.totalSizeHint().height()
        self.setMinimumSize(width, height)
        self.resize(width, height)

    def text(self) -> str:
        """Todo o texto visível (para testes)."""
        return "\n".join(w.text() for w in (self.title, self.version, self.credit_lab, self.credit_author,
                                             self.links, self.paths))
