"""Telecharge les donnees d'augmentation necessaires a l'entrainement du mot d'activation."""
import logging
import os
from pathlib import Path

import numpy as np
import scipy.io.wavfile
import urllib.request
from tqdm import tqdm

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("download_data")

HERE = Path(__file__).resolve().parent
RIR_DIR = HERE / "mit_rirs"
FMA_DIR = HERE / "background_clips"
VAL_FEATURES_PATH = HERE / "validation_set_features.npy"

RIR_DIR.mkdir(exist_ok=True)
FMA_DIR.mkdir(exist_ok=True)


def download_rirs():
    if any(RIR_DIR.iterdir()):
        log.info("RIRs deja presentes, on saute.")
        return
    import datasets
    log.info("Telechargement des reponses impulsionnelles MIT...")
    rir_dataset = datasets.load_dataset(
        "davidscripka/MIT_environmental_impulse_responses", split="train", streaming=True
    )
    for row in tqdm(rir_dataset):
        name = row["audio"]["path"].split("/")[-1]
        scipy.io.wavfile.write(
            str(RIR_DIR / name), 16000, (row["audio"]["array"] * 32767).astype(np.int16)
        )


def download_background_noise():
    if any(FMA_DIR.iterdir()):
        log.info("Bruits de fond deja presents, on saute.")
        return
    import zipfile
    import numpy as np

    log.info("Telechargement de bruits de fond environnementaux (ESC-50, ~600 Mo)...")
    zip_path = HERE / "esc50.zip"
    if not zip_path.exists():
        urllib.request.urlretrieve("https://github.com/karoldvl/ESC-50/archive/master.zip", str(zip_path))

    log.info("Extraction et conversion en 16kHz...")
    with zipfile.ZipFile(zip_path) as zf:
        wav_names = [n for n in zf.namelist() if n.endswith(".wav")]
        for name in tqdm(wav_names):
            with zf.open(name) as f:
                data = f.read()
            tmp_in = FMA_DIR / "_tmp_in.wav"
            tmp_in.write_bytes(data)
            try:
                import librosa
                y, sr = librosa.load(str(tmp_in), sr=16000, mono=True)
                out_name = Path(name).name
                scipy.io.wavfile.write(str(FMA_DIR / out_name), 16000, (y * 32767).astype(np.int16))
            except Exception as exc:
                log.warning("Skip %s: %s", name, exc)
    (FMA_DIR / "_tmp_in.wav").unlink(missing_ok=True)
    zip_path.unlink(missing_ok=True)


def download_validation_features():
    if VAL_FEATURES_PATH.exists():
        log.info("Fichier de validation deja present, on saute.")
        return
    log.info("Telechargement du jeu de validation openWakeWord (~185 Mo)...")
    url = "https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/validation_set_features.npy"
    urllib.request.urlretrieve(url, str(VAL_FEATURES_PATH))


if __name__ == "__main__":
    download_rirs()
    download_background_noise()
    download_validation_features()
    log.info("Termine.")
