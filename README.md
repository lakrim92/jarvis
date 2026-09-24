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
