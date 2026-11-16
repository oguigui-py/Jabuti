"""Codificação: arquivos do usuário fora do UTF-8 e saída do terminal no Windows (cp1252)."""

from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from jabuti.parsers.errors import decode_text

ROOT = Path(__file__).resolve().parents[1]
CP1252_ONLY = "Solo úmido — “raiz” ‘nódulo’ …"           # travessão e aspas curvas: só existem no cp1252


@pytest.fixture
def warnings_log():  # type: ignore[no-untyped-def]
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("jabuti.leitura")
    old = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield records
    logger.removeHandler(handler)
    logger.setLevel(old)


def test_decode_utf8_bom_cp1252_latin1(warnings_log):
    assert decode_text("ação".encode("utf-8")) == "ação" and not warnings_log
    assert decode_text(b"\xef\xbb\xbf" + "ação".encode("utf-8")) == "ação"          # BOM some
    assert decode_text(CP1252_ONLY.encode("cp1252"), "planilha.tsv") == CP1252_ONLY
    assert "planilha.tsv" in warnings_log[-1].getMessage() and "cp1252" in warnings_log[-1].getMessage()
    assert decode_text(b"\x81\x8d") == "\x81\x8d"                                     # nem cp1252: latin-1, sem quebrar


def test_user_files_in_cp1252(tmp_path, warnings_log):
    from jabuti.parsers.gff import parse_gff3
    from jabuti.parsers.metadata import load_metadata
    from jabuti.parsers.newick import load_tree

    nwk = tmp_path / "árvore.nwk"
    nwk.write_bytes("(Espécie_ç:1,(B:1,C:1):1);".encode("cp1252"))
    assert "Espécie_ç" in load_tree(nwk).leaf_names()
    meta = tmp_path / "meta.tsv"
    meta.write_bytes(f"genoma\thabitat\nA\t{CP1252_ONLY}\nB\tágua\n".encode("cp1252"))
    table = load_metadata(meta)
    assert table.rows[0]["habitat"] == CP1252_ONLY
    gff = tmp_path / "g.gff3"
    gff.write_bytes("##gff-version 3\nc1\tP\tCDS\t1\t90\t.\t+\t0\tID=g1;product=proteína “X”\n".encode("cp1252"))
    genome = parse_gff3(gff)
    assert any(f.attributes.get("product") == "proteína “X”" for f in genome.features)
    assert len([r for r in warnings_log if "cp1252" in r.getMessage()]) == 3


def test_utf8_stdio_reconfigures_and_survives_no_console(monkeypatch):
    from jabuti.cli import utf8_stdio

    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    monkeypatch.setattr(sys, "stderr", None)                       # executável de janela no Windows
    utf8_stdio()
    assert sys.stdout.encoding.lower().replace("_", "-") == "utf-8" and sys.stderr is not None
    print("Laboratório — ✓")
    sys.stdout.flush()
    assert raw.getvalue().decode("utf-8").strip() == "Laboratório — ✓"


@pytest.mark.parametrize("args", [["--help"], ["--version"]])
def test_cli_output_is_utf8_even_with_cp1252_default(args):
    """Simula o Windows: o processo filho tem cp1252 como padrão de E/S (sem modo UTF-8)."""
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252", "QT_QPA_PLATFORM": "offscreen"}
    out = subprocess.run([sys.executable, "-m", "jabuti", *args], capture_output=True, cwd=ROOT, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    text = out.stdout.decode("utf-8")                               # estrito: falha se vier em cp1252
    assert "Jabuti" in text
    if args == ["--help"]:
        assert "uso:" in text and "Laboratório de Genômica Eco-evolutiva Microbiana" in text


def test_offscreen_font_dir_on_windows(monkeypatch):
    from jabuti import cli

    monkeypatch.delenv("QT_QPA_FONTDIR", raising=False)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("WINDIR", r"C:\Windows")
    cli.offscreen_fonts()
    assert os.environ["QT_QPA_FONTDIR"].endswith("Fonts")
    monkeypatch.delenv("QT_QPA_FONTDIR")
    monkeypatch.setenv("QT_QPA_PLATFORM", "windows")                 # plataforma normal: nada muda
    cli.offscreen_fonts()
    assert "QT_QPA_FONTDIR" not in os.environ
