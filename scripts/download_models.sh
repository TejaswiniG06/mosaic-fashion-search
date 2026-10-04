#!/usr/bin/env bash
# Downloads the two free, open-source models used by MOSAIC (no HuggingFace account needed).
#  1. multilingual-e5-small (intfloat, MIT) exported to ONNX + int8 dynamic quantisation, pinned by SHA256
#  2. OpenCLIP ViT-B/32 (LAION-400M, MIT) weights -> exported to ONNX by scripts/export_clip_onnx.py (needs torch once)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p models/multilingual-e5-small models/clip-vit-b32 .cache

E5_URL=https://github.com/teleport-computer/feedling-mcp/releases/download/models-e5-small-614241f6/multilingual-e5-small-614241f6-int8.tar.gz
E5_SHA=f964e4a46307a987ad49f46e8285d51c50199ac57933b3617be9e63546b74e17
if [ ! -f models/multilingual-e5-small/model_int8.onnx ]; then
  echo "downloading multilingual-e5-small (int8 ONNX, ~83 MB)"
  curl -fL --retry 3 -o .cache/e5.tgz "$E5_URL"
  echo "$E5_SHA  .cache/e5.tgz" | sha256sum -c -
  tar -xzf .cache/e5.tgz -C models/multilingual-e5-small
fi

if [ ! -f models/clip-vit-b32/visual.onnx ]; then
  CLIP_URL=https://github.com/mlfoundations/open_clip/releases/download/v0.2-weights/vit_b_32-quickgelu-laion400m_e32-46683a32.pt
  [ -f .cache/vitb32.pt ] || { echo "downloading OpenCLIP ViT-B/32 weights (~600 MB)"; curl -fL --retry 3 -o .cache/vitb32.pt "$CLIP_URL"; }
  echo "exporting CLIP to ONNX (one-off; installs torch+open_clip into a throwaway venv)"
  python3 -m venv .cache/exportenv
  .cache/exportenv/bin/pip install -q torch open_clip_torch onnx numpy pillow
  .cache/exportenv/bin/python scripts/export_clip_onnx.py --weights .cache/vitb32.pt --out models/clip-vit-b32
fi
echo "models ready:"; ls -la models/*
