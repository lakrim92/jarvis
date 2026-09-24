"""Interface graphique de Jarvis : HUD holographique anime, dans l'esprit du film (PySide6).

Tout est dessine en code (anneaux, graduations, halo) : aucune image ni ressource protegee.
"""
import math
import time

import clock

from PySide6.QtCore import Qt, QTimer, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

STATE_COLORS = {
    "idle": QColor(0, 190, 255),
    "listening": QColor(90, 235, 255),
    "thinking": QColor(255, 190, 60),
    "speaking": QColor(150, 245, 255),
    "error": QColor(255, 80, 80),
    "sleeping": QColor(60, 110, 150),
}
STATE_LABELS = {
    "idle": "EN LIGNE — DIS « HEY JARVIS »",
    "listening": "JE T'ÉCOUTE",
    "thinking": "ANALYSE EN COURS",
    "speaking": "JE RÉPONDS",
    "error": "ERREUR",
    "sleeping": "EN VEILLE — APPELLE-MOI : « HEY JARVIS »",
}
SPEED = {"idle": 1.0, "listening": 1.7, "thinking": 3.4, "speaking": 1.6, "error": 0.5, "sleeping": 0.25}
INTENSITY = {"idle": 0.8, "listening": 1.0, "thinking": 1.0, "speaking": 1.0, "error": 1.0, "sleeping": 0.38}
JOURS = ["LUN", "MAR", "MER", "JEU", "VEN", "SAM", "DIM"]
MOIS = ["JANV", "FÉVR", "MARS", "AVR", "MAI", "JUIN", "JUIL", "AOÛT", "SEPT", "OCT", "NOV", "DÉC"]


def _lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


class HudOrb(QWidget):
    """Coeur du HUD : anneaux concentriques qui tournent, graduations, barres reactives a la voix."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(360, 360)
        self.state = "idle"
        self._t = 0.0
        self._last = time.monotonic()
        self._rot = [0.0] * 5
        self._speed = 1.0
        self._intensity = INTENSITY["idle"]
        self._level = 0.0
        self._level_target = 0.0
        self._level_stamp = 0.0
        self._rgb = [float(STATE_COLORS["idle"].red()), float(STATE_COLORS["idle"].green()),
                     float(STATE_COLORS["idle"].blue())]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_state(self, state: str):
        self.state = state if state in STATE_COLORS else "idle"

    def set_level(self, value: float):
        self._level_target = max(0.0, min(1.0, value))
        self._level_stamp = time.monotonic()

    # ------------------------------------------------------------------ animation
    def _tick(self):
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now
        self._t += dt
        k = min(1.0, dt * 4)
        self._speed = _lerp(self._speed, SPEED[self.state], k)
        self._intensity = _lerp(self._intensity, INTENSITY[self.state], k)
        target = STATE_COLORS[self.state]
        for i, v in enumerate((target.red(), target.green(), target.blue())):
            self._rgb[i] = _lerp(self._rgb[i], v, k)

        # niveau : mesure reelle si elle est recente, sinon une respiration simulee selon l'etat
        if now - self._level_stamp < 0.25:
            goal = self._level_target
        else:
            t = self._t
            goal = {"idle": 0.06 + 0.04 * math.sin(t * 1.5), "listening": 0.16 + 0.1 * math.sin(t * 3),
                    "thinking": 0.32 + 0.2 * math.sin(t * 7), "speaking": 0.3 + 0.28 * abs(math.sin(t * 9)),
                    "sleeping": 0.03, "error": 0.2}[self.state]
        self._level = _lerp(self._level, max(0.0, goal), min(1.0, dt * 10))

        for i, rate in enumerate((6.0, -18.0, 24.0, 14.0, -55.0)):
            self._rot[i] = (self._rot[i] + dt * rate * self._speed) % 360
        self.update()

    # ------------------------------------------------------------------ dessin
    def _c(self, alpha: float) -> QColor:
        return QColor(int(self._rgb[0]), int(self._rgb[1]), int(self._rgb[2]),
                      max(0, min(255, int(alpha * 255 * self._intensity))))

    @staticmethod
    def _pt(cx, cy, r, deg):
        a = math.radians(deg)
        return QPointF(cx + r * math.cos(a), cy + r * math.sin(a))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        R = min(self.width(), self.height()) / 2 - 8
        lvl = self._level

        # halo
        glow = QRadialGradient(QPointF(cx, cy), R)
        glow.setColorAt(0.0, self._c(0.32 + 0.35 * lvl))
        glow.setColorAt(0.55, self._c(0.09))
        glow.setColorAt(1.0, self._c(0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), R, R)

        # anneau exterieur + graduations
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(self._c(0.75), 1.4))
        p.drawEllipse(QPointF(cx, cy), R, R)
        for i in range(120):
            deg = i * 3 + self._rot[0]
            length = 11 if i % 10 == 0 else (7 if i % 5 == 0 else 3.5)
            p.setPen(QPen(self._c(0.85 if i % 10 == 0 else 0.5), 1.3 if i % 10 == 0 else 1))
            p.drawLine(self._pt(cx, cy, R - 5, deg), self._pt(cx, cy, R - 5 - length, deg))

        # anneau 2 : quatre arcs, sens inverse
        r2 = R * 0.84
        p.setPen(QPen(self._c(0.9), 3.2, Qt.SolidLine, Qt.FlatCap))
        for i in range(4):
            p.drawArc(QRectF(cx - r2, cy - r2, 2 * r2, 2 * r2), int((i * 90 + self._rot[1]) * 16), int(58 * 16))
        p.setPen(QPen(self._c(0.35), 1))
        p.drawEllipse(QPointF(cx, cy), r2 - 7, r2 - 7)

        # anneau 3 : pointille qui tourne
        r3 = R * 0.72
        pen = QPen(self._c(0.7), 1.6)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([2.0, 5.0])
        pen.setDashOffset(self._rot[2] / 2)
        p.setPen(pen)
        p.drawEllipse(QPointF(cx, cy), r3, r3)

        # anneau 4 : barres qui reagissent a la voix
        r4 = R * 0.58
        n = 64
        for i in range(n):
            deg = i * (360 / n) + self._rot[3]
            amp = 0.25 + 0.75 * abs(math.sin(i * 0.55 + self._t * 5.0 * self._speed) *
                                    math.cos(i * 0.21 - self._t * 2.3))
            length = 3 + (3 + 32 * lvl) * amp
            p.setPen(QPen(self._c(0.55 + 0.4 * amp), 2.0, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(self._pt(cx, cy, r4, deg), self._pt(cx, cy, r4 + length, deg))

        # anneau 5 : arc epais rapide (balayage)
        r5 = R * 0.46
        p.setPen(QPen(self._c(0.95), 5, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(cx - r5, cy - r5, 2 * r5, 2 * r5), int(self._rot[4] * 16), int((110 + 60 * lvl) * 16))
        p.setPen(QPen(self._c(0.4), 1.2))
        p.drawEllipse(QPointF(cx, cy), r5 - 8, r5 - 8)

        # coeur lumineux
        rc = R * 0.27 * (1 + 0.05 * math.sin(self._t * 2.2) + 0.28 * lvl)
        core = QRadialGradient(QPointF(cx, cy), rc)
        core.setColorAt(0.0, QColor(255, 255, 255, int(235 * max(self._intensity, 0.5))))
        core.setColorAt(0.35, self._c(0.95))
        core.setColorAt(1.0, self._c(0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(core)
        p.drawEllipse(QPointF(cx, cy), rc, rc)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(self._c(0.9), 1.5))
        p.drawEllipse(QPointF(cx, cy), R * 0.135, R * 0.135)


class HudFrame(QWidget):
    """Cadre de la fenetre : fond sombre translucide et reperes d'angle."""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(0, 200, 255, 55), 1))
        p.setBrush(QColor(3, 9, 16, 225))
        p.drawRoundedRect(r, 14, 14)
        p.setPen(QPen(QColor(110, 230, 255, 235), 2))
        m, size = 7, 24
        x0, y0, x1, y1 = r.left() + m, r.top() + m, r.right() - m, r.bottom() - m
        for x, y, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * size, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * size))


class JarvisWindow(QWidget):
    """Fenetre HUD sans bordure, toujours au-dessus, deplacable."""

    user_text_submitted = Signal(str)
    quit_requested = Signal()
    remote_requested = Signal()
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag_pos = None
        self._state = "idle"
        self._build_ui()
        self._place_bottom_right()
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._update_clock)
        self._clock.start(1000)
        self._update_clock()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.container = HudFrame()
        self.container.setStyleSheet(
            """
            QLabel { color: #bdeeff; }
            QPushButton {
                background: transparent; color: #8fe6ff; border: 1px solid rgba(0,200,255,90);
                border-radius: 3px; padding: 3px 9px; font-size: 10px; letter-spacing: 1px;
            }
            QPushButton:hover { background: rgba(0,200,255,55); color: white; }
            QLineEdit {
                background: rgba(0,160,220,18); border: none; border-bottom: 1px solid rgba(0,200,255,120);
                padding: 7px 4px; color: #e8fbff;
            }
            QFrame#sep { background: rgba(0,200,255,70); max-height: 1px; min-height: 1px; border: none; }
            """
        )
        outer.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(26, 20, 26, 22)
        layout.setSpacing(6)

        top = QHBoxLayout()
        title = QLabel("J.A.R.V.I.S")
        f = QFont("Sans Serif", 13, QFont.Bold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 5)
        title.setFont(f)
        title.setStyleSheet("color: #7fe8ff;")
        top.addWidget(title)
        top.addStretch()
        for text, sig, tip in (("STOP", self.stop_requested, "Coupe la parole de Jarvis"),
                               ("TÉLÉCOMMANDE", self.remote_requested, "Télécommande de la Freebox"),
                               ("✕", self.quit_requested, "Quitter")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(sig.emit)
            top.addWidget(b)
        layout.addLayout(top)

        self.clock_label = QLabel("")
        self.clock_label.setFont(QFont("DejaVu Sans Mono", 9))
        self.clock_label.setStyleSheet("color: #4fb8d6;")
        layout.addWidget(self.clock_label)

        orb_row = QHBoxLayout()
        orb_row.addStretch()
        self.orb = HudOrb()
        orb_row.addWidget(self.orb)
        orb_row.addStretch()
        layout.addLayout(orb_row)

        self.status_label = QLabel(STATE_LABELS["idle"])
        self.status_label.setAlignment(Qt.AlignCenter)
        sf = QFont("Sans Serif", 9, QFont.DemiBold)
        sf.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        self.status_label.setFont(sf)
        self.status_label.setStyleSheet("color: #7fe8ff;")
        layout.addWidget(self.status_label)

        sep = QFrame()
        sep.setObjectName("sep")
        layout.addWidget(sep)

        self.log_area = QScrollArea()
        self.log_area.setWidgetResizable(True)
        self.log_area.setFixedHeight(180)
        self.log_area.setStyleSheet("background: transparent; border: none;")
        self.log_area.viewport().setStyleSheet("background: transparent;")
        self.log_content = QWidget()
        self.log_content.setStyleSheet("background: transparent;")
        self.log_layout = QVBoxLayout(self.log_content)
        self.log_layout.setSpacing(5)
        self.log_layout.addStretch()
        self.log_area.setWidget(self.log_content)
        layout.addWidget(self.log_area)

        input_row = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Écris ici plutôt que parler…")
        self.text_input.returnPressed.connect(self._on_text_submit)
        input_row.addWidget(self.text_input)
        send_btn = QPushButton("ENVOYER")
        send_btn.setFocusPolicy(Qt.NoFocus)
        send_btn.clicked.connect(self._on_text_submit)
        input_row.addWidget(send_btn)
        layout.addLayout(input_row)

        self.setFixedWidth(452)

    def _place_bottom_right(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        self.move(screen.right() - self.width() - 24, screen.bottom() - self.height() - 20)

    def _update_clock(self):
        n = clock.now()      # heure reelle (et non celle du PC, qui peut etre fausse)
        self.clock_label.setText(f"{n:%H:%M:%S}  ·  {JOURS[n.weekday()]} {n.day:02d} {MOIS[n.month - 1]} {n.year}")

    def _on_text_submit(self):
        text = self.text_input.text().strip()
        if text:
            self.text_input.clear()
            self.user_text_submitted.emit(text)

    # ------------------------------------------------------------------ etat
    def set_level(self, value: float):
        self.orb.set_level(value)

    def show_notice(self, text: str):
        """Message discret dans la ligne d'etat, qui revient a l'etat normal apres quelques secondes."""
        self.status_label.setText(text.upper())
        QTimer.singleShot(5000, lambda: self.status_label.setText(STATE_LABELS.get(self._state, "")))

    def set_state(self, state: str, extra: str = ""):
        self._state = state
        self.orb.set_state(state)
        self.status_label.setText(extra.upper() if extra else STATE_LABELS.get(state, state))

    def append_message(self, role: str, text: str):
        who, color = ("VOUS", "#5fe0ff") if role == "user" else ("JARVIS", "#ffffff")
        label = QLabel(f"<span style='color:{color}; letter-spacing:2px; font-size:8pt;'>{who}</span>"
                       f"<br><span style='color:#cdefff;'>{_escape(text)}</span>")
        label.setWordWrap(True)
        label.setFont(QFont("Sans Serif", 9))
        self.log_layout.insertWidget(self.log_layout.count() - 1, label)
        QTimer.singleShot(50, lambda: self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()))

    # --- deplacement de la fenetre sans bordure ---
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
