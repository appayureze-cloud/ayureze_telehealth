#!/usr/bin/env bash
# Downloads the Day 6 pipeline's model weights into apps/ai-agent/models/
# (gitignored — never committed). Run once before setting
# AI_AGENT_ENABLE_PIPELINE=true. Total download: ~2.5GB.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

mkdir -p models

echo "== Silero VAD (ONNX, ~2MB) =="
curl -sL -o models/silero_vad.onnx \
  https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx

echo "== faster-whisper 'tiny' (downloads on first use into models/whisper/) =="
echo "== NLLB-200-distilled-600M + MMS-TTS (downloads on first use into models/hf/) =="
python3 - <<'PY'
from app.pipeline.factory import build_default_pipeline
print("Loading pipeline once to trigger model downloads (this can take a few minutes)...")
build_default_pipeline()
print("Done.")
PY

echo "All models downloaded."
