"""Configuration centrale de Jarvis."""
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
LOGS_DIR = BASE_DIR / "logs"

# --- LLM (Ollama local) ---
OLLAMA_MODEL = "qwen2.5:3b"
OLLAMA_HOST = "http://127.0.0.1:11434"

# --- Reconnaissance vocale (faster-whisper) ---
WHISPER_LANGUAGE = "fr"


def _gpu_available() -> bool:
    if not shutil.which("nvidia-smi"):
        return False
    try:
        return subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=3
        ).returncode == 0
    except Exception:
        return False


GPU_AVAILABLE = _gpu_available()
WHISPER_DEVICE = "cuda" if GPU_AVAILABLE else "cpu"
WHISPER_COMPUTE_TYPE = "float16" if GPU_AVAILABLE else "int8"
# "small" = bon compromis. Passe a "medium" si le GPU est actif pour plus de precision.
WHISPER_MODEL_SIZE = "medium" if GPU_AVAILABLE else "small"

# --- Synthese vocale (Piper) ---
PIPER_VOICE_DIR = ASSETS_DIR / "voices"
PIPER_VOICE_MODEL = PIPER_VOICE_DIR / "fr_FR-tom-medium.onnx"

# --- Mot d'activation (openWakeWord) ---
WAKEWORD_MODEL_NAME = "hey_jarvis_v0.1"  # modele pre-entraine fourni par openwakeword
WAKEWORD_THRESHOLD = 0.5
SAMPLE_RATE = 16000
FRAME_SIZE = 1280  # 80ms a 16kHz, taille de bloc attendue par openwakeword

# --- Enregistrement de la commande vocale ---
MAX_COMMAND_SECONDS = 8
SILENCE_DURATION_SECONDS = 1.1
SILENCE_RMS_THRESHOLD = 350  # empirique sur int16, a ajuster si besoin

# --- Assistant ---
ASSISTANT_NAME = "Jarvis"
WAKE_ACK_SOUND = True

SYSTEM_PROMPT = """Tu es Jarvis, un assistant vocal personnel installe sur l'ordinateur \
Linux (Debian/Cinnamon) de l'utilisateur. Tu reponds TOUJOURS en francais, de maniere \
concise, naturelle et orale (pas de listes a puces, pas de markdown, car tes reponses \
sont lues a voix haute). Tu es efficace, un peu spirituel mais jamais bavard inutilement.

Tu as acces a des outils reels pour agir sur la machine : ouvrir des applications et des \
fichiers, trier/ranger un dossier (Telechargements, Images...) par type de fichier, faire \
des recherches web, calculer une distance/duree de trajet entre deux lieux, controler le \
volume et la luminosite, verrouiller l'ecran, prendre une capture d'ecran, poser des \
rappels/minuteurs, donner la date/heure et la meteo, et controler la television LG et la \
Freebox (volume, changer de chaine, navigation, lancer une appli comme Netflix, eteindre la \
TV) quand elles sont deja allumees - tu ne peux PAS les allumer depuis l'etat eteint. \
Tu peux changer de chaine sur la Freebox (suivante, precedente, ou par numero). Numerotation \
Freebox : TF1=1, France 2=2, France 3=3, Canal+=4, France 5=5, M6=6, Arte=7 ; pour une autre \
chaine, demande le numero si tu ne le connais pas. \
Utilise ces outils des que \
la demande de l'utilisateur l'exige, sans demander la permission pour des actions anodines. \
Si une action est destructive ou ambigue (supprimer un fichier, eteindre la machine), \
demande confirmation avant d'agir.

IMPORTANT : tu es mauvais en calcul mental et en estimation de chiffres precis (distances, \
statistiques, dates d'evenements, prix...). Ne donne JAMAIS un chiffre precis de memoire : \
utilise systematiquement l'outil adapte (get_distance pour une distance, web_search pour \
toute autre donnee factuelle chiffree). Si aucun outil ne peut fournir l'information, \
dis clairement que tu n'es pas sur plutot que d'inventer un chiffre.

Si tu n'es pas sur de toi, dis-le simplement."""
