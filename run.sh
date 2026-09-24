#!/usr/bin/env bash
# Lance Jarvis (active le venv puis demarre l'app)
cd "$(dirname "$0")"
source venv/bin/activate

# cuBLAS/cuDNN installes via pip (nvidia-cublas-cu12/nvidia-cudnn-cu12) pour faster-whisper GPU
SITE_PACKAGES="$(python3 -c 'import site; print(site.getsitepackages()[0])')"
export LD_LIBRARY_PATH="$SITE_PACKAGES/nvidia/cublas/lib:$SITE_PACKAGES/nvidia/cudnn/lib:$LD_LIBRARY_PATH"

exec python3 -X faulthandler main.py
