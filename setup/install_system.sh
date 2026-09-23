#!/usr/bin/env bash
# Jarvis - installation des dépendances SYSTÈME (à lancer avec sudo)
# Usage: sudo bash install_system.sh
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Ce script doit être lancé avec sudo: sudo bash install_system.sh"
  exit 1
fi

REAL_USER="${SUDO_USER:-lakrim}"

echo "==> Activation des dépôts contrib/non-free (nécessaires pour le driver NVIDIA)"
sed -i 's/main non-free-firmware/main contrib non-free non-free-firmware/' /etc/apt/sources.list

echo "==> Mise à jour des paquets"
apt update

echo "==> Installation du driver NVIDIA + outils système"
apt install -y \
  linux-headers-"$(uname -r)" \
  nvidia-driver \
  firmware-misc-nonfree \
  build-essential \
  git curl \
  portaudio19-dev \
  python3-dev \
  brightnessctl \
  playerctl \
  alsa-utils \
  libnotify-bin

echo "==> Installation d'Ollama (moteur LLM local)"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
else
  echo "Ollama déjà installé, on saute."
fi

echo "==> Ajout de l'utilisateur $REAL_USER au groupe render/video (accès GPU pour l'inférence)"
usermod -aG render,video "$REAL_USER" || true

echo ""
echo "============================================================"
echo " Installation système terminée."
echo ""
echo " IMPORTANT (Secure Boot est activé sur cette machine) :"
echo " 1. Redémarre la machine : sudo reboot"
echo " 2. Un écran bleu 'MOK Management' va apparaître AVANT le"
echo "    démarrage de Linux. Choisis 'Enroll MOK' -> 'Continue'"
echo "    -> 'Yes', puis entre le mot de passe que le paquet"
echo "    nvidia-driver/dkms t'a demandé de définir pendant"
echo "    l'installation ci-dessus (regarde le terminal si un"
echo "    prompt est apparu)."
echo " 3. Une fois reconnecté, vérifie avec: nvidia-smi"
echo "============================================================"
