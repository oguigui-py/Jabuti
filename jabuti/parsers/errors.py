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
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise error_cls("Codificação de texto não reconhecida.", p)  # pragma: no cover
