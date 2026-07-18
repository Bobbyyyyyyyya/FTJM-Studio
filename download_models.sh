#!/bin/bash
set -e

CACHE_DIR="$HOME/.cache/huggingface/hub"

echo "=========================================="
echo "  MODEL DOWNLOADER"
echo "=========================================="
echo ""
echo "Downloadt modellen voor Photo & Audio Generator."
echo ""

download_model() {
  local model="$1"
  echo "Downloaden: $model"
  python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('$model')
print('Gereed')
" || echo "Fout bij $model"
}

download_model "stable-diffusion-v1-5/stable-diffusion-v1-5"
download_model "facebook/musicgen-small"

echo ""
echo "Download voltooid!"
echo "Start de app met de Electron app of:"
echo "  python3 generate.py photo \"een prompt\""
echo "  python3 generate.py audio \"een prompt\""
