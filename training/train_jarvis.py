"""Entraine un modele openWakeWord custom pour detecter uniquement 'jarvis' (prononciation francaise)."""
import logging
import os
import sys
import uuid
from pathlib import Path

import numpy as np
import scipy.io.wavfile
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "piper-sample-generator"))

from piper_sample_generator.__main__ import generate_samples  # noqa: E402

import openwakeword  # noqa: E402
from openwakeword.data import generate_adversarial_texts, augment_clips  # noqa: E402
from openwakeword.utils import compute_features_from_generator, AudioFeatures  # noqa: E402
from openwakeword.train import Model  # noqa: E402

logging.basicConfig(level=logging.INFO)
logging.getLogger().setLevel(logging.INFO)  # piper_sample_generator forces root to DEBUG on import
log = logging.getLogger("train_jarvis")
log.setLevel(logging.INFO)

# --- Configuration ---
MODEL_NAME = "jarvis"
TARGET_PHRASE = "jarvis"
TTS_MODEL = str(HERE / "piper-sample-generator" / "models" / "fr_FR-mls-medium.pt")

N_SAMPLES_TRAIN = 12000
N_SAMPLES_VAL = 1500
TTS_BATCH_SIZE = 16

OUTPUT_DIR = HERE / "output"
MODEL_DIR = OUTPUT_DIR / MODEL_NAME
POS_TRAIN_DIR = MODEL_DIR / "positive_train"
POS_TEST_DIR = MODEL_DIR / "positive_test"
NEG_TRAIN_DIR = MODEL_DIR / "negative_train"
NEG_TEST_DIR = MODEL_DIR / "negative_test"

RIR_DIR = HERE / "mit_rirs"
BACKGROUND_DIR = HERE / "background_clips"
VAL_FEATURES_PATH = HERE / "validation_set_features.npy"

STEPS = 40000
MAX_NEGATIVE_WEIGHT = 150
TARGET_FP_PER_HOUR = 0.2


def ensure_dirs():
    for d in [OUTPUT_DIR, MODEL_DIR, POS_TRAIN_DIR, POS_TEST_DIR, NEG_TRAIN_DIR, NEG_TEST_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def generate_clips():
    log.info("### Generation des clips positifs (train) ###")
    n_existing = len(list(POS_TRAIN_DIR.glob("*.wav")))
    if n_existing < 0.95 * N_SAMPLES_TRAIN:
        generate_samples(
            text=[TARGET_PHRASE],
            output_dir=str(POS_TRAIN_DIR),
            model=TTS_MODEL,
            max_samples=N_SAMPLES_TRAIN - n_existing,
            batch_size=TTS_BATCH_SIZE,
            noise_scales=(0.98,),
            noise_scale_ws=(0.98,),
            length_scales=(0.75, 1.0, 1.25),
            file_names=[uuid.uuid4().hex + ".wav" for _ in range(N_SAMPLES_TRAIN - n_existing)],
        )
        torch.cuda.empty_cache()
    else:
        log.info("Deja assez de clips positifs (train), on saute.")

    log.info("### Generation des clips positifs (test) ###")
    n_existing = len(list(POS_TEST_DIR.glob("*.wav")))
    if n_existing < 0.95 * N_SAMPLES_VAL:
        generate_samples(
            text=[TARGET_PHRASE],
            output_dir=str(POS_TEST_DIR),
            model=TTS_MODEL,
            max_samples=N_SAMPLES_VAL - n_existing,
            batch_size=TTS_BATCH_SIZE,
            noise_scales=(1.0,),
            noise_scale_ws=(1.0,),
            length_scales=(0.75, 1.0, 1.25),
            file_names=[uuid.uuid4().hex + ".wav" for _ in range(N_SAMPLES_VAL - n_existing)],
        )
        torch.cuda.empty_cache()
    else:
        log.info("Deja assez de clips positifs (test), on saute.")

    log.info("### Generation des clips negatifs adversariaux (train) ###")
    n_existing = len(list(NEG_TRAIN_DIR.glob("*.wav")))
    if n_existing < 0.95 * N_SAMPLES_TRAIN:
        adversarial_texts = generate_adversarial_texts(
            input_text=TARGET_PHRASE,
            N=N_SAMPLES_TRAIN,
            include_partial_phrase=1.0,
            include_input_words=0.2,
        )
        generate_samples(
            text=adversarial_texts,
            output_dir=str(NEG_TRAIN_DIR),
            model=TTS_MODEL,
            max_samples=N_SAMPLES_TRAIN - n_existing,
            batch_size=max(1, TTS_BATCH_SIZE // 7),
            noise_scales=(0.98,),
            noise_scale_ws=(0.98,),
            length_scales=(0.75, 1.0, 1.25),
            file_names=[uuid.uuid4().hex + ".wav" for _ in range(N_SAMPLES_TRAIN - n_existing)],
        )
        torch.cuda.empty_cache()
    else:
        log.info("Deja assez de clips negatifs (train), on saute.")

    log.info("### Generation des clips negatifs adversariaux (test) ###")
    n_existing = len(list(NEG_TEST_DIR.glob("*.wav")))
    if n_existing < 0.95 * N_SAMPLES_VAL:
        adversarial_texts = generate_adversarial_texts(
            input_text=TARGET_PHRASE,
            N=N_SAMPLES_VAL,
            include_partial_phrase=1.0,
            include_input_words=0.2,
        )
        generate_samples(
            text=adversarial_texts,
            output_dir=str(NEG_TEST_DIR),
            model=TTS_MODEL,
            max_samples=N_SAMPLES_VAL - n_existing,
            batch_size=max(1, TTS_BATCH_SIZE // 7),
            noise_scales=(1.0,),
            noise_scale_ws=(1.0,),
            length_scales=(0.75, 1.0, 1.25),
            file_names=[uuid.uuid4().hex + ".wav" for _ in range(N_SAMPLES_VAL - n_existing)],
        )
        torch.cuda.empty_cache()
    else:
        log.info("Deja assez de clips negatifs (test), on saute.")


def resample_clips_to_16k():
    import librosa
    for d in [POS_TRAIN_DIR, POS_TEST_DIR, NEG_TRAIN_DIR, NEG_TEST_DIR]:
        wavs = list(d.glob("*.wav"))
        to_fix = []
        for w in wavs:
            sr, _ = scipy.io.wavfile.read(str(w))
            if sr != 16000:
                to_fix.append(w)
        if not to_fix:
            log.info("%s deja en 16kHz (%d clips).", d.name, len(wavs))
            continue
        log.info("Reechantillonnage de %d/%d clips dans %s vers 16kHz...", len(to_fix), len(wavs), d.name)
        for w in to_fix:
            y, _ = librosa.load(str(w), sr=16000, mono=True)
            scipy.io.wavfile.write(str(w), 16000, (y * 32767).astype(np.int16))


def compute_total_length():
    positive_clips = list(POS_TEST_DIR.glob("*.wav"))
    durations = []
    for i in range(min(50, len(positive_clips))):
        sr, dat = scipy.io.wavfile.read(str(positive_clips[np.random.randint(0, len(positive_clips))]))
        durations.append(len(dat))
    total_length = int(round(np.median(durations) / 1000) * 1000) + 12000
    if total_length < 32000:
        total_length = 32000
    elif abs(total_length - 32000) <= 4000:
        total_length = 32000
    log.info("total_length (echantillons) = %d (%.2fs)", total_length, total_length / 16000)
    return total_length


def augment_and_featurize(total_length):
    rir_paths = [str(p) for p in RIR_DIR.iterdir()]
    background_paths = [str(p) for p in BACKGROUND_DIR.iterdir()]
    log.info("RIRs: %d, bruits de fond: %d", len(rir_paths), len(background_paths))

    def gen(paths):
        return augment_clips(
            paths, total_length=total_length, batch_size=16,
            background_clip_paths=background_paths, RIR_paths=rir_paths,
        )

    targets = [
        (POS_TRAIN_DIR, "positive_features_train.npy"),
        (POS_TEST_DIR, "positive_features_test.npy"),
        (NEG_TRAIN_DIR, "negative_features_train.npy"),
        (NEG_TEST_DIR, "negative_features_test.npy"),
    ]
    for clip_dir, out_name in targets:
        out_path = MODEL_DIR / out_name
        if out_path.exists():
            log.info("%s existe deja, on saute.", out_name)
            continue
        clips = [str(p) for p in clip_dir.glob("*.wav")]
        log.info("Calcul des features pour %s (%d clips) -> %s", clip_dir.name, len(clips), out_name)
        compute_features_from_generator(
            gen(clips), n_total=len(clips), clip_duration=total_length,
            output_file=str(out_path),
            device="gpu" if torch.cuda.is_available() else "cpu",
            ncpu=1,
        )


def train(total_length):
    # Derive the real per-clip frame count from the computed features themselves,
    # rather than from total_length // 16000 (integer division truncates non-round
    # durations like 2.75s -> 2s, causing a shape mismatch with the actual features).
    sample_features = np.load(str(MODEL_DIR / "positive_features_train.npy"))
    input_shape = sample_features.shape[1:]
    log.info("input_shape derive des features calculees : %s", input_shape)

    oww = Model(
        n_classes=1, input_shape=input_shape, model_type="dnn",
        layer_dim=32, seconds_per_example=1280 * input_shape[0] / 16000,
    )

    feature_data_files = {
        "positive": str(MODEL_DIR / "positive_features_train.npy"),
        "adversarial_negative": str(MODEL_DIR / "negative_features_train.npy"),
    }
    batch_n_per_class = {"positive": 512, "adversarial_negative": 512}

    label_transforms = {
        "positive": lambda x: [1 for _ in x],
        "adversarial_negative": lambda x: [0 for _ in x],
    }

    from openwakeword.data import mmap_batch_generator

    batch_generator = mmap_batch_generator(
        feature_data_files, n_per_class=batch_n_per_class,
        data_transform_funcs={}, label_transform_funcs=label_transforms,
    )

    class IterDataset(torch.utils.data.IterableDataset):
        def __init__(self, generator):
            self.generator = generator

        def __iter__(self):
            return self.generator

    X_train = torch.utils.data.DataLoader(IterDataset(batch_generator), batch_size=None, num_workers=2, prefetch_factor=16)

    X_val_fp = np.load(str(VAL_FEATURES_PATH))
    # Le fichier complet (11h+) genere une matrice de fenetres glissantes de plusieurs Go
    # une fois deplie (une fenetre par frame), ce qui epuise la RAM/VRAM de cette machine.
    # On se limite a un sous-ensemble (~1h) largement suffisant pour un modele mono-utilisateur.
    MAX_VAL_FP_FRAMES = 60000
    if X_val_fp.shape[0] > MAX_VAL_FP_FRAMES:
        X_val_fp = X_val_fp[:MAX_VAL_FP_FRAMES]
    X_val_fp = np.array([X_val_fp[i:i + input_shape[0]] for i in range(0, X_val_fp.shape[0] - input_shape[0], 1)])
    X_val_fp_labels = np.zeros(X_val_fp.shape[0]).astype(np.float32)
    X_val_fp_loader = torch.utils.data.DataLoader(
        torch.utils.data.TensorDataset(torch.from_numpy(X_val_fp), torch.from_numpy(X_val_fp_labels)),
        batch_size=4096,
    )

    X_val_pos = np.load(str(MODEL_DIR / "positive_features_test.npy"))
    X_val_neg = np.load(str(MODEL_DIR / "negative_features_test.npy"))
    labels = np.hstack((np.ones(X_val_pos.shape[0]), np.zeros(X_val_neg.shape[0]))).astype(np.float32)
    X_val_loader = torch.utils.data.DataLoader(
        torch.utils.data.TensorDataset(
            torch.from_numpy(np.vstack((X_val_pos, X_val_neg))), torch.from_numpy(labels)
        ),
        batch_size=len(labels),
    )

    log.info("### Debut de l'entrainement (auto_train, %d steps max) ###", STEPS)
    merged_model = oww.auto_train(
        X_train=X_train,
        X_val=X_val_loader,
        false_positive_val_data=X_val_fp_loader,
        steps=STEPS,
        max_negative_weight=MAX_NEGATIVE_WEIGHT,
        target_fp_per_hour=TARGET_FP_PER_HOUR,
    )

    log.info("### Checkpoints individuels (avant fusion) ###")
    for i, score in enumerate(oww.best_model_scores):
        log.info("checkpoint %d: %s", i, score)

    # La fusion (moyenne) des checkpoints du 90e percentile peut degrader le resultat
    # quand les checkpoints proviennent de phases avec des poids negatifs tres differents.
    # On choisit le meilleur checkpoint individuel (meilleur recall a fp/hr raisonnable)
    # et on exporte les deux pour comparaison pratique.
    best_individual_idx = max(
        range(len(oww.best_model_scores)),
        key=lambda i: oww.best_model_scores[i]["val_accuracy"] - 0.01 * oww.best_model_scores[i]["val_fp_per_hr"],
    )
    best_individual_model = oww.best_models[best_individual_idx]
    log.info("Meilleur checkpoint individuel: %s", oww.best_model_scores[best_individual_idx])

    oww.export_model(model=merged_model, model_name=MODEL_NAME + "_merged", output_dir=str(OUTPUT_DIR))
    oww.export_model(model=best_individual_model, model_name=MODEL_NAME + "_best", output_dir=str(OUTPUT_DIR))
    log.info("Modeles exportes : %s_merged.onnx et %s_best.onnx", MODEL_NAME, MODEL_NAME)


if __name__ == "__main__":
    ensure_dirs()
    generate_clips()
    resample_clips_to_16k()
    total_length = compute_total_length()
    augment_and_featurize(total_length)
    train(total_length)
    log.info("TERMINE")
