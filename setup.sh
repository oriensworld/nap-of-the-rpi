#!/usr/bin/env bash
# setup.sh — First-time Raspberry Pi setup for nap-of-the-rpi
# Run once after cloning the repo on your Pi.

set -euo pipefail

echo "=== nap-of-the-rpi: First-time setup ==="

# 1. Install system dependencies
echo "[1/5] Installing system packages..."
sudo apt-get update
sudo apt-get install -y \
    libportaudio2 \
    libportaudiocpp0 \
    portaudio19-dev \
    bluetooth \
    pulseaudio-module-bluetooth \
    python3-dev

# 2. Install uv (Python package manager)
echo "[2/5] Installing uv..."
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# 3. Install Python dependencies
echo "[3/5] Installing Python dependencies..."
uv sync

# 4. Download Vosk speech recognition model
echo "[4/5] Downloading Vosk model (vosk-model-small-en-us, ~40MB)..."
VOSK_MODEL_DIR="./models/vosk-model-small-en-us"
if [ ! -d "$VOSK_MODEL_DIR" ]; then
    mkdir -p ./models
    curl -LO https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
    unzip vosk-model-small-en-us-0.15.zip -d ./models/
    mv ./models/vosk-model-small-en-us-0.15 "$VOSK_MODEL_DIR"
    rm vosk-model-small-en-us-0.15.zip
else
    echo "  Vosk model already exists, skipping."
fi

# 5. Download Piper TTS voice model
echo "[5/5] Downloading Piper TTS voice model..."
PIPER_MODEL_DIR="./models/piper-voice-en-us"
if [ ! -d "$PIPER_MODEL_DIR" ]; then
    mkdir -p "$PIPER_MODEL_DIR"
    curl -L "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" \
        -o "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx"
    curl -L "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" \
        -o "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx.json"
else
    echo "  Piper voice model already exists, skipping."
fi

# 6. Create config from example if not exists
if [ ! -f "config.yaml" ]; then
    echo "Creating config.yaml from config.example.yaml..."
    cp config.example.yaml config.yaml
    echo "  IMPORTANT: Edit config.yaml and set your WEATHER_API_KEY!"
fi

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit config.yaml with your settings (especially weather API key)"
echo "  2. Pair your Bluetooth speaker: bash scripts/pair_bluetooth.sh"
echo "  3. Run the app: uv run python main.py"
