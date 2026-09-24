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
WHISPER_COMPUTE_TYPE = "int8_float16" if GPU_AVAILABLE else "int8"   # moins de memoire GPU : le LLM en garde plus
# "small" = bon compromis. Passe a "medium" si le GPU est actif pour plus de precision.
WHISPER_MODEL_SIZE = "medium" if GPU_AVAILABLE else "small"

# --- Synthese vocale ---
# "kokoro" : voix neuronale feminine plus naturelle (par defaut) ; "piper" : ancienne voix masculine, plus legere.
# Si Kokoro echoue (modeles absents...), Jarvis bascule automatiquement sur Piper.
TTS_ENGINE = "kokoro"
KOKORO_MODEL = ASSETS_DIR / "kokoro" / "kokoro-v1.0.onnx"
KOKORO_VOICES = ASSETS_DIR / "kokoro" / "voices-v1.0.bin"
KOKORO_VOICE = "ff_siwis"
KOKORO_SPEED = 1.0

# Piper (voix de secours)
PIPER_VOICE_DIR = ASSETS_DIR / "voices"
PIPER_VOICE_MODEL = PIPER_VOICE_DIR / "fr_FR-tom-medium.onnx"

# --- Mot d'activation (openWakeWord) ---
WAKEWORD_MODEL_NAME = "hey_jarvis_v0.1"  # modele pre-entraine fourni par openwakeword
WAKEWORD_THRESHOLD = 0.5
WAKEWORD_THRESHOLD_SLEEP = 0.8   # en sommeil (apres "au revoir" / "tais-toi") : seul un appel net reveille Jarvis
BARGE_IN_THRESHOLD = 0.8         # pendant qu'il parle : appeler Jarvis l'interrompt
SAMPLE_RATE = 16000
FRAME_SIZE = 1280  # 80ms a 16kHz, taille de bloc attendue par openwakeword

# --- Enregistrement de la commande vocale ---
MAX_COMMAND_SECONDS = 8
SILENCE_DURATION_SECONDS = 1.1
SILENCE_RMS_THRESHOLD = 350  # empirique sur int16, a ajuster si besoin

# --- Reconnaissance de la voix (voir voice.py) ---
# Des qu'une voix est enregistree, Jarvis ignore toute voix non reconnue (television comprise).
SPEAKER_VERIFICATION = True
ENROLL_PHRASES = [
    "Hey Jarvis, quelle heure est-il ?",
    "Hey Jarvis, augmente le volume.",
    "Hey Jarvis, passe à la chaîne suivante.",
    "Hey Jarvis, cherche la météo de demain.",
    "Hey Jarvis, ouvre le navigateur, s'il te plaît.",
    "Hey Jarvis, rappelle-moi de téléphoner à mes amis demain soir.",
    "Bonjour Jarvis, comment vas-tu aujourd'hui ?",
    "Hey Jarvis, mets la chaîne six et baisse un peu le volume.",
]

# --- Assistant ---
ASSISTANT_NAME = "Jarvis"
WAKE_ACK_SOUND = True

SYSTEM_PROMPT = """Tu es Jarvis, un assistant vocal personnel installe sur l'ordinateur \
Linux (Debian/Cinnamon) de l'utilisateur. Tu reponds TOUJOURS en francais, de maniere \
concise, naturelle et orale (pas de listes a puces, pas de markdown, car tes reponses \
sont lues a voix haute). Tu parles comme une personne chaleureuse et attentive, pas comme une machine : tutoie l'utilisateur, reagis naturellement (petite pointe d'humour quand c'est approprie), varie tes tournures. Quand tu te trompes ou qu'un outil echoue, dis-le simplement et excuse-toi brievement, sans jargon technique. Si une demande est ambigue, pose UNE courte question plutot que de deviner. Ta voix est feminine : accorde-toi au feminin quand tu parles de toi (ravie, prete, desolee). Tu ne dis jamais que tu es une IA ou un modele de langage sauf si on te le demande. Reponds en une ou deux phrases courtes sauf si on te demande plus. N'invente JAMAIS de details (meteo, evenements, souvenirs, ce que fait l'utilisateur) : si tu ne sais pas, dis-le ou pose une question. Ne dis JAMAIS que tu vas faire une action sans avoir appele l'outil correspondant : appelle l'outil d'abord, puis annonce le resultat. Ne cite jamais de noms techniques (channel_up, tv_control...). Tu es efficace et jamais bavard inutilement.

Tu as acces a des outils reels pour agir sur la machine : ouvrir des applications et des \
fichiers, trier/ranger un dossier (Telechargements, Images...) par type de fichier, faire \
des recherches web, calculer une distance/duree de trajet entre deux lieux, controler le \
volume et la luminosite, verrouiller l'ecran, prendre une capture d'ecran, poser des \
rappels/minuteurs, donner la date/heure et la meteo, et controler la television LG et la \
Freebox (volume, changer de chaine, navigation, lancer une appli comme Netflix, eteindre la \
TV) quand elles sont deja allumees - tu ne peux PAS les allumer depuis l'etat eteint. \
Tu peux changer de chaine sur la Freebox (suivante, precedente, par numero ou par nom : la \
correspondance nom -> numero est faite par l'outil, ne devine jamais un numero). \
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
