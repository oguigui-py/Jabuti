"""Empacotamento: ícones gerados, spec do PyInstaller coerente e autoteste do executável."""

from __future__ import annotations

import ast
import os
import re
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"


def test_ico_has_all_sizes_as_png():
    data = (PKG / "jabuti.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1) and count == 7
    sizes = []
    for i in range(count):
        w, h, _c, _r, _planes, bpp, size, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i: 22 + 16 * i])
        sizes.append(w or 256)
        assert w == h and bpp == 32 and data[offset:offset + 8] == b"\x89PNG\r\n\x1a\n"
        assert offset + size <= len(data)
    assert sizes == [16, 24, 32, 48, 64, 128, 256]


def test_icns_exists_with_retina_sizes():
    data = (PKG / "jabuti.icns").read_bytes()
    assert data[:4] == b"icns" and struct.unpack(">I", data[4:8])[0] == len(data)
    types = set()
    pos = 8
    while pos < len(data):
        types.add(data[pos:pos + 4])
        pos += struct.unpack(">I", data[pos + 4:pos + 8])[0]
    assert {b"ic10", b"ic09", b"ic08", b"ic07"} <= types           # 1024, 512, 256, 128


def test_make_icons_script_regenerates(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import make_icons
    finally:
        sys.path.pop(0)
    from PySide6.QtGui import QImage

    from jabuti.resources import JABUTI_ICON, asset_path

    src = QImage(str(asset_path(JABUTI_ICON)))
    out = make_icons.write_ico(src, tmp_path / "x.ico")
    assert out.read_bytes()[:6] == (PKG / "jabuti.ico").read_bytes()[:6]
    mac = make_icons.scaled(src, 1024, make_icons.MAC_GRID)
    assert mac.pixelColor(10, 10).alpha() == 0 and mac.pixelColor(512, 512).alpha() == 255   # margem do macOS


def test_spec_is_valid_python_and_has_the_required_settings():
    text = (PKG / "jabuti.spec").read_text(encoding="utf-8")
    ast.parse(text)
    for needle in ('APP_NAME = "Jabuti"', 'BUNDLE_ID = "br.ufv.lgem.jabuti"', "console=False",
                   "exclude_binaries=True", "from jabuti import __version__", '"CFBundleName": APP_NAME',
                   "CFBundleDocumentTypes", '"jabuti/assets"', "jabuti.icns", "jabuti.ico", "BUNDLE(", "COLLECT("):
        assert needle in text, needle
    assert (PKG / "jabuti_main.py").is_file()
    dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert re.search(r"^pyinstaller==\d+\.\d+", dev, re.M)


def test_open_with_extensions_match_tree_loader():
    from jabuti.file_types import OPEN_WITH_SUFFIXES, TREE_SUFFIXES
    from jabuti.views.tree_tab import TREE_FILTER

    for suf in OPEN_WITH_SUFFIXES:
        assert suf == ".jabuti" or (suf in TREE_SUFFIXES and f"*{suf}" in TREE_FILTER)


def test_selftest_passes_from_source(tmp_path, qtbot):
    from jabuti.selftest import run_selftest

    assert run_selftest(tmp_path) == 0
    report = (tmp_path / "autoteste.txt").read_text(encoding="utf-8")
    assert "TUDO CERTO" in report and "FALHOU" not in report
    work = tmp_path / "autoteste ção"
    assert {p.suffix for p in work.iterdir()} >= {".svg", ".pdf", ".png", ".tif", ".jabuti"}


def test_selftest_reports_failures(tmp_path, qtbot, monkeypatch):
    from jabuti import selftest

    monkeypatch.setattr(selftest, "examples_dir", lambda: tmp_path / "sumiu")
    assert selftest.run_selftest(tmp_path) == 1
    assert "[FALHOU] exemplos empacotados" in (tmp_path / "autoteste.txt").read_text(encoding="utf-8")


def test_cli_autoteste_flag(monkeypatch):
    from jabuti import cli, selftest

    seen = []
    monkeypatch.setattr(selftest, "run_selftest", lambda out: seen.append(out) or 0)
    assert cli.main(["--autoteste", "pasta"]) == 0 and seen == ["pasta"]


@pytest.mark.parametrize("frozen", [False, True])
def test_frozen_app_leaves_dock_to_info_plist(monkeypatch, frozen):
    """No .app, o Info.plist/.icns definem nome e ícone; o AppKit só é usado com python -m jabuti."""
    import jabuti.app as app_mod
    from jabuti import macos

    calls = []
    monkeypatch.setattr(app_mod.sys, "platform", "darwin")
    monkeypatch.setattr(app_mod.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(macos, "set_app_name", lambda name="": calls.append("nome") or True)
    monkeypatch.setattr(macos, "set_dock_icon", lambda p: calls.append("dock") or True)

    class Stop(Exception):
        pass

    monkeypatch.setattr(app_mod, "Launcher", lambda *a, **k: (_ for _ in ()).throw(Stop()))
    monkeypatch.setattr("jabuti.views.errors.install_excepthook", lambda: None)
    with pytest.raises(Stop):
        app_mod.run(splash=False)
    assert calls == ([] if frozen else ["nome", "dock"])


def test_install_guide_and_build_script():
    guide = (PKG / "LEIAME_INSTALACAO.txt").read_text(encoding="utf-8")
    for needle in ("botão direito", "Abrir Mesmo Assim", "xattr -dr com.apple.quarantine", "SmartScreen",
                   "Executar assim mesmo", "--autoteste"):
        assert needle in guide, needle
    script = ROOT / "scripts" / "build_macos.sh"
    text = script.read_text(encoding="utf-8")
    assert os.access(script, os.X_OK)
    assert "ditto -c -k --keepParent dist/Jabuti.app dist/Jabuti-macOS.zip" in text and "hdiutil create" in text
    assert "--autoteste" in text


def test_open_paths_logs_what_was_opened(qtbot, monkeypatch, tmp_path):
    import logging
    import shutil

    from jabuti.views import errors
    from jabuti.views.main_window import MainWindow

    monkeypatch.setattr(errors.QMessageBox, "exec", lambda self: 0)
    shutil.copy("examples/paraburkholderia_40.treefile", tmp_path / "t.treefile")
    w = MainWindow()
    qtbot.addWidget(w)
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("jabuti.abrir")
    logger.addHandler(handler)
    old = logger.level
    logger.setLevel(logging.INFO)
    try:
        assert w.open_paths([tmp_path / "t.treefile"], ask=False)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old)
    assert any("tree=t.treefile" in r.getMessage() for r in records)


def test_github_workflow():
    text = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    for needle in ("workflow_dispatch", 'tags: ["v*"]', "macos-latest", "windows-latest", 'PYTHON_VERSION: "3.12"',
                   "requirements-dev.txt", "QT_QPA_PLATFORM: offscreen", "python -m pytest -q",
                   "scripts/build_macos.sh", "Jabuti-macOS.zip", "Jabuti-Windows.zip", "Jabuti.exe",
                   "--autoteste", "actions/upload-artifact", "softprops/action-gh-release",
                   "startsWith(github.ref, 'refs/tags/v')", "contents: write", "ExtractAssociatedIcon"):
        assert needle in text, needle
    assert "\t" not in text                                       # YAML não aceita tabulação
    win = text[text.index("  windows:"):text.index("  release:")]
    mac = text[text.index("  macos:"):text.index("  windows:")]
    assert "QT_QPA_PLATFORM: windows" in win                      # fontes do sistema (não offscreen)
    for job in (mac, win):                                        # artefato antes dos testes
        assert job.index("actions/upload-artifact") < job.index("python -m pytest -q")
        assert "if: ${{ !cancelled() }}" in job[job.index("name: Testes"):]


def test_windows_app_id_never_raises(monkeypatch):
    from jabuti.app import set_windows_app_id

    if not sys.platform.startswith("win"):
        assert set_windows_app_id() is False
    monkeypatch.setattr("ctypes.windll", None, raising=False)
    assert set_windows_app_id() is False
