"""Reconnaissance du locuteur : Jarvis ne repond qu'aux voix enregistrees.

Une « empreinte vocale » (vecteur ECAPA-TDNN de 192 nombres, SpeechBrain, calcule en local sur le processeur)
est comparee a celles des voix enregistrees (cosinus). Les empreintes sont des donnees biometriques :
elles restent dans data/voices/ (jamais versionne).

Limite honnete : ce n'est pas une barriere de securite. Un enregistrement de ta voix ou une voix clonee peut
tromper le systeme, et une phrase tres courte ou noyee dans le bruit se verifie mal.
"""
import json
import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("jarvis.voice")

ROOT = Path(__file__).resolve().parent
PROFILES_DIR = ROOT / "data" / "voices"
MODEL_DIR = ROOT / "assets" / "spkrec-ecapa"
SAMPLE_RATE = 16000
MIN_SPEECH_SECONDS = 0.7       # en dessous, pas assez de voix pour verifier
THRESHOLD_MIN, THRESHOLD_MAX = 0.30, 0.50


def trim_speech(audio: np.ndarray) -> np.ndarray:
    """Garde uniquement la portion parlee (retire le silence de debut et de fin)."""
    if audio.size < SAMPLE_RATE // 4:
        return audio
    win = SAMPLE_RATE // 40                                    # fenetres de 25 ms
    n = audio.size // win
    rms = np.sqrt(np.mean(audio[: n * win].reshape(n, win) ** 2, axis=1))
    peak = np.percentile(rms, 95)
    if peak <= 1e-4:
        return audio[:0]
    active = np.where(rms > max(0.25 * peak, 1e-4))[0]
    return audio[active[0] * win: (active[-1] + 1) * win] if active.size else audio[:0]


class VoiceProfiles:
    def __init__(self):
        self._classifier = None
        self.profiles: dict = {}
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        self.reload()

    # ------------------------------------------------------------------ modele
    def _model(self):
        if self._classifier is None:
            import torch
            from speechbrain.inference.speaker import EncoderClassifier

            torch.set_num_threads(4)
            self._classifier = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb", savedir=str(MODEL_DIR), run_opts={"device": "cpu"})
            log.info("Modele de reconnaissance vocale charge")
        return self._classifier

    def embed(self, audio: np.ndarray) -> np.ndarray:
        import torch

        with torch.no_grad():
            emb = self._model().encode_batch(torch.from_numpy(audio.astype(np.float32))[None, :])
        vec = emb.squeeze().cpu().numpy()
        return vec / (np.linalg.norm(vec) + 1e-9)

    # ------------------------------------------------------------------ profils
    def reload(self) -> None:
        self.profiles = {}
        for f in sorted(PROFILES_DIR.glob("*.json")):
            try:
                d = json.loads(f.read_text())
                self.profiles[d["name"]] = {
                    "centroid": np.array(d["centroid"], dtype=np.float32),
                    "threshold": _threshold(d["mean_intra"]) if "mean_intra" in d else float(d["threshold"]),
                    "samples": d.get("samples", 0)}
            except Exception:
                log.exception("Profil vocal illisible : %s", f)

    @property
    def enabled(self) -> bool:
        return bool(self.profiles)

    def names(self) -> list:
        return sorted(self.profiles)

    def enroll(self, name: str, samples: list) -> dict:
        """Cree/remplace le profil `name` a partir de plusieurs enregistrements (audio float32 16 kHz)."""
        embs = [self.embed(trim_speech(s)) for s in samples]
        centroid = np.mean(embs, axis=0)
        centroid /= np.linalg.norm(centroid)
        # coherence de ta voix : chaque echantillon compare a la moyenne des AUTRES
        intra = []
        for i, e in enumerate(embs):
            others = np.mean([x for j, x in enumerate(embs) if j != i], axis=0)
            intra.append(float(np.dot(e, others / np.linalg.norm(others))))
        mean_intra = float(np.mean(intra))
        threshold = _threshold(mean_intra)
        data = {"name": name, "centroid": centroid.tolist(), "threshold": threshold, "samples": len(embs),
                "mean_intra": mean_intra, "min_intra": float(min(intra)), "ts": time.time()}
        (PROFILES_DIR / f"{_slug(name)}.json").write_text(json.dumps(data))
        self.reload()
        return data

    def remove(self, name: str) -> bool:
        path = PROFILES_DIR / f"{_slug(name)}.json"
        existed = path.exists()
        path.unlink(missing_ok=True)
        self.reload()
        return existed

    # ------------------------------------------------------------------ verification
    def identify(self, audio: np.ndarray, wake_audio: Optional[np.ndarray] = None, relax: float = 0.0):
        """Renvoie (nom | None, meilleur_score, raison). raison : 'ok', 'trop_court' ou 'inconnue'.
        `wake_audio` : le « Hey Jarvis » lui-meme, ajoute a la commande (les commandes tres courtes,
        comme « quelle heure ? », ne contiennent pas assez de voix a elles seules).
        `relax` : tolerance sur le seuil (reponse a une question de Jarvis : sans « Hey Jarvis », donc moins de voix)."""
        speech = trim_speech(audio)
        if wake_audio is not None and wake_audio.size:
            speech = np.concatenate([trim_speech(wake_audio), speech])
        if speech.size < MIN_SPEECH_SECONDS * SAMPLE_RATE:
            return None, speech.size / SAMPLE_RATE, "trop_court"
        emb = self.embed(speech)
        best_name, best_score, best_margin = None, -1.0, -1.0
        for name, prof in self.profiles.items():
            score = float(np.dot(emb, prof["centroid"]))
            if score - (prof["threshold"] - relax) > best_margin:
                best_name, best_score, best_margin = name, score, score - (prof["threshold"] - relax)
        if best_name is not None and best_margin >= 0:
            return best_name, best_score, "ok"
        return None, max(best_score, 0.0), "inconnue"


def _threshold(mean_intra: float) -> float:
    """Seuil de reconnaissance : la moitie de la coherence de la voix enregistree (voix etrangeres : ~0,0-0,3)."""
    return float(np.clip(0.5 * mean_intra, THRESHOLD_MIN, THRESHOLD_MAX))


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_") or "voix"
