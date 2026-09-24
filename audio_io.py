"""Entrees/sorties audio : detection du mot d'activation, enregistrement, transcription, synthese."""
import logging
import queue
import subprocess
import sys
import tempfile
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

    def poll_wakeword_once(self, timeout: float = 0.2) -> bool:
        """Lit un bloc audio (si disponible) et teste le mot d'activation. Non bloquant au-dela de `timeout`."""
        try:
            chunk = self._q.get(timeout=timeout)
        except queue.Empty:
            return False
        audio = chunk.reshape(-1)
        predictions = self.model.predict(audio)
        score = predictions.get(config.WAKEWORD_MODEL_NAME, 0.0)
        return score >= config.WAKEWORD_THRESHOLD

    def record_command(self) -> np.ndarray:
        """Enregistre la commande vocale apres le mot d'activation, s'arrete au silence."""
        frames = []
        silence_frames_needed = int(
            config.SILENCE_DURATION_SECONDS * config.SAMPLE_RATE / config.FRAME_SIZE
        )
        max_frames = int(config.MAX_COMMAND_SECONDS * config.SAMPLE_RATE / config.FRAME_SIZE)

        silence_run = 0
        speech_started = False
        peak = 0.0          # niveau moyen le plus eleve observe (la voix)
        smoothed = 0.0
        with self._q.mutex:
            self._q.queue.clear()

        for _ in range(max_frames):
            chunk = self._q.get()
            frames.append(chunk)
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
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
    """Synthese vocale via Piper (rendu WAV puis lecture)."""

    def __init__(self):
        self.voice_model = config.PIPER_VOICE_MODEL
        if not self.voice_model.exists():
            raise FileNotFoundError(f"Voix Piper introuvable : {self.voice_model}")

    def say(self, text: str):
        if not text.strip():
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out_path = Path(tmp.name)
        try:
            proc = subprocess.run(
                [
                    sys.executable, "-m", "piper",
                    "-m", str(self.voice_model),
                    "-f", str(out_path),
                ],
                input=text,
                text=True,
                capture_output=True,
                timeout=60,
            )
            if proc.returncode != 0:
                log.error("Erreur Piper: %s", proc.stderr)
                return
            data, samplerate = _read_wav(out_path)
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
