#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Story-to-Image Pipeline Setup ==="
echo ""

# 1. Install system dependencies
echo "[1/6] Installing system dependencies..."
sudo apt update && sudo apt install -y git python3-pip python3-venv ffmpeg wget

# 2. Clone and setup ComfyUI
echo "[2/6] Setting up ComfyUI..."
if [ ! -d "ComfyUI" ]; then
    git clone https://github.com/comfyanonymous/ComfyUI
    cd ComfyUI
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cd ..
else
    echo "  ComfyUI already exists, updating..."
    cd ComfyUI
    source venv/bin/activate
    pip install -r requirements.txt
    cd ..
fi

# 3. Install custom nodes
echo "[3/6] Installing ComfyUI custom nodes..."
cd ComfyUI/custom_nodes

if [ ! -d "ComfyUI_IPAdapter_plus" ]; then
    git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus
else
    echo "  ComfyUI_IPAdapter_plus already installed"
fi

if [ ! -d "ComfyUI-Manager" ]; then
    git clone https://github.com/ltdrdata/ComfyUI-Manager
else
    echo "  ComfyUI-Manager already installed"
fi

cd "$PROJECT_DIR"

# 4. Create model directories
echo "[4/6] Creating model directories..."
mkdir -p ComfyUI/models/checkpoints
mkdir -p ComfyUI/models/ipadapter
mkdir -p ComfyUI/models/clip_vision
mkdir -p ComfyUI/models/insightface
mkdir -p data/characters
mkdir -p data/stories
mkdir -p output

# 5. Download models
echo "[5/6] Downloading models..."
python3 "$SCRIPT_DIR/download_models.py"

# 6. Install project dependencies
echo "[6/6] Installing project dependencies..."
pip install -r "$PROJECT_DIR/requirements.txt"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To start ComfyUI:"
echo "  cd ComfyUI && python main.py --listen --port 8188 --normalvram"
echo ""
echo "To run the pipeline:"
echo "  python run.py --story data/stories/my_story.txt"
echo ""
