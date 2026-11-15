"""Desfazer/refazer (QUndoStack) das ações que mudam a árvore desenhada e o estilo.

Cada entrada guarda dois "estados do documento" compactos — o preset completo (estilo,
clados, edições da árvore, grupos de rótulos, detecção), o enraizamento aplicado e a lista
de anotações iTOL — e nunca uma cópia da árvore: as edições guardam só nomes de folhas.

O estado é lido depois de cada desenho (que já acontece uma vez por mudança, com o atraso
de 120 ms do redesenho ao vivo); se mudou, vira uma entrada com o nome da ação. Entradas
seguidas com o mesmo nome em menos de ``MERGE_SECONDS`` se juntam (arrastar um controle
deslizante ou escolher várias cores seguidas = um passo só).
"""

from __future__ import annotations

import json
import time
import weakref
from dataclasses import dataclass, field

from PySide6.QtGui import QUndoCommand, QUndoStack

from jabuti.logs import get_logger

UNDO_LIMIT = 100
MERGE_SECONDS = 1.5
_log = get_logger("undo")


@dataclass(frozen=True)
class ItolState:
    entry: object                        # ItolEntry (o dataset lido não é copiado)
    visible: bool
    title: str
    colors: tuple
    labels: tuple


@dataclass
class DocState:
    view: str                            # preset completo em JSON (ordenado)
    rooting: str                         # enraizamento em JSON
    itol: tuple = field(default_factory=tuple)

    def key(self) -> tuple:
        return (self.view, self.rooting, tuple((id(s.entry), s.visible, s.title, s.colors, s.labels)
                                                for s in self.itol))


_LAYOUT_NAMES = {"rectangular": "retangular", "slanted": "diagonal", "circular": "circular", "fan": "leque",
                 "unrooted": "não enraizada"}
_ROOTING = {"midpoint": "Enraizar no ponto médio", "outgroup": "Enraizar na folha", "group": "Enraizar no grupo selecionado",
            "file": "Voltar à raiz do arquivo"}
_EDITS = {"ladderize": "Ladderize", "rotations": "Girar nó", "collapsed": "Colapsar/expandir",
          "hidden": "Ocultar/restaurar folhas", "shortened": "Encurtar ramo", "marked": "Marcar folhas",
          "highlights": "Destacar linhas"}
_STYLE = {"branch": "Ramos", "label": "Rótulos", "support": "Suporte", "symbols": "Símbolos", "clades": "Cores dos clados",
          "legend": "Legenda", "scale_bar": "Barra de escala", "heatmap": "Heatmap de genes", "metadata": "Metadados",
          "context": "Contexto gênico", "fan": "Ângulo do leque", "unrooted": "Árvore não enraizada",
          "background": "Fundo", "guide": "Linhas-guia", "merge_backgrounds": "Fundos vizinhos",
          "branch_scale": "Escala dos ramos", "leaf_spacing": "Espaçamento das folhas", "align_tips": "Alinhar pontas"}


# só ajustes contínuos se juntam (deslizadores, caixas numéricas, cores de estilo);
# ações discretas — estrutura, enraizamento, clados, grupos, layout, anotações — nunca
MERGEABLE = set(_STYLE.values()) | {"Estilo", "Figura", "Barras", "Barras empilhadas", "Matriz", "Níveis de suporte",
                                    "Textos nos ramos", "Nomes", "Editar anotação iTOL"}


def describe(old: DocState, new: DocState) -> str:
    """Nome da ação a partir da diferença entre dois estados."""
    if old.rooting != new.rooting:
        r = json.loads(new.rooting)
        name = _ROOTING.get(r.get("mode", ""), "Enraizar")
        return f"{name} {r['leaf']}" if r.get("mode") == "outgroup" and r.get("leaf") else name
    if old.itol != new.itol:
        a, b = {id(s.entry) for s in old.itol}, {id(s.entry) for s in new.itol}
        if b - a:
            return "Importar anotação iTOL"
        if a - b:
            return "Remover anotação iTOL"
        if [id(s.entry) for s in old.itol] != [id(s.entry) for s in new.itol]:
            return "Reordenar anotações iTOL"
        return "Editar anotação iTOL"
    o, n = json.loads(old.view), json.loads(new.view)
    oe, ne = o.get("edits") or {}, n.get("edits") or {}
    for k, label in _EDITS.items():
        if oe.get(k) != ne.get(k):
            return label
    if (o.get("clades"), o.get("clade_auto_mode"), o.get("detection")) != \
            (n.get("clades"), n.get("clade_auto_mode"), n.get("detection")):
        return "Clados"
    if o.get("label_groups") != n.get("label_groups"):
        return "Grupos de rótulos"
    os_, ns = o.get("style") or {}, n.get("style") or {}
    if os_.get("layout") != ns.get("layout"):
        return f"Layout {_LAYOUT_NAMES.get(ns.get('layout'), ns.get('layout'))}"
    if os_.get("use_lengths") != ns.get("use_lengths"):
        return "Usar comprimentos de ramo" if ns.get("use_lengths") else "Modo cladograma"
    for k, label in _STYLE.items():
        if os_.get(k) != ns.get(k):
            return label
    if os_.get("figure") != ns.get("figure"):
        of, nf = os_.get("figure") or {}, ns.get("figure") or {}
        if of.get("itol") != nf.get("itol"):
            return "Editar anotação iTOL"
        key = next((k for k in nf if of.get(k) != nf.get(k)), "")
        return {"bars": "Barras", "stacked": "Barras empilhadas", "matrices": "Matriz", "track_order": "Ordem das colunas",
                "hidden_tracks": "Mostrar/ocultar colunas", "names": "Nomes", "support_levels": "Níveis de suporte",
                "branch_text": "Textos nos ramos"}.get(key, "Figura")
    return "Estilo"


class StateCommand(QUndoCommand):
    def __init__(self, ctl: "UndoController", old: DocState, new: DocState, label: str) -> None:
        super().__init__(label)
        # referência fraca: o comando pertence à pilha (C++) e não pode manter a janela viva
        self._ctl = weakref.ref(ctl)
        self.old, self.new, self.label = old, new, label
        self.stamp = time.monotonic()
        self._first = True                   # o estado já está aplicado quando entra na pilha

    def id(self) -> int:                     # noqa: A003 — API do Qt
        return 1

    def mergeWith(self, other) -> bool:  # type: ignore[no-untyped-def]  # noqa: N802
        if not isinstance(other, StateCommand) or other.label != self.label or self.label not in MERGEABLE:
            return False
        if other.stamp - self.stamp > MERGE_SECONDS:
            return False
        self.new, self.stamp = other.new, other.stamp
        if self.new.key() == self.old.key():
            self.setObsolete(True)
        return True

    def redo(self) -> None:
        if self._first:
            self._first = False
            return
        ctl = self._ctl()
        if ctl is not None:
            ctl.apply(self.new)

    def undo(self) -> None:
        ctl = self._ctl()
        if ctl is not None:
            ctl.apply(self.old)


class UndoController:
    def __init__(self, win) -> None:  # type: ignore[no-untyped-def]
        self._win = weakref.ref(win)
        self.stack = QUndoStack()               # sem pai: não emite sinais durante a destruição da janela
        self.stack.setUndoLimit(UNDO_LIMIT)
        self.last: DocState | None = None
        self.restoring = False
        self.enabled = True

    @property
    def win(self):  # type: ignore[no-untyped-def]
        return self._win()

    # ------------------------------------------------------------------ estado
    def capture(self) -> DocState | None:
        w = self.win
        if w.tree is None:
            return None
        view = json.dumps(w.collect_preset(include_tree_state=True), sort_keys=True, ensure_ascii=False)
        rooting = json.dumps(w.tree_tab.rooting, sort_keys=True)
        itol = tuple(ItolState(e, e.visible, e.title, tuple(sorted(e.colors.items())), tuple(sorted(e.labels.items())))
                     for e in w.figure_panel.itol.entries)
        return DocState(view, rooting, itol)

    def reset(self) -> None:
        """Histórico zerado (outra árvore ou outro projeto); o estado atual vira o ponto de partida."""
        self.stack.clear()
        self.last = self.capture()

    def record(self) -> None:
        """Chamado depois de cada desenho: empilha a mudança (se houve)."""
        if self.restoring or not self.enabled or getattr(self.win.project, "loading", False):
            return
        try:
            new = self.capture()
        except Exception:  # noqa: BLE001 — o histórico nunca pode derrubar o desenho
            _log.exception("falha ao ler o estado para desfazer")
            return
        if new is None:
            self.last = None
            return
        if self.last is None:
            self.last = new
            return
        if new.key() == self.last.key():
            return
        old, self.last = self.last, new
        self.stack.push(StateCommand(self, old, new, describe(old, new)))

    # ------------------------------------------------------------------ restaurar
    def apply(self, state: DocState) -> None:
        from jabuti.presets import preset_from_dict

        w = self.win
        self.restoring = True
        try:
            rooting = json.loads(state.rooting)
            if rooting != w.tree_tab.rooting:
                if rooting.get("mode", "file") == "file":
                    w.tree_tab.reset_rooting()
                else:
                    w.tree_tab.apply_rooting_spec(rooting)
            itol = w.figure_panel.itol
            current = [s.entry for s in state.itol]
            if [id(e) for e in itol.entries] != [id(e) for e in current] or any(
                    (e.visible, e.title, tuple(sorted(e.colors.items())), tuple(sorted(e.labels.items())))
                    != (s.visible, s.title, s.colors, s.labels) for e, s in zip(itol.entries, state.itol)):
                itol.restore_entries([(s.entry, s.visible, s.title, dict(s.colors), dict(s.labels)) for s in state.itol])
            w.apply_preset(preset_from_dict(json.loads(state.view)))
            w._live_timer.stop()
            w.generate()
            w._live_timer.stop()
        finally:
            self.restoring = False
        self.last = self.capture()
