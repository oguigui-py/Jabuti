"""Leitura de arquivos em segundo plano, com progresso, lotes e cancelamento.

Usamos ``threading.Thread`` (e não ``QThread``) porque o ciclo de vida é mais simples:
destruir um ``QThread`` ainda em execução aborta o processo, e a thread Python pode ser
cancelada e aguardada sem esse risco. (Nas medições, ``QThread`` e ``threading.Thread``
deixaram a GUI igualmente responsiva.)

O objeto ``FileLoader`` vive na thread da GUI; a thread de trabalho só emite sinais, que o
Qt entrega enfileirados na thread da GUI. A função de leitura não pode criar objetos Qt.

Cuidado ao tratar os resultados na GUI: enquanto a leitura roda, cada chamada ao sistema
feita pela thread da GUI (ex.: ``Path.resolve()``) solta o GIL e precisa esperar para
recuperá-lo. Milhares delas travaram a interface por quase 1 s; por isso os caminhos são
resolvidos uma única vez, antes de iniciar a leitura.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from jabuti.logs import get_logger
from jabuti.parsers.errors import JabutiParseError
from jabuti.parsers.gff import LoadCancelled

ParseFn = Callable[[Path, Callable[[], bool]], Any]


class FileLoader(QObject):
    """Lê ``paths`` numa thread e devolve resultados em lotes (no máximo a cada ``BATCH_SECONDS``),
    para a GUI tratar poucos eventos em vez de um por arquivo."""

    BATCH_SECONDS = 0.05

    progress = Signal(int, int, str)     # concluídos, total, próximo arquivo
    items = Signal(list)                 # [(ok: bool, caminho, resultado | mensagem), ...]
    finished = Signal(bool)              # cancelado?

    def __init__(self, paths: list[Path], parse: ParseFn) -> None:
        super().__init__()
        self.paths = list(paths)
        self.parse = parse
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="jabuti-loader", daemon=True)
        self.thread.start()

    def cancel(self) -> None:
        """Pode ser chamado de qualquer thread."""
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self.thread is not None:
            self.thread.join(timeout)

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    @property
    def cancelled(self) -> bool:
        return self._stop.is_set()

    def _run(self) -> None:
        total = len(self.paths)
        done = 0
        batch: list[tuple[bool, str, Any]] = []
        last = time.monotonic()

        def flush(next_name: str) -> None:
            nonlocal batch, last
            if batch:
                self.items.emit(batch)
                batch = []
            self.progress.emit(done, total, next_name)
            last = time.monotonic()

        try:
            self.progress.emit(0, total, self.paths[0].name if self.paths else "")
            for i, path in enumerate(self.paths):
                if self._stop.is_set():
                    break
                try:
                    batch.append((True, str(path), self.parse(path, self._stop.is_set)))
                except LoadCancelled:
                    break
                except JabutiParseError as exc:
                    batch.append((False, str(path), exc.user_message()))
                except Exception as exc:  # noqa: BLE001 — nenhum erro pode derrubar a thread
                    get_logger("workers").error("Erro lendo %s", path, exc_info=True)
                    batch.append((False, str(path), f"Arquivo: {path.name}\n{exc.__class__.__name__}: {exc}"))
                done += 1
                if time.monotonic() - last >= self.BATCH_SECONDS:
                    flush(self.paths[i + 1].name if i + 1 < total else "")
            flush("")
        finally:
            self.finished.emit(self._stop.is_set())
