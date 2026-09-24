#!/usr/bin/env python3
"""Point d'entree de Jarvis : lance l'interface graphique + le pipeline vocal."""
import logging
import queue
import re
import threading
import time
import sys
from pathlib import Path

import numpy as np

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

import clock
import config
import reminders
from audio_io import WakeWordListener, SpeechTranscriber, Speaker
from brain import JarvisBrain
from gui import JarvisWindow
from intent import register_remote_display, register_session_callback, register_voice_callback, try_fast_intent
from learning import Learner
from memory import Memory
from voice import VoiceProfiles, trim_speech
from remote_gui import RemoteWindow
from tools import dispatch_tool, register_reminder_callback, set_dispatch_hook
from tools.freebox_remote import register_action_callback as register_freebox_callback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.LOGS_DIR / "jarvis.log", encoding="utf-8"),
    ],
)
logging.Formatter.converter = staticmethod(clock.localtime)   # journaux en heure reelle
log = logging.getLogger("jarvis.main")

GREET_AFTER_SECONDS = 3 * 3600   # au-dela, le prochain appel est salue comme un nouveau reveil
ACTION_REQUEST = re.compile(
    r"\b(ouvre|ouvrir|lance|lancer|affiche|range|trie|organise|ferme|fermer|mets|met|baisse|monte|augmente|diminue|"
    r"[ée]teins|allume|coupe|verrouille|capture|prends une capture|cherche|recherche)\b|cha[iî]ne|volume|luminosit", re.I)
FOLLOW_UP_SECONDS = 10           # attente de la reponse apres une question de Jarvis


class AssistantWorker(QThread):
    state_changed = Signal(str)
    message_ready = Signal(str, str)  # role, text
    fatal_error = Signal(str)
    show_remote = Signal()
    hide_remote = Signal()
    notice = Signal(str)
    level = Signal(float)

    def __init__(self):
        super().__init__()
        self._stop = False
        self.text_queue = queue.Queue()
        self.listener = None
        self.transcriber = None
        self.speaker = None
        self.brain = None
        self.sleeping = False
        self.voice = None
        self.voice_paused = False
        self._pending_enroll = None
        self.last_speaker = None
        self.last_reply = ""
        self.last_activity = None   # dernier echange (None : rien depuis le demarrage)

    def submit_text(self, text: str):
        self.text_queue.put(text)

    def stop(self):
        self._stop = True

    def request_stop_speaking(self):
        """Bouton Stop du HUD : coupe la parole en cours."""
        if self.speaker:
            self.speaker.stop()

    def _on_session(self, kind: str):
        """« tais-toi » / « au revoir » : Jarvis se tait puis n'ecoute plus que l'appel net « Hey Jarvis »."""
        self.sleeping = True
        if kind == "stop":
            self.speaker.stop()

    @staticmethod
    def _speakable(text: str) -> str:
        """Le texte lu a voix haute : ni code, ni symboles markdown (ils restent affiches dans la fenetre)."""
        had_code = "```" in text
        text = re.sub(r"```.*?```", " ", text, flags=re.S)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"[*_#>]+", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text + (" Je t'ai mis le détail à l'écran." if had_code else "")

    def _speak(self, text: str) -> bool:
        """Lit `text` ; renvoie True si l'utilisateur a coupe la parole en appelant Jarvis."""
        text = self._speakable(text)
        done, barged = threading.Event(), []

        def watch():
            time.sleep(1.0)              # on ignore l'echo du debut de la phrase
            self.listener.flush()
            while not done.is_set():
                try:
                    if self.listener.poll_wakeword_once(0.1, threshold=config.BARGE_IN_THRESHOLD):
                        barged.append(True)
                        self.speaker.stop()
                        return
                except Exception:
                    return

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            self.speaker.say(text)
        finally:
            done.set()
            watcher.join(timeout=2)
        return bool(barged)

    def _init_components(self):
        log.info("Initialisation du pipeline audio (GPU=%s)...", config.GPU_AVAILABLE)
        self.listener = WakeWordListener()
        self.transcriber = SpeechTranscriber()
        self.speaker = Speaker()
        self.speaker.level_callback = self.level.emit
        self.brain = JarvisBrain()
        self.memory = Memory()
        self.memory.prune()
        self.learner = Learner(self.memory, dispatch_tool)
        set_dispatch_hook(self.learner.on_dispatch)
        self.brain.load_history(self.memory.recent_turns(6))
        self.due_reminders = queue.Queue()
        reminders.start(self.due_reminders.put)      # dit a voix haute quand l'heure est venue (voir run)
        register_session_callback(self._on_session)
        register_voice_callback(self._on_voice_command)
        self.voice = VoiceProfiles()
        self.learner.multi_speaker = len(self.voice.profiles) > 1
        if self.voice.enabled:
            self.voice._model()      # charge maintenant : pas de delai a la premiere commande
            log.info("Voix reconnues : %s", ", ".join(self.voice.names()))
        register_freebox_callback(self.show_remote.emit)
        register_remote_display(lambda visible: (self.show_remote if visible else self.hide_remote).emit())
        self.listener.start()
        log.info("Jarvis est pret.")

    def _announce_reminder(self, text: str):
        log.info("Rappel : %s", text)
        self.message_ready.emit("assistant", f"[Rappel] {text}")
        self.state_changed.emit("speaking")
        self._speak(text)
        self.listener.flush()
        self.state_changed.emit("sleeping" if self.sleeping else "idle")

    # ------------------------------------------------------------ reconnaissance de la voix
    def _verification_active(self) -> bool:
        return config.SPEAKER_VERIFICATION and self.voice and self.voice.enabled and not self.voice_paused

    def _on_voice_command(self, kind: str, arg):
        """Commandes vocales/ecrites de gestion des voix. Renvoie la phrase a dire."""
        if kind == "enroll":
            name = arg or self.memory.name() or "Propriétaire"
            self._pending_enroll = name
            return f"D'accord, on enregistre la voix de {name}."
        if kind == "enroll_who":
            return "À qui appartient cette voix ? Dis par exemple : enregistre la voix de Marie."
        if kind == "list":
            names = self.voice.names()
            if not names:
                return "Je n'ai encore enregistré aucune voix, donc je réponds à tout le monde."
            return "Je reconnais " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " et " + names[-1]) + "."
        if kind == "remove":
            if not self.voice.remove(arg):
                return f"Je ne connais pas de voix nommée {arg}."
            self.learner.multi_speaker = len(self.voice.profiles) > 1
            return (f"J'ai oublié la voix de {arg}." + ("" if self.voice.enabled else
                    " Il n'y a plus aucune voix enregistrée, je réponds de nouveau à tout le monde."))
        if kind == "pause":
            self.voice_paused = True
            return "Reconnaissance vocale désactivée : je réponds à toutes les voix jusqu'à ce que tu la réactives ou que je redémarre."
        if kind == "resume":
            self.voice_paused = False
            return "Reconnaissance vocale réactivée." if self.voice.enabled else \
                "C'est réactivé, mais je ne connais aucune voix pour l'instant. Dis « enregistre ma voix »."
        return "Je n'ai pas compris cette demande."

    def _run_enrollment(self, name: str):
        """Guide l'utilisateur : quelques phrases a repeter, puis calcul de l'empreinte de la voix."""
        phrases = config.ENROLL_PHRASES
        intro = (f"Je vais te donner {len(phrases)} phrases, une par une. Répète-les normalement, à ta distance "
                 "habituelle. Si la télé est allumée, baisse un peu le son.")
        self.message_ready.emit("assistant", intro)
        self.state_changed.emit("speaking")
        self.speaker.say(intro)
        samples = []
        for i, phrase in enumerate(phrases, 1):
            for attempt in range(3):
                prompt = f"Phrase {i} sur {len(phrases)}. Répète : {phrase}"
                self.message_ready.emit("assistant", prompt)
                self.state_changed.emit("speaking")
                self.speaker.say(prompt)
                self.listener.flush()
                self.state_changed.emit("listening")
                audio = self.listener.record_command(on_level=self.level.emit, max_seconds=15, silence_seconds=2.0)
                if trim_speech(audio).size >= 1.5 * config.SAMPLE_RATE:
                    samples.append(audio)
                    break
                self.state_changed.emit("speaking")
                self.speaker.say("C'était trop court ou trop discret, on la refait.")
            else:
                self.message_ready.emit("assistant", "Je n'arrive pas à t'entendre assez bien pour l'instant, on réessaiera.")
                self.speaker.say("Je n'arrive pas à t'entendre assez bien pour l'instant, on réessaiera plus tard.")
                self.state_changed.emit("idle")
                return
        self.state_changed.emit("thinking")
        profile = self.voice.enroll(name, samples)
        self.learner.multi_speaker = len(self.voice.profiles) > 1
        log.info("Voix enregistree : %s (seuil %.2f, coherence %.2f, min %.2f)", name, profile["threshold"],
                 profile["mean_intra"], profile["min_intra"])
        done = (f"C'est fait, j'ai enregistré la voix de {name}. Désormais je ne réponds plus qu'aux voix que je connais.")
        if profile["mean_intra"] < 0.5:
            done += " Attention, tes échantillons étaient assez variables : si je ne te reconnais pas bien, refais l'enregistrement dans un endroit plus calme."
        self.message_ready.emit("assistant", done)
        self.state_changed.emit("speaking")
        self.speaker.say(done)
        self.listener.flush()
        self.state_changed.emit("idle")

    def _pipeline(self, text: str):
        reply = try_fast_intent(text)
        if reply is not None:
            return reply, "direct"
        self.learner.turn_actions = []
        mark = len(self.brain.messages)
        slow = threading.Timer(5.0, lambda: self.notice.emit("Je réfléchis, un instant…"))
        slow.start()
        reply = self.brain.ask(text, self.learner.context())
        # Le petit modele annonce parfois une action sans avoir appele d'outil : on ne laisse pas passer ca.
        if not self.learner.turn_actions and ACTION_REQUEST.search(text):
            del self.brain.messages[mark:]
            log.info("Action demandee mais aucun outil appele : nouvelle tentative")
            reply = self.brain.ask(text + "\n(Exécute cette demande en appelant l'outil adapté, sans juste répondre.)",
                                   self.learner.context())
            if not self.learner.turn_actions:
                del self.brain.messages[mark:]      # la fausse promesse ne doit pas rester dans l'historique
                if re.search(r"cha[iî]ne|volume|\bson\b|t[ée]l[ée]|freebox|player|luminosit|zapp", text, re.I):
                    reply = ("Je n'ai pas réussi à faire ça, je n'ai pas bien compris. Tu peux reformuler ? "
                             "Par exemple « chaîne suivante » ou « mets M6 ».")
                else:
                    reply = "Je n'ai pas réussi à faire ça. Tu peux me le redire autrement ?"
        slow.cancel()
        return reply, "llm"

    def _handle_user_text(self, text: str):
        log.info("Commande: %s", text)
        self.message_ready.emit("user", text)
        self.state_changed.emit("thinking")
        self.sleeping = False            # tout message adresse a Jarvis le reveille
        reply = self.learner.respond(text, self._pipeline)
        log.info("Reponse: %s", reply or "(silence)")
        self.last_reply = reply or ""
        barged = False
        if reply:
            self.message_ready.emit("assistant", reply)
            self.state_changed.emit("speaking")
            barged = self._speak(reply)
        # Ce que le micro a entendu pendant qu'il parlait/reflechissait (sa voix, la tele) ne doit pas le reveiller.
        self.listener.flush()
        self.state_changed.emit("sleeping" if self.sleeping else "idle")
        self.last_activity = time.time()
        if self._pending_enroll:
            name, self._pending_enroll = self._pending_enroll, None
            self._run_enrollment(name)
            self.last_activity = time.time()
        if barged:
            self._handle_voice_command()   # l'utilisateur a repris la parole
        elif reply and not self.sleeping and self._expects_answer(reply):
            self._await_answer()           # Jarvis a pose une question : on attend la reponse

    def _needs_greeting(self, from_sleep: bool) -> bool:
        return from_sleep or self.last_activity is None or time.time() - self.last_activity > GREET_AFTER_SECONDS

    def _dump_debug_clip(self, wake_audio, audio, who, score) -> None:
        """Garde les 8 derniers enregistrements verifies (data/debug/, jamais versionne) pour comprendre les refus."""
        try:
            import wave
            folder = Path(__file__).resolve().parent / "data" / "debug"
            folder.mkdir(parents=True, exist_ok=True)
            for old in sorted(folder.glob("*.wav"))[:-15]:
                old.unlink()
            for tag, clip in (("wake", wake_audio), ("cmd", audio)):
                pcm = (np.clip(clip, -1, 1) * 32767).astype(np.int16)
                stamp = clock.now().strftime("%H%M%S")
                with wave.open(str(folder / f"{stamp}_{'ok' if who else 'refus'}{score:.2f}_{tag}.wav"), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(config.SAMPLE_RATE); w.writeframes(pcm.tobytes())
            log.info("Niveaux : wake rms=%.3f (%.1fs), commande rms=%.3f (%.1fs), ambiant=%.0f",
                     float(np.sqrt(np.mean(wake_audio ** 2))) if wake_audio.size else 0, wake_audio.size / config.SAMPLE_RATE,
                     float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0, audio.size / config.SAMPLE_RATE,
                     self.listener.ambient_level())
        except Exception:
            log.exception("Sauvegarde de debogage impossible")

    def _handle_voice_command(self, from_sleep: bool = False):
        log.info("Mot d'activation detecte (score %.2f)%s", self.listener.last_score,
                 " [reveil du sommeil]" if from_sleep else "")
        self.state_changed.emit("listening")
        wake_audio = self.listener.wake_audio()
        initial = None
        if self._needs_greeting(from_sleep):
            spoke, frames = self.listener.probe_speech(1.5)
            if spoke:
                initial = frames        # il enchaine sa commande : pas de salutation
            else:
                greeting = self.learner.greeting()
                log.info("Salutation: %s", greeting)
                self.message_ready.emit("assistant", greeting)
                self.state_changed.emit("speaking")
                self._speak(greeting)
                self.listener.flush()
                self.state_changed.emit("listening")
            self.last_activity = time.time()
        audio = self.listener.record_command(initial, on_level=self.level.emit)
        self._verify_and_handle(audio, wake_audio)

    def _verify_and_handle(self, audio, wake_audio, follow_up: bool = False) -> str:
        """Verifie la voix puis traite la commande. Renvoie 'traite', 'refuse' ou 'vide'.
        `follow_up` : reponse a une question de Jarvis (pas de « Hey Jarvis » avant, donc parfois tres courte)."""
        self.learner.speaker = None
        verified = False
        if self._verification_active():
            self.state_changed.emit("thinking")
            who, score, why = self.voice.identify(audio, wake_audio, relax=0.08 if follow_up else 0.0)
            self._dump_debug_clip(wake_audio, audio, who, score)
            if who is None and follow_up and why == "trop_court":
                # « oui », « non »... : trop court pour une empreinte fiable, on l'accepte seulement s'il reste bref.
                log.info("Reponse courte sans verification vocale (%.1f s de voix)", score)
                who = self.last_speaker
            elif who is None:
                # Voix inconnue (ou television) : on ne transcrit rien et on ne garde aucune trace.
                if why == "trop_court":
                    log.info("Voix non verifiable : phrase trop courte (%.1f s de voix)", score)
                    self.notice.emit("Trop court pour reconnaître ta voix")
                else:
                    log.info("Voix non reconnue (score %.2f) : ignoree", score)
                    self.notice.emit("Voix non reconnue")
                self.listener.flush()
                if not follow_up:
                    self.state_changed.emit("sleeping" if self.sleeping else "idle")
                return "refuse"
            else:
                verified = True
                log.info("Voix reconnue : %s (score %.2f)", who, score)
                self.last_speaker = who
            self.learner.speaker = who
        self.state_changed.emit("thinking")
        text = self.transcriber.transcribe(audio, self.last_reply if follow_up else "")
        if not text:
            if not follow_up:
                self.state_changed.emit("idle")
            return "vide"
        if follow_up and self._verification_active() and not verified and len(text.split()) > 4:
            log.info("Reponse longue non verifiee, ignoree : %s", text)
            self.listener.flush()
            return "refuse"
        self._handle_user_text(text)
        return "traite"

    @staticmethod
    def _expects_answer(reply: str) -> bool:
        return bool(reply) and reply.strip().rstrip(" \"'»”)*").endswith("?")

    def _await_answer(self):
        """Jarvis vient de poser une question : il ecoute la reponse sans exiger « Hey Jarvis »."""
        deadline = time.time() + FOLLOW_UP_SECONDS
        self.state_changed.emit("listening")
        self.notice.emit("Je t'écoute…")
        while time.time() < deadline and not self._stop and self.text_queue.empty():
            spoke, frames = self.listener.probe_speech(1.0)
            if not spoke:
                continue
            audio = self.listener.record_command(frames, on_level=self.level.emit)
            if self._verify_and_handle(audio, np.zeros(0, dtype=np.float32), follow_up=True) != "refuse":
                return
        self.state_changed.emit("sleeping" if self.sleeping else "idle")
        self.last_activity = time.time()

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
                self._announce_reminder(self.due_reminders.get_nowait())
                continue
            except queue.Empty:
                pass

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
                detected = self.listener.poll_wakeword_once(
                    timeout=0.2, threshold=config.WAKEWORD_THRESHOLD_SLEEP if self.sleeping else None)
            except Exception:
                log.exception("Erreur pendant l'ecoute du mot d'activation")
                continue

            if detected:
                from_sleep, self.sleeping = self.sleeping, False
                try:
                    self._handle_voice_command(from_sleep)
                except Exception:
                    log.exception("Erreur pendant le traitement de la commande vocale")
                    self.state_changed.emit("idle")

        if self.listener:
            self.listener.stop()


def main():
    config.LOGS_DIR.mkdir(exist_ok=True)
    clock.sync()                     # avant d'afficher quoi que ce soit
    clock.start_background_refresh()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    window = JarvisWindow()
    remote = RemoteWindow()
    worker = AssistantWorker()

    def open_remote():
        if not remote.isVisible():
            remote.place_left_of(window)
            remote.show()
        remote.raise_()

    worker.show_remote.connect(open_remote)
    worker.hide_remote.connect(remote.hide)
    worker.notice.connect(window.show_notice)
    worker.level.connect(window.set_level)
    window.remote_requested.connect(open_remote)

    worker.state_changed.connect(window.set_state)
    worker.message_ready.connect(window.append_message)
    worker.fatal_error.connect(lambda msg: window.set_state("error", f"Erreur : {msg}"))
    window.user_text_submitted.connect(worker.submit_text)
    window.stop_requested.connect(worker.request_stop_speaking)

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
