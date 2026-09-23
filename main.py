#!/usr/bin/env python3
"""Point d'entree de Jarvis : lance l'interface graphique + le pipeline vocal."""
import logging
import queue
import sys

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

import config
from audio_io import WakeWordListener, SpeechTranscriber, Speaker
from brain import JarvisBrain
from gui import JarvisWindow
from tools import register_reminder_callback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.LOGS_DIR / "jarvis.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("jarvis.main")


class AssistantWorker(QThread):
    state_changed = Signal(str)
    message_ready = Signal(str, str)  # role, text
    fatal_error = Signal(str)

    def __init__(self):
        super().__init__()
        self._stop = False
        self.text_queue = queue.Queue()
        self.listener = None
        self.transcriber = None
        self.speaker = None
        self.brain = None

    def submit_text(self, text: str):
        self.text_queue.put(text)

    def stop(self):
        self._stop = True

    def _init_components(self):
        log.info("Initialisation du pipeline audio (GPU=%s)...", config.GPU_AVAILABLE)
        self.listener = WakeWordListener()
        self.transcriber = SpeechTranscriber()
        self.speaker = Speaker()
        self.brain = JarvisBrain()
        register_reminder_callback(self._on_reminder)
        self.listener.start()
        log.info("Jarvis est pret.")

    def _on_reminder(self, message: str):
        self.message_ready.emit("assistant", f"[Rappel] {message}")
        self.state_changed.emit("speaking")
        self.speaker.say(f"Rappel : {message}")
        self.state_changed.emit("idle")

    def _handle_user_text(self, text: str):
        self.message_ready.emit("user", text)
        self.state_changed.emit("thinking")
        reply = self.brain.ask(text)
        self.message_ready.emit("assistant", reply)
        self.state_changed.emit("speaking")
        self.speaker.say(reply)
        self.state_changed.emit("idle")

    def _handle_voice_command(self):
        self.state_changed.emit("listening")
        audio = self.listener.record_command()
        self.state_changed.emit("thinking")
        text = self.transcriber.transcribe(audio)
        if not text:
            self.state_changed.emit("idle")
            return
        self._handle_user_text(text)

    def run(self):
        try:
            self._init_components()
        except Exception as exc:
            log.exception("Erreur d'initialisation")
            self.fatal_error.emit(str(exc))
            return

        self.state_changed.emit("idle")
        while not self._stop:
            try:
                typed = self.text_queue.get_nowait()
            except queue.Empty:
                typed = None

            if typed:
                try:
                    self._handle_user_text(typed)
                except Exception:
                    log.exception("Erreur pendant le traitement de la commande texte")
                    self.state_changed.emit("idle")
                continue

            try:
                detected = self.listener.poll_wakeword_once(timeout=0.2)
            except Exception:
                log.exception("Erreur pendant l'ecoute du mot d'activation")
                continue

            if detected:
                try:
                    self._handle_voice_command()
                except Exception:
                    log.exception("Erreur pendant le traitement de la commande vocale")
                    self.state_changed.emit("idle")

        if self.listener:
            self.listener.stop()


def main():
    config.LOGS_DIR.mkdir(exist_ok=True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    window = JarvisWindow()
    worker = AssistantWorker()

    worker.state_changed.connect(window.set_state)
    worker.message_ready.connect(window.append_message)
    worker.fatal_error.connect(lambda msg: window.set_state("error", f"Erreur : {msg}"))
    window.user_text_submitted.connect(worker.submit_text)

    def on_quit():
        worker.stop()
        worker.wait(3000)
        app.quit()

    window.quit_requested.connect(on_quit)

    window.show()
    worker.start()

    exit_code = app.exec()
    worker.stop()
    worker.wait(3000)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
