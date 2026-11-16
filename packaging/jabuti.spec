# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller: Jabuti.app (macOS) e pasta Jabuti/ com Jabuti.exe (Windows, onedir).

Gerar (na raiz do repositório, num ambiente com requirements.txt + pyinstaller):

    python scripts/make_icons.py          # só se o ícone mudar (os gerados ficam em packaging/)
    pyinstaller --noconfirm --clean packaging/jabuti.spec

Saída: dist/Jabuti.app (macOS) ou dist/Jabuti/Jabuti.exe (Windows).
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent          # noqa: F821 — SPECPATH vem do PyInstaller
sys.path.insert(0, str(ROOT))
from jabuti import __version__                  # noqa: E402
from jabuti.file_types import OPEN_WITH_SUFFIXES, PROJECT_SUFFIX  # noqa: E402

APP_NAME = "Jabuti"
BUNDLE_ID = "br.ufv.lgem.jabuti"
MAC = sys.platform == "darwin"
WIN = sys.platform.startswith("win")
ICON = str(ROOT / "packaging" / ("jabuti.icns" if MAC else "jabuti.ico"))

datas = [
    (str(ROOT / "jabuti" / "assets"), "jabuti/assets"),   # lidos via asset_path (sys._MEIPASS)
    (str(ROOT / "README.md"), "."),                       # "Abrir README" offline
    (str(ROOT / "examples"), "examples"),                 # árvore e anotações de exemplo
]

# só QtCore, QtGui, QtWidgets e QtSvg são usados; o resto do Qt e da biblioteca padrão
# que nunca é importado sai do pacote (menor e mais rápido para abrir)
excludes = [
    "tkinter", "_tkinter", "unittest", "pydoc", "doctest", "pdb", "lib2to3", "test",
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.Qt3DCore", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtXml", "PySide6.QtDBus", "PySide6.QtBluetooth", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
    "PySide6.QtConcurrent", "PySide6.QtStateMachine", "PySide6.QtSvgWidgets",
    "matplotlib", "PIL", "IPython", "pandas", "scipy", "reportlab", "mysql", "psycopg2",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "jabuti_main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["Bio.Phylo.NewickIO"],          # importado tarde (só ao abrir uma árvore)
    excludes=excludes,
    noarchive=False,
)
# fora: QtNetwork (só o plugin de toque TUIO o usa) e formatos de imagem que o Jabuti não lê
# nem grava (PNG é embutido no QtGui; TIFF, JPEG e SVG ficam)
_DROP = ("qtuiotouchplugin", "qtnetwork", "qt6network", "qgif", "qicns", "qico", "qmacheif", "qmacjp2",
         "qtga", "qwbmp", "qwebp")
def _keep(entry) -> bool:  # type: ignore[no-untyped-def]
    name = entry[0].lower()
    return not (("pyside6" in name or "/" not in name.replace("\\", "/")) and any(d in name for d in _DROP))


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]               # esqueleto do QtNetwork.framework (links)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,                         # onedir: bibliotecas ficam ao lado do .exe
    name=APP_NAME,
    console=False,                                 # sem janela de terminal
    disable_windowed_traceback=False,
    icon=ICON,
    upx=False,
    argv_emulation=False,                          # arquivos chegam por QFileOpenEvent
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

if MAC:
    tree_exts = [s.lstrip(".") for s in OPEN_WITH_SUFFIXES if s != PROJECT_SUFFIX]
    app = BUNDLE(  # noqa: F821
        coll,
        name=f"{APP_NAME}.app",
        icon=ICON,
        bundle_identifier=BUNDLE_ID,
        version=__version__,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "14.0",              # o Qt 6.12 (PySide6) exige macOS 14+
            "NSRequiresAquaSystemAppearance": False,      # acompanha o modo escuro
            "LSApplicationCategoryType": "public.app-category.education",
            "NSHumanReadableCopyright": "Laboratório de Genômica Eco-evolutiva Microbiana",
            # tipos de arquivo: projeto do Jabuti (nosso) e árvores Newick (abre também)
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": f"{BUNDLE_ID}.project",
                "UTTypeDescription": "Projeto do Jabuti",
                "UTTypeConformsTo": ["public.data", "public.content"],
                "UTTypeIconFile": "jabuti.icns",
                "UTTypeTagSpecification": {"public.filename-extension": ["jabuti"]},
            }],
            "UTImportedTypeDeclarations": [{
                "UTTypeIdentifier": f"{BUNDLE_ID}.newick",
                "UTTypeDescription": "Árvore Newick",
                "UTTypeConformsTo": ["public.plain-text", "public.data"],
                "UTTypeTagSpecification": {"public.filename-extension": tree_exts},
            }],
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Projeto do Jabuti",
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Owner",
                    "LSItemContentTypes": [f"{BUNDLE_ID}.project"],
                    "CFBundleTypeExtensions": ["jabuti"],
                    "CFBundleTypeIconFile": "jabuti.icns",
                },
                {
                    "CFBundleTypeName": "Árvore Newick",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Default",
                    "LSItemContentTypes": [f"{BUNDLE_ID}.newick"],
                    "CFBundleTypeExtensions": tree_exts,
                },
            ],
        },
    )
