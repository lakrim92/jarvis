"""Entrees/sorties audio : detection du mot d'activation, enregistrement, transcription, synthese."""
import collections
import logging
import queue
import statistics
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from openwakeword.model import Model as WakeWordModel

import config

log = logging.getLogger("jarvis.audio")


class WakeWordListener:
    """Ecoute continue du micro et detection du mot 'Jarvis'."""

    def __init__(self):
        self.model = WakeWordModel(
            wakeword_models=[config.WAKEWORD_MODEL_NAME],
            inference_framework="onnx",
        )
        self._stream = None
        self._q = queue.Queue()
        self.last_score = 0.0
        self._levels = collections.deque(maxlen=60)   # niveaux recents (~5 s) : bruit ambiant

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.debug("Statut stream audio: %s", status)
        self._q.put(indata.copy())

    def start(self):
        self._stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=config.FRAME_SIZE,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._q.mutex:
            self._q.queue.clear()

    def flush(self) -> None:
        """Jette le son accumule (pendant que Jarvis parlait ou reflechissait) et remet le detecteur a zero."""
        with self._q.mutex:
            self._q.queue.clear()
        self._levels.clear()
        self.model.reset()

    def ambient_level(self) -> float:
        """Niveau median du son ambiant (television...) juste avant l'appel ; 0 si trop peu de mesures."""
        return statistics.median(self._levels) if len(self._levels) >= 10 else 0.0

    def poll_wakeword_once(self, timeout: float = 0.2, threshold: float = None) -> bool:
        """Lit un bloc audio (si disponible) et teste le mot d'activation. Non bloquant au-dela de `timeout`."""
        try:
            chunk = self._q.get(timeout=timeout)
        except queue.Empty:
            return False
        audio = chunk.reshape(-1)
        self._levels.append(float(np.sqrt(np.mean(audio.astype(np.float32) ** 2))))
        predictions = self.model.predict(audio)
        score = predictions.get(config.WAKEWORD_MODEL_NAME, 0.0)
        self.last_score = float(score)
        return score >= (config.WAKEWORD_THRESHOLD if threshold is None else threshold)

    def probe_speech(self, seconds: float = 1.5):
        """Ecoute `seconds` juste apres le mot d'activation. Renvoie (parole_detectee, blocs_audio_lus)."""
        with self._q.mutex:
            self._q.queue.clear()
        # Seuil relatif au bruit ambiant : avec la television allumee, un seuil fixe prendrait le fond sonore
        # pour de la parole. La voix de l'utilisateur, plus proche du micro, depasse nettement l'ambiant.
        limit = max(config.SILENCE_RMS_THRESHOLD, 2.5 * self.ambient_level())
        frames, loud_run = [], 0
        for _ in range(int(seconds * config.SAMPLE_RATE / config.FRAME_SIZE)):
            chunk = self._q.get()
            frames.append(chunk)
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
            loud_run = loud_run + 1 if rms >= limit else 0
            if loud_run >= 3:               # ~240 ms de voix : l'utilisateur enchaine sa commande
                return True, frames
        return False, frames

    def record_command(self, initial_frames=None, on_level=None) -> np.ndarray:
        """Enregistre la commande vocale apres le mot d'activation, s'arrete au silence.
        `initial_frames` : blocs deja lus par probe_speech (l'utilisateur parlait deja)."""
        frames = []
        pending = list(initial_frames) if initial_frames else []
        silence_frames_needed = int(
            config.SILENCE_DURATION_SECONDS * config.SAMPLE_RATE / config.FRAME_SIZE
        )
        max_frames = int(config.MAX_COMMAND_SECONDS * config.SAMPLE_RATE / config.FRAME_SIZE)

        silence_run = 0
        speech_started = False
        peak = 0.0          # niveau moyen le plus eleve observe (la voix)
        smoothed = 0.0
        if initial_frames is None:
            with self._q.mutex:
                self._q.queue.clear()

        for _ in range(max_frames):
            chunk = pending.pop(0) if pending else self._q.get()
            frames.append(chunk)
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
            if on_level:
                on_level(min(1.0, rms / 5000.0))
            smoothed = 0.5 * smoothed + 0.5 * rms
            peak = max(peak, smoothed)
            # Seuil relatif : avec un fond sonore constant (television), le niveau ne tombe jamais sous
            # un seuil fixe ; on considere la parole finie quand on redescend nettement sous le pic de la voix.
            threshold = max(config.SILENCE_RMS_THRESHOLD, 0.45 * peak)

            if smoothed >= max(config.SILENCE_RMS_THRESHOLD, 0.6 * peak):
                speech_started = True
                silence_run = 0
            elif speech_started and smoothed < threshold:
                silence_run += 1
                if silence_run >= silence_frames_needed:
                    break

        if not frames:
            return np.array([], dtype=np.float32)

        audio_int16 = np.concatenate(frames).reshape(-1)
        return audio_int16.astype(np.float32) / 32768.0


class SpeechTranscriber:
    """Transcription via faster-whisper."""

    def __init__(self):
        from faster_whisper import WhisperModel

        log.info("Chargement du modele Whisper (%s, %s)...", config.WHISPER_MODEL_SIZE, config.WHISPER_DEVICE)
        self.model = WhisperModel(
            config.WHISPER_MODEL_SIZE,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
        )

    def transcribe(self, audio_float32: np.ndarray) -> str:
        if audio_float32.size == 0:
            return ""
        segments, _ = self.model.transcribe(
            audio_float32,
            language=config.WHISPER_LANGUAGE,
            beam_size=5,
            vad_filter=True,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()


class Speaker:
    """Synthese vocale : Kokoro (voix neuronale) avec repli sur Piper."""

    def __init__(self):
        self._kokoro = None
        self._stop_speaking = False
        self.level_callback = None      # callback(niveau 0..1) pour animer l'interface pendant la parole
        if config.TTS_ENGINE == "kokoro":
            try:
                from kokoro_onnx import Kokoro

                self._kokoro = Kokoro(str(config.KOKORO_MODEL), str(config.KOKORO_VOICES))
                log.info("Voix Kokoro chargee (%s)", config.KOKORO_VOICE)
            except Exception:
                log.exception("Kokoro indisponible, repli sur Piper")
        self.voice_model = config.PIPER_VOICE_MODEL
        if self._kokoro is None and not self.voice_model.exists():
            raise FileNotFoundError(f"Voix Piper introuvable : {self.voice_model}")

    def stop(self) -> None:
        """Coupe la parole en cours immediatement (appelable depuis un autre thread)."""
        self._stop_speaking = True
        sd.stop()

    def say(self, text: str):
        if not text.strip():
            return
        self._stop_speaking = False
        if self._kokoro is not None:
            try:
                self._say_kokoro(text)
                return
            except Exception:
                log.exception("Erreur Kokoro, repli sur Piper pour cette phrase")
        self._say_piper(text)

    def _animate_level(self, samples, rate) -> None:
        """Envoie a l'interface l'enveloppe sonore de la phrase, synchronisee avec la lecture."""
        callback = self.level_callback
        if callback is None:
            return
        data = np.asarray(samples, dtype=np.float32)
        data = data.mean(axis=1) if data.ndim > 1 else data
        win = max(1, int(rate * 0.04))
        n = data.size // win
        if n == 0:
            return
        env = np.sqrt(np.mean(data[: n * win].reshape(n, win) ** 2, axis=1))
        env = np.clip(env / max(float(np.percentile(env, 95)), 1e-4), 0.0, 1.0)

        def run():
            start = time.time()
            for i, value in enumerate(env):
                if self._stop_speaking:
                    break
                time.sleep(max(0.0, start + i * 0.04 - time.time()))
                callback(float(value))
            callback(0.0)

        threading.Thread(target=run, daemon=True).start()

    def _say_kokoro(self, text: str):
        # Phrase par phrase : on synthetise la suivante pendant que la precedente est lue.
        sentences = [s for s in re.split(r"(?<=[.!?…:])\s+", text.strip()) if s.strip()]
        for sentence in sentences:
            samples, rate = self._kokoro.create(
                sentence, voice=config.KOKORO_VOICE, speed=config.KOKORO_SPEED, lang="fr-fr")
            sd.wait()
            if self._stop_speaking:
                return
            self._animate_level(samples, rate)
            sd.play(samples, rate)
        sd.wait()

    def _say_piper(self, text: str):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out_path = Path(tmp.name)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "piper", "-m", str(self.voice_model), "-f", str(out_path)],
                input=text, text=True, capture_output=True, timeout=60,
            )
            if proc.returncode != 0:
                log.error("Erreur Piper: %s", proc.stderr)
                return
            data, samplerate = _read_wav(out_path)
            self._animate_level(data, samplerate)
            sd.play(data, samplerate)
            sd.wait()
        finally:
            out_path.unlink(missing_ok=True)


def _read_wav(path: Path):
    import wave
    with wave.open(str(path), "rb") as wf:
        samplerate = wf.getframerate()
        n_channels = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        data = data.reshape(-1, n_channels)
    return data, samplerate
