"""Tela de abertura: logo do Jabuti, o nome e os créditos sobre um fundo animado e discreto.

O fundo (ramos de árvore filogenética crescendo, dupla hélice ondulando e
pontos flutuando) é desenhado com QPainter a ~30 fps. As partes fixas (sombra,
cartão, logo e textos) são pré-renderizadas uma vez, então cada quadro só
redesenha linhas finas — pouca CPU. A logo também tem uma árvore: um halo opaco na cor
do cartão fica atrás dela e do nome, e a árvore animada só cresce na faixa da esquerda,
esmaecendo antes do halo, para o fundo não competir com o desenho.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import (
    QElapsedTimer,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QBrush,
    QLinearGradient,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from jabuti.credits import CREDIT_AUTHOR, CREDIT_LAB
from jabuti.resources import JABUTI_GREEN, JABUTI_LOGO, load_pixmap

CARD_W, CARD_H = 600, 400
MARGIN = 22                 # área transparente ao redor do cartão (sombra)
RADIUS = 18
CARD_COLOR = QColor("#f7f6f1")
MOTIF = QColor("#5f7f6e")   # verde-acinzentado do fundo animado
LOGO_FRACTION = 0.50        # largura da logo (recortada) em relação ao cartão
APP_NAME = "Jabuti"
CREDIT_1 = CREDIT_LAB
CREDIT_2 = CREDIT_AUTHOR
TREE_ZONE = 0.30            # a árvore animada ocupa só esta fração da largura, à esquerda


@dataclass
class _Branch:
    """Ramo horizontal que cresce de x0 a x1 entre t0 e t1, mais o conector
    vertical (bifurcação) na ponta, que abre do centro para fora."""

    x0: float
    x1: float
    y: float
    t0: float
    t1: float
    fork: float = 0.0       # meia-altura do conector (0 = folha)


def _grow_tree(seed: int = 7) -> list[_Branch]:
    rng = random.Random(seed)
    speed = 230.0           # px/s
    out: list[_Branch] = []

    def node(x: float, y: float, spread: float, depth: int, t: float) -> None:
        length = rng.uniform(34, 70) * (1.0 if depth else 1.4)
        t1 = t + length / speed
        leaf = depth >= 5 or (depth >= 3 and rng.random() < 0.2)
        b = _Branch(x, x + length, y, t, t1, 0.0 if leaf else spread / 2)
        out.append(b)
        if leaf:
            return
        nxt = t1 + 0.12      # tempo do conector abrir
        for sign in (-1, 1):
            node(b.x1, y + sign * spread / 2, spread * rng.uniform(0.48, 0.58), depth + 1, nxt)

    node(18.0, CARD_H * 0.47, CARD_H * 0.52, 0, 0.0)
    # comprime na horizontal para caber na faixa da esquerda (fora do halo da logo)
    right = max(b.x1 for b in out)
    k = (CARD_W * TREE_ZONE - 18.0) / max(right - 18.0, 1.0)
    for b in out:
        b.x0 = 18.0 + (b.x0 - 18.0) * k
        b.x1 = 18.0 + (b.x1 - 18.0) * k
    return out


class SplashScreen(QWidget):
    """Janela de abertura sem moldura. Emite ``closing`` no início do fade-out
    (hora de mostrar a janela principal por baixo) e ``finished`` ao sumir."""

    closing = Signal()
    finished = Signal()

    DURATION_MS = 3000
    FADE_IN_MS = 350
    FADE_OUT_MS = 400
    FPS = 30

    def __init__(self, duration_ms: int | None = None) -> None:
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle("Jabuti")
        self.setFixedSize(CARD_W + 2 * MARGIN, CARD_H + 2 * MARGIN)
        self.duration_ms = self.DURATION_MS if duration_ms is None else duration_ms

        self._branches = _grow_tree()
        rng = random.Random(11)
        self._dots = [
            (rng.uniform(0, CARD_W), rng.uniform(0, CARD_H), rng.uniform(-6, 6), rng.uniform(-4, 4),
             rng.uniform(1.2, 2.6), rng.uniform(0, math.tau))
            for _ in range(28)
        ]
        self._card = QPainterPath()
        self._card.addRoundedRect(QRectF(MARGIN, MARGIN, CARD_W, CARD_H), RADIUS, RADIUS)
        self._base: QPixmap | None = None
        self._front: QPixmap | None = None
        self.logo = QPixmap()
        self.frames = 0
        self._closing = False

        self._clock = QElapsedTimer()
        self._tick = QTimer(self)
        self._tick.setInterval(round(1000 / self.FPS))
        self._tick.timeout.connect(self.update)
        self._end_timer = QTimer(self)
        self._end_timer.setSingleShot(True)
        self._end_timer.timeout.connect(self.dismiss)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)

    # ------------------------------------------------------------ ciclo
    def start(self) -> None:
        """Mostra centralizada, com fade-in, e agenda o fechamento."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)
        self._prepare_layers()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        self._clock.start()
        self._tick.start()
        self._animate_opacity(1.0, self.FADE_IN_MS)
        self._end_timer.start(max(self.duration_ms - self.FADE_OUT_MS, 0))

    def dismiss(self) -> None:
        """Inicia o fade-out (timer, clique ou tecla). Idempotente."""
        if self._closing:
            return
        self._closing = True
        self._end_timer.stop()
        self.closing.emit()
        self.raise_()
        self._animate_opacity(0.0, self.FADE_OUT_MS)
        self._fade.finished.connect(self._done)

    def _done(self) -> None:
        self._tick.stop()
        self.finished.emit()
        self.close()

    def _animate_opacity(self, target: float, ms: int) -> None:
        self._fade.stop()
        self._fade.setDuration(ms)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(target)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade.start()

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.dismiss()

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.dismiss()

    # ------------------------------------------------------- camadas fixas
    def _prepare_layers(self) -> None:
        dpr = self.devicePixelRatioF()
        w, h = self.width(), self.height()

        def blank() -> QPixmap:
            pm = QPixmap(round(w * dpr), round(h * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            return pm

        # sombra leve + cartão
        base = blank()
        p = QPainter(base)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(MARGIN, 0, -2):
            alpha = int(26 * (1 - i / MARGIN) ** 2)
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(QRectF(MARGIN - i, MARGIN - i + 4, CARD_W + 2 * i, CARD_H + 2 * i),
                              RADIUS + i, RADIUS + i)
        p.setBrush(CARD_COLOR)
        p.drawPath(self._card)
        p.end()
        self._base = base

        # halo opaco atrás da logo e do nome, logo, nome e créditos
        front = blank()
        p = QPainter(front)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        logo_w = CARD_W * LOGO_FRACTION
        self.logo = load_pixmap(JABUTI_LOGO, logo_w, dpr, trim=True)
        logo_h = self.logo.height() / self.logo.devicePixelRatio() if not self.logo.isNull() else 0
        fn, f1, f2 = QFont(self.font()), QFont(self.font()), QFont(self.font())
        fn.setPointSizeF(30)
        fn.setWeight(QFont.Weight.DemiBold)
        fn.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 103)
        f1.setPointSizeF(11.5)
        f2.setPointSizeF(10.5)
        hn, h1, h2 = QFontMetrics(fn).height(), QFontMetrics(f1).height(), QFontMetrics(f2).height()
        gap_name, gap_credits = 8, 16
        block = logo_h + gap_name + hn + gap_credits + h1 + 4 + h2
        top = MARGIN + (CARD_H - block) / 2
        cx = MARGIN + CARD_W / 2

        # elipse opaca (cor do cartão) sobre logo + nome, com borda suave: o fundo some ali
        ecy = top + (logo_h + gap_name + hn) / 2
        rx, ry = logo_w / 2 + 70, (logo_h + gap_name + hn) / 2 + 48
        glow = QRadialGradient(QPointF(0, 0), 1.0)
        solid = QColor(CARD_COLOR)
        glow.setColorAt(0.0, solid)
        glow.setColorAt(0.72, solid)
        fade = QColor(CARD_COLOR)
        fade.setAlpha(0)
        glow.setColorAt(1.0, fade)
        p.setClipPath(self._card)
        p.save()
        p.translate(cx, ecy)
        p.scale(rx, ry)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(0, 0), 1.0, 1.0)
        p.restore()
        # faixa clara e suave atrás dos créditos (a hélice passa embaixo)
        band = QLinearGradient(MARGIN, 0, MARGIN + CARD_W, 0)
        c0 = QColor(CARD_COLOR)
        c0.setAlpha(0)
        c1 = QColor(CARD_COLOR)
        c1.setAlpha(235)
        band.setColorAt(0.0, c0)
        band.setColorAt(0.2, c1)
        band.setColorAt(0.8, c1)
        band.setColorAt(1.0, c0)
        y_credits = top + logo_h + gap_name + hn + gap_credits
        p.fillRect(QRectF(MARGIN, y_credits - 6, CARD_W, h1 + 4 + h2 + 12), band)
        p.setClipping(False)

        if not self.logo.isNull():
            p.drawPixmap(QPointF(cx - logo_w / 2, top), self.logo)
        y = top + logo_h + gap_name
        p.setFont(fn)
        p.setPen(QColor(JABUTI_GREEN))
        p.drawText(QRectF(MARGIN, y, CARD_W, hn), Qt.AlignmentFlag.AlignCenter, APP_NAME)
        p.setFont(f1)
        p.drawText(QRectF(MARGIN, y_credits, CARD_W, h1), Qt.AlignmentFlag.AlignCenter, CREDIT_1)
        p.setFont(f2)
        p.setPen(QColor("#5f6b64"))
        p.drawText(QRectF(MARGIN, y_credits + h1 + 4, CARD_W, h2), Qt.AlignmentFlag.AlignCenter, CREDIT_2)
        p.end()
        self._front = front
        self._layout = {"top": top, "logo_w": logo_w, "logo_h": logo_h, "name_y": y, "credits_y": y_credits}

    # ------------------------------------------------------------ quadro
    def elapsed(self) -> float:
        return self._clock.elapsed() / 1000 if self._clock.isValid() else 0.0

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._base is None:
            self._prepare_layers()
        self.frames += 1
        p = QPainter(self)
        p.drawPixmap(0, 0, self._base)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setClipPath(self._card)
        p.translate(MARGIN, MARGIN)
        self.paint_motifs(p, self.elapsed())
        p.resetTransform()
        p.setClipping(False)
        p.drawPixmap(0, 0, self._front)
        p.end()

    def paint_motifs(self, p: QPainter, t: float) -> None:
        """Fundo animado em coordenadas do cartão (0..CARD_W × 0..CARD_H)."""
        self._paint_tree(p, t)
        self._paint_helix(p, t)
        self._paint_dots(p, t)

    def _pen(self, alpha: float, width: float) -> QPen:
        c = QColor(MOTIF)
        c.setAlphaF(max(0.0, min(alpha, 1.0)))
        pen = QPen(c, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen

    def _paint_tree(self, p: QPainter, t: float) -> None:
        sway = 1.5 * math.sin(t * 0.7)                # respiração quase imperceptível
        path = QPainterPath()
        for b in self._branches:
            if t <= b.t0:
                continue
            k = min((t - b.t0) / (b.t1 - b.t0), 1.0)
            k = 1 - (1 - k) ** 2                       # desacelera ao chegar
            y = b.y + sway * (b.x0 / CARD_W)
            path.moveTo(b.x0, y)
            path.lineTo(b.x0 + (b.x1 - b.x0) * k, y)
            if b.fork and t > b.t1:
                f = min((t - b.t1) / 0.12, 1.0) * b.fork
                path.moveTo(b.x1, y - f)
                path.lineTo(b.x1, y + f)
        grad = QLinearGradient(0, 0, CARD_W * TREE_ZONE, 0)     # esmaece até sumir antes do halo
        c = QColor(MOTIF)
        c.setAlphaF(0.20)
        grad.setColorAt(0.0, c)
        grad.setColorAt(0.6, c)
        c = QColor(MOTIF)
        c.setAlphaF(0.0)
        grad.setColorAt(1.0, c)
        pen = QPen(QBrush(grad), 1.1)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _paint_helix(self, p: QPainter, t: float) -> None:
        mid, amp, wave = CARD_H - 30, 12.0, 150.0
        phase = t * 0.9
        a, b = QPainterPath(), QPainterPath()
        rungs = QPainterPath()
        steps = 120
        for i in range(steps + 1):
            x = CARD_W * i / steps
            ang = x / wave * math.tau + phase
            ya, yb = mid + amp * math.sin(ang), mid - amp * math.sin(ang)
            if i == 0:
                a.moveTo(x, ya)
                b.moveTo(x, yb)
            else:
                a.lineTo(x, ya)
                b.lineTo(x, yb)
            if i % 4 == 2:
                rungs.moveTo(x, ya)
                rungs.lineTo(x, yb)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(self._pen(0.08, 0.8))
        p.drawPath(rungs)
        p.setPen(self._pen(0.18, 1.1))
        p.drawPath(a)
        p.setPen(self._pen(0.12, 1.1))
        p.drawPath(b)

    def _paint_dots(self, p: QPainter, t: float) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        for x0, y0, vx, vy, r, ph in self._dots:
            x = (x0 + vx * t) % CARD_W
            y = (y0 + vy * t) % CARD_H
            c = QColor(MOTIF)
            c.setAlphaF(0.10 + 0.08 * math.sin(t * 1.1 + ph))
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), r, r)
