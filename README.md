# Jarvis — assistant vocal personnel local

Assistant 100% local (aucune donnée envoyée à un tiers) : LLM via Ollama,
reconnaissance vocale via faster-whisper, synthèse vocale via Piper,
détection du mot d'activation "Hey Jarvis" via openWakeWord, interface HUD via PySide6.

## Installation (une seule fois)

1. **Dépendances système + driver NVIDIA + Ollama** (nécessite ton mot de passe sudo) :
   ```
   sudo bash setup/install_system.sh
   sudo reboot
   ```
   Au redémarrage, un écran bleu "MOK Management" peut apparaître (Secure Boot) :
   choisis **Enroll MOK → Continue → Yes** et entre le mot de passe défini pendant
   l'installation. Si le driver ne charge toujours pas après reboot (`nvidia-smi`
   échoue), la clé DKMS n'a peut-être pas été enrôlée automatiquement :
   `sudo mokutil --import /var/lib/dkms/mok.pub` puis reboot.

2. **Télécharger le modèle de langage** (après qu'Ollama soit installé) :
   ```
   ollama pull qwen2.5:3b
   ```

3. Les dépendances Python sont déjà installées dans `venv/`, et les modèles
   vocaux (mot d'activation + voix française) sont déjà téléchargés dans `assets/`.

## Lancer Jarvis

```
./run.sh
```
Ou depuis le menu des applications : cherche **"Jarvis"**.

## Heure réelle

L'horloge du PC peut être fausse (ici : 2 h d'avance, sans synchronisation NTP). Jarvis mesure donc l'écart avec
des serveurs de temps (NTP, sinon en-tête HTTPS), le rafraîchit toutes les 30 min et l'applique partout :
interface, « quelle heure est-il / quel jour sommes-nous » (réponse directe), salutation, rappels et journaux
(`clock.py`, fuseau Europe/Paris). Sans internet, il retombe sur l'horloge du PC.

## Interface

HUD holographique animé dans l'esprit du film, dessiné entièrement en code (aucune image protégée) :
anneaux concentriques tournants, graduations, halo. Le cœur change de couleur selon l'état (cyan : en ligne /
écoute, ambre : analyse, blanc-cyan : parole, bleu terne : veille) et **réagit au son** : à ta voix pendant
l'écoute et à celle de Jarvis pendant qu'il parle. Boutons STOP (coupe la parole), TÉLÉCOMMANDE et ✕ ;
fenêtre déplaçable à la souris.

## Utilisation

- Dis **"Hey Jarvis"** (prononciation à l'anglaise) pour l'activer, puis parle
  ta demande.
- Ou tape directement dans le champ texte en bas de la fenêtre.
- La fenêtre (coin bas-droit de l'écran) est déplaçable à la souris.
- Le cercle change de couleur : gris = veille, cyan = écoute, violet = réflexion,
  vert = réponse.

## Ce que Jarvis sait faire

- Discuter (mémoire de la conversation en cours)
- Ouvrir des applications (`ouvre firefox`, `lance gimp`...)
- Ouvrir des fichiers/dossiers (`ouvre le fichier rapport.pdf`)
- Trier/ranger un dossier en vrac par type de fichier (`trie mon dossier Téléchargements`)
- Rechercher sur le web et résumer les résultats
- Calculer une distance/durée de trajet réelle entre deux lieux
- Donner la météo, la date/l'heure
- Contrôler le volume et la luminosité
- Verrouiller l'écran, prendre une capture d'écran (`~/Pictures/Jarvis/`)
- Poser des rappels/minuteurs vocaux
- Piloter la télé LG webOS (volume, applis, extinction) et la Freebox Player (chaînes, volume,
  navigation) avec une télécommande virtuelle cliquable qui s'affiche à l'écran
  (`ferme la télécommande` / `affiche la télécommande`)

Les commandes courantes (volume, son, chaînes) sont traitées directement, sans passer par le modèle
(`intent.py`) : c'est instantané. Le volume vise par défaut le Player ; dis « télé » ou « ordinateur »
pour viser la télé LG ou le PC.

## Télé LG et Freebox Player (à faire une fois)

Les identifiants sont stockés dans `.secrets/` (jamais versionné).

- **Freebox Player** : dans les réglages du Player, active « clavier virtuel à distance »
  (ouvre le protocole Android TV Remote), puis `python setup/pair_freebox_remote.py <ip_du_player>` :
  écris le code à 6 caractères affiché sur la télé dans `/tmp/atv_pin`. Le bouton d'alimentation est
  volontairement bloqué (éteint, le Player n'est plus joignable et ne peut pas être rallumé à distance).
- **Télé LG webOS** : appairage via `aiowebostv` (accepter la demande affichée sur la télé), le jeton
  est enregistré dans `.secrets/lg_tv_token.json` (`{"host": ..., "client_key": ...}`).
- Limite : ni la télé ni la Freebox ne peuvent être allumées depuis l'état éteint.

## Reconnaissance de ta voix

Jarvis peut ne répondre qu'aux voix enregistrées (la télé et les inconnus sont ignorés en silence :
rien n'est transcrit ni gardé). Tant qu'aucune voix n'est enregistrée, il répond à tout le monde.

- `enregistre ma voix` : il te fait répéter 6 phrases (dans un endroit calme, télé baissée), calcule ton
  empreinte vocale et fixe un seuil adapté à ta voix.
- `enregistre la voix de Marie` : ajoute une autre voix (Marie répète les phrases). `quelles voix connais-tu ?`,
  `supprime la voix de Marie`, `mets à jour ma voix`.
- `désactive / réactive la reconnaissance vocale` : suspend la vérification (jusqu'au redémarrage).
- Les empreintes (données biométriques) sont dans `data/voices/`, jamais versionnées. Modèle : SpeechBrain
  ECAPA-TDNN, calculé en local sur le processeur (~0,15 s). Le texte écrit dans le champ n'est jamais vérifié.
- Ce n'est **pas une barrière de sécurité** : un enregistrement ou une voix clonée peut tromper le système,
  et les phrases très courtes ou noyées dans le bruit se vérifient mal.
- Dépendance : `speechbrain` (et `torch`).

## Sommeil et interruption

- `au revoir`, `bonne nuit`, `à plus tard` : Jarvis dit au revoir puis passe **en sommeil** (orbe assombri).
- `tais-toi`, `silence`, `stop`, `ça suffit` : il se tait immédiatement et passe aussi en sommeil.
- En sommeil, seul un « Hey Jarvis » net le réveille (seuil plus strict, `WAKEWORD_THRESHOLD_SLEEP`) ;
  écrire dans le champ texte le réveille aussi.
- Pendant qu'il parle, dire « Hey Jarvis » (ou cliquer sur **Stop**) l'interrompt.
- **Salutation au réveil** : quand tu le réveilles (après un sommeil, ou au premier appel après plus de 3 h),
  Jarvis attend 1,5 s ; si tu ne dis rien, il te salue (« Bonjour ! Que puis-je faire pour toi aujourd'hui ? »,
  « Bonsoir » à partir de 18 h, avec ton prénom s'il le connaît). Si tu enchaînes directement ta commande
  (« Hey Jarvis, mets M6 »), il ne te coupe pas la parole. La détection tient compte du bruit de la télé.
- Le son capté pendant qu'il parle ou réfléchit est jeté (sinon sa propre voix ou la télé le rappelaient).

## Mémoire et apprentissage

Jarvis garde une mémoire **locale** (`data/jarvis.db`, jamais versionnée, conservée 180 jours) :
journal des échanges, faits retenus, corrections apprises. Il n'y a pas de ré-entraînement du modèle :
il se souvient et adapte ses réponses.

- `souviens-toi que ...` / `appelle-moi X` / `que sais-tu de moi ?` / `oublie que ...` / `oublie tout`
- `annule` : défait la dernière action (volume, chaîne, son)
- `non` puis la vraie demande, ou `j'ai dit ...` : il apprend le raccourci (ex. une chaîne mal comprise)
- `qu'as-tu appris ?`, `oublie la dernière correction`, `fais un bilan`, `mets ma chaîne préférée`

## Voix

Voix féminine neuronale **Kokoro** (locale) par défaut ; l'ancienne voix Piper sert de secours.
Modèles à télécharger une fois dans `assets/kokoro/` :

```
mkdir -p assets/kokoro && cd assets/kokoro
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```
Pour revenir à Piper : `TTS_ENGINE = "piper"` dans `config.py`.

## Réglages utiles (`config.py`)

- `OLLAMA_MODEL` : change de modèle LLM (`qwen2.5:3b` par défaut pour la rapidité ;
  `qwen2.5:7b` pour plus de finesse mais plus lent sur un GPU 4 Go).
  Pense à faire `ollama pull <modele>` avant.
- `WAKEWORD_THRESHOLD` : baisse-le (ex: 0.4) si le mot d'activation n'est pas
  assez détecté, monte-le s'il se déclenche tout seul.
- `WHISPER_MODEL_SIZE` : passe en `medium`/`large-v3` une fois le GPU actif pour
  plus de précision (détecté et appliqué automatiquement selon le GPU disponible).
- Le driver GPU (une fois installé) est détecté automatiquement au démarrage,
  aucun changement de code nécessaire.

## Entraînement d'un mot d'activation custom (`training/`)

Contient un pipeline complet pour entraîner un modèle openWakeWord sur mesure
(ex: "Jarvis" seul, sans "Hey"). Tentative faite avec ~12 000 échantillons
synthétiques : résultat pas encore assez fiable (trop de faux positifs) pour
remplacer le modèle "Hey Jarvis" pré-entraîné. Piste à explorer : générateur
TTS anglais plutôt que français pour la synthèse des échantillons positifs.

## Démarrage automatique à la connexion (optionnel)

```
mkdir -p ~/.config/autostart
cp ~/.local/share/applications/jarvis.desktop ~/.config/autostart/
```
Pour désactiver : `rm ~/.config/autostart/jarvis.desktop`

## Logs

`logs/jarvis.log` — utile pour diagnostiquer un souci (micro non détecté,
Ollama injoignable, etc.)
