"""Interface graphique HUD de Jarvis (PySide6)."""
import math

from PySide6.QtCore import Qt, QTimer, Signal, QPoint
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QLinearGradient, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
    QPushButton, QSizePolicy,
)

STATE_COLORS = {
    "idle": QColor(90, 110, 130),
    "listening": QColor(0, 200, 255),
    "thinking": QColor(170, 90, 255),
    "speaking": QColor(60, 220, 140),
    "error": QColor(230, 70, 70),
}
STATE_LABELS = {
    "idle": "En veille — dis « Jarvis »",
    "listening": "Je t'ecoute...",
    "thinking": "Je reflechis...",
    "speaking": "Je reponds...",
    "error": "Erreur",
}


class Orb(QWidget):
    """Cercle anime qui indique l'etat de l'assistant."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 140)
        self.state = "idle"
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_state(self, state: str):
        self.state = state
        self.update()

    def _tick(self):
        self._phase += 0.08
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        base_color = STATE_COLORS.get(self.state, STATE_COLORS["idle"])

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        pulse = (math.sin(self._phase) + 1) / 2  # 0..1

        if self.state == "idle":
            radius = 34
        else:
            radius = 34 + pulse * 12

        # halo exterieur
        gradient = QLinearGradient(0, 0, w, h)
        halo_color = QColor(base_color)
        halo_color.setAlpha(60)
        painter.setPen(Qt.NoPen)
        painter.setBrush(halo_color)
        halo_r = radius + 18 + pulse * 6
        painter.drawEllipse(QPoint(int(cx), int(cy)), int(halo_r), int(halo_r))

        # anneau
        pen = QPen(base_color, 3)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPoint(int(cx), int(cy)), int(radius), int(radius))

        # coeur
        core_color = QColor(base_color)
        core_color.setAlpha(200)
        painter.setPen(Qt.NoPen)
        painter.setBrush(core_color)
        painter.drawEllipse(QPoint(int(cx), int(cy)), int(radius * 0.55), int(radius * 0.55))


class JarvisWindow(QWidget):
    """Fenetre HUD sans bordure, toujours au-dessus, deplacable."""

    user_text_submitted = Signal(str)
    quit_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag_pos = None

        self._build_ui()
        self._place_bottom_right()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.container = QWidget(objectName="container")
        self.container.setStyleSheet(
            """
            #container {
                background-color: rgba(15, 18, 25, 235);
                border-radius: 18px;
                border: 1px solid rgba(90, 200, 255, 60);
            }
            QLabel { color: #d7e6f5; }
            QLineEdit {
                background-color: rgba(255,255,255,20);
                border: 1px solid rgba(90,200,255,80);
                border-radius: 8px;
                padding: 6px 10px;
                color: white;
            }
            QPushButton {
                background-color: rgba(255,255,255,15);
                border: none;
                border-radius: 6px;
                color: #d7e6f5;
                padding: 4px 8px;
            }
            QPushButton:hover { background-color: rgba(255,255,255,35); }
            """
        )
        outer.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(16, 12, 16, 14)

        top_bar = QHBoxLayout()
        title = QLabel("JARVIS")
        title.setFont(QFont("Sans Serif", 11, QFont.Bold))
        top_bar.addWidget(title)
        top_bar.addStretch()
        close_btn = QPushButton("x")
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(self.quit_requested.emit)
        top_bar.addWidget(close_btn)
        layout.addLayout(top_bar)

        orb_row = QHBoxLayout()
        orb_row.addStretch()
        self.orb = Orb()
        orb_row.addWidget(self.orb)
        orb_row.addStretch()
        layout.addLayout(orb_row)

        self.status_label = QLabel(STATE_LABELS["idle"])
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(QFont("Sans Serif", 10))
        layout.addWidget(self.status_label)

        self.log_area = QScrollArea()
        self.log_area.setWidgetResizable(True)
        self.log_area.setFixedHeight(160)
        self.log_area.setStyleSheet("background: transparent; border: none;")
        self.log_content = QWidget()
        self.log_layout = QVBoxLayout(self.log_content)
        self.log_layout.addStretch()
        self.log_area.setWidget(self.log_content)
        layout.addWidget(self.log_area)

        input_row = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Ou ecris ici plutot que parler...")
        self.text_input.returnPressed.connect(self._on_text_submit)
        input_row.addWidget(self.text_input)
        send_btn = QPushButton("Envoyer")
        send_btn.clicked.connect(self._on_text_submit)
        input_row.addWidget(send_btn)
        layout.addLayout(input_row)

        self.setFixedWidth(340)

    def _place_bottom_right(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        x = screen.right() - self.width() - 24
        y = screen.bottom() - self.height() - 24
        self.move(x, y)

    def _on_text_submit(self):
        text = self.text_input.text().strip()
        if text:
            self.text_input.clear()
            self.user_text_submitted.emit(text)

    def set_state(self, state: str, extra: str = ""):
        self.orb.set_state(state)
        label = STATE_LABELS.get(state, state)
        if extra:
            label = extra
        self.status_label.setText(label)

    def append_message(self, role: str, text: str):
        color = "#5fd0ff" if role == "user" else "#7fffb0"
        prefix = "Toi" if role == "user" else "Jarvis"
        label = QLabel(f"<b style='color:{color}'>{prefix} :</b> {_escape(text)}")
        label.setWordWrap(True)
        label.setFont(QFont("Sans Serif", 9))
        self.log_layout.insertWidget(self.log_layout.count() - 1, label)
        QTimer.singleShot(50, lambda: self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        ))

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
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
