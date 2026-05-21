#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Start ComfyUI if not running
if ! curl -sf http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
    echo "Starting ComfyUI..."
    nohup python ComfyUI/main.py --listen --port 8188 > /tmp/comfyui_server.log 2>&1 &
    echo "Waiting for ComfyUI..."
    for i in $(seq 1 30); do
        if curl -sf http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
            echo "ComfyUI ready"
            break
        fi
        sleep 2
    done
fi

# Start Flask app
echo "Starting Web App on http://0.0.0.0:5000"
python webapp/app.py
