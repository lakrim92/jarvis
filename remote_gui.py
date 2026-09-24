"""Telecommande virtuelle de la Freebox Player (fenetre cliquable a la souris)."""
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from tools import freebox_remote

STYLE = """
#container {
    background-color: rgba(15, 18, 25, 240);
    border-radius: 18px;
    border: 1px solid rgba(90, 200, 255, 60);
}
QLabel { color: #d7e6f5; }
QPushButton {
    background-color: rgba(255,255,255,18);
    border: none; border-radius: 8px; color: #e6f1ff;
    padding: 7px 4px; min-height: 22px;
}
QPushButton:hover { background-color: rgba(90,200,255,60); }
QPushButton:pressed { background-color: rgba(90,200,255,120); }
QPushButton#ok { background-color: rgba(0,200,255,90); font-weight: bold; }
QPushButton#red { background-color: rgba(230,60,60,150); }
QPushButton#green { background-color: rgba(60,190,90,150); }
QPushButton#yellow { background-color: rgba(230,200,50,150); color: #111; }
QPushButton#blue { background-color: rgba(70,110,230,150); }
"""


class RemoteWindow(QWidget):
    result = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telecommande Jarvis")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag_pos = None
        self._build()
        self.result.connect(self._show_result)

    # --- construction ---
    def _btn(self, label, action, name=None):
        b = QPushButton(label)
        b.setFocusPolicy(Qt.NoFocus)
        if name:
            b.setObjectName(name)
        b.clicked.connect(lambda: self._run(label, action))
        return b

    def _fb(self, key):
        return lambda: freebox_remote.fb_key(key)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        box = QWidget(objectName="container")
        box.setStyleSheet(STYLE)
        outer.addWidget(box)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("FREEBOX POP")
        title.setFont(QFont("Sans Serif", 10, QFont.Bold))
        top.addWidget(title)
        top.addStretch()
        close = QPushButton("x")
        close.setFixedSize(22, 22)
        close.setFocusPolicy(Qt.NoFocus)
        close.clicked.connect(self.hide)
        top.addWidget(close)
        lay.addLayout(top)

        row = QHBoxLayout()
        for label, key in (("Retour", "BACK"), ("Accueil", "HOME"), ("TV", "TV")):
            row.addWidget(self._btn(label, self._fb(key)))
        lay.addLayout(row)

        dpad = QGridLayout()
        dpad.addWidget(self._btn("▲", self._fb("DPAD_UP")), 0, 1)
        dpad.addWidget(self._btn("◀", self._fb("DPAD_LEFT")), 1, 0)
        dpad.addWidget(self._btn("OK", self._fb("DPAD_CENTER"), "ok"), 1, 1)
        dpad.addWidget(self._btn("▶", self._fb("DPAD_RIGHT")), 1, 2)
        dpad.addWidget(self._btn("▼", self._fb("DPAD_DOWN")), 2, 1)
        lay.addLayout(dpad)

        row = QHBoxLayout()
        for label, key in (("Menu", "MENU"), ("Guide", "GUIDE"), ("Info", "INFO"), ("Dern.", "LAST_CHANNEL")):
            row.addWidget(self._btn(label, self._fb(key)))
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._btn("Chaîne −", self._fb("CHANNEL_DOWN")))
        row.addWidget(self._btn("Chaîne +", self._fb("CHANNEL_UP")))
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._btn("Vol −", self._fb("VOLUME_DOWN")))
        row.addWidget(self._btn("Muet", self._fb("VOLUME_MUTE")))
        row.addWidget(self._btn("Vol +", self._fb("VOLUME_UP")))
        lay.addLayout(row)

        row = QHBoxLayout()
        for label, key in (("⏮", "MEDIA_PREVIOUS"), ("⏪", "MEDIA_REWIND"), ("⏯", "MEDIA_PLAY_PAUSE"),
                           ("⏩", "MEDIA_FAST_FORWARD"), ("⏭", "MEDIA_NEXT"), ("⏹", "MEDIA_STOP")):
            row.addWidget(self._btn(label, self._fb(key)))
        lay.addLayout(row)

        digits = QGridLayout()
        for i, d in enumerate("123456789"):
            digits.addWidget(self._btn(d, self._fb(d)), i // 3, i % 3)
        digits.addWidget(self._btn("0", self._fb("0")), 3, 1)
        lay.addLayout(digits)

        row = QHBoxLayout()
        for name, key in (("red", "PROG_RED"), ("green", "PROG_GREEN"), ("yellow", "PROG_YELLOW"), ("blue", "PROG_BLUE")):
            row.addWidget(self._btn(" ", self._fb(key), name))
        lay.addLayout(row)

        self.status = QLabel("Prete")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #8fa6bf; font-size: 9px;")
        lay.addWidget(self.status)
        self.setFixedWidth(270)

    # --- actions ---
    def _run(self, label, action):
        def work():
            try:
                res = action()
            except Exception as exc:
                res = {"success": False, "error": str(exc)}
            self.result.emit(f"{label.strip() or 'touche'} : ok" if res.get("success")
                             else f"{res.get('error', 'echec')}")

        threading.Thread(target=work, daemon=True).start()

    def _show_result(self, text):
        self.status.setText(text)

    # --- affichage ---
    def place_left_of(self, other):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        x = max(screen.left(), other.x() - self.width() - 16)
        y = max(screen.top(), min(other.y() + other.height() - self.height(), screen.bottom() - self.height()))
        self.move(x, y)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
