"""Erros de parsing com mensagens amigáveis para a GUI."""

from __future__ import annotations

from pathlib import Path


class JabutiParseError(Exception):
    """Erro de leitura de arquivo com contexto (arquivo, linha)."""

    def __init__(self, message: str, path: str | Path | None = None, line: int | None = None) -> None:
        self.message = message
        self.path = Path(path) if path is not None else None
        self.line = line
        super().__init__(self.user_message())

    def user_message(self) -> str:
        parts = []
        if self.path is not None:
            parts.append(f"Arquivo: {self.path.name}")
        if self.line is not None:
            parts.append(f"Linha: {self.line}")
        parts.append(self.message)
        return "\n".join(parts)


class TreeParseError(JabutiParseError):
    pass


def read_text(path: str | Path, error_cls: type[JabutiParseError] = JabutiParseError) -> str:
    """Lê um arquivo de texto tolerando BOM e codificações comuns."""
    p = Path(path)
    if not p.exists():
        raise error_cls("Arquivo não encontrado.", p)
    if p.is_dir():
        raise error_cls("O caminho é uma pasta, não um arquivo.", p)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise error_cls(f"Não foi possível ler o arquivo: {exc.strerror or exc}", p) from exc
    return decode_text(raw, p)


# arquivos do usuário: UTF-8 (com ou sem BOM); senão, os dois mais comuns em planilhas e
# editores do Windows. latin-1 aceita qualquer byte, então a leitura nunca quebra.
TEXT_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def decode_text(raw: bytes, path: str | Path | None = None) -> str:
    """Bytes de um arquivo de texto do usuário → texto. Tenta UTF-8 (BOM opcional) e cai
    para cp1252/latin-1 sem quebrar, registrando no log quando não era UTF-8."""
    for enc in TEXT_ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if enc != "utf-8-sig":
            from jabuti.logs import get_logger

            name = Path(path).name if path is not None else "(texto)"
            get_logger("leitura").warning("%s não está em UTF-8: lido como %s", name, enc)
        return text
    raise AssertionError("latin-1 decodifica qualquer sequência de bytes")  # pragma: no cover
