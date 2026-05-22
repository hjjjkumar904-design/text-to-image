#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
export PATH="$PATH:/usr/local/bin:/usr/bin:/home/zeus/miniconda3/envs/cloudspace/bin"

COMFYUI_PORT=8188
OLLAMA_PORT=11434
FLASK_PORT=5000

log() { printf "\033[36m%s\033[0m\n" "$1"; }
ok()  { printf "\033[32m%s\033[0m\n" "$1"; }

# --- Ollama ---
start_ollama() {
  if curl -sf http://127.0.0.1:$OLLAMA_PORT/api/tags >/dev/null 2>&1; then
    ok "  Ollama already running"
    return
  fi
  if ! command -v ollama &>/dev/null; then
    log "  ollama not found — install from https://ollama.com"
    return
  fi
  log "  Starting Ollama..."
  nohup ollama serve > /tmp/ollama.log 2>&1 &
  for _ in $(seq 1 15); do
    if curl -sf http://127.0.0.1:$OLLAMA_PORT/api/tags >/dev/null 2>&1; then
      ok "  Ollama ready"
      return
    fi
    sleep 1
  done
  log "  Ollama start issued (may take a moment)"
}

# --- ComfyUI ---
start_comfyui() {
  if curl -sf http://127.0.0.1:$COMFYUI_PORT/system_stats >/dev/null 2>&1; then
    ok "  ComfyUI already running"
    return
  fi
  log "  Starting ComfyUI..."
  PYTHON=$(command -v python3 || command -v python)
  nohup "$PYTHON" ComfyUI/main.py --listen --port $COMFYUI_PORT > /tmp/comfyui_server.log 2>&1 &
  for _ in $(seq 1 30); do
    if curl -sf http://127.0.0.1:$COMFYUI_PORT/system_stats >/dev/null 2>&1; then
      ok "  ComfyUI ready"
      return
    fi
    sleep 2
  done
  log "  ComfyUI start timed out — check /tmp/comfyui_server.log"
}

# --- Model check (Anima) ---
ensure_models() {
  log "  Checking diffusion models..."
  if [ -f "ComfyUI/models/diffusion_models/anima-base-v1.0.safetensors" ] && \
     [ -f "ComfyUI/models/text_encoders/qwen_3_06b_base.safetensors" ] && \
     [ -f "ComfyUI/models/vae/qwen_image_vae.safetensors" ]; then
    ok "  All Anima models present"
    return
  fi
  log "  Downloading missing Anima models (may take a while)..."
  for pair in \
    "split_files/diffusion_models/anima-base-v1.0.safetensors ComfyUI/models/diffusion_models" \
    "split_files/text_encoders/qwen_3_06b_base.safetensors ComfyUI/models/text_encoders" \
    "split_files/vae/qwen_image_vae.safetensors ComfyUI/models/vae"; do
    rel_path=$(echo "$pair" | cut -d' ' -f1)
    dest_dir=$(echo "$pair" | cut -d' ' -f2)
    fname=$(basename "$rel_path")
    if [ ! -f "$dest_dir/$fname" ]; then
      mkdir -p "$dest_dir"
      hf download circlestone-labs/Anima "$rel_path" --local-dir /tmp/anima_dl 2>/dev/null
      if [ -f "/tmp/anima_dl/$rel_path" ]; then
        mv "/tmp/anima_dl/$rel_path" "$dest_dir/$fname"
        log "    Downloaded $fname"
      fi
    fi
  done
  rm -rf /tmp/anima_dl
  log "  Model check complete"
}

# --- Start all services in parallel ---
echo ""
printf "\033[1;35m%s\033[0m\n" "========================================"
printf "\033[1;35m%s\033[0m\n" "   Story-to-Image Pipeline — Launcher"
printf "\033[1;35m%s\033[0m\n" "========================================"
echo ""

ensure_models

# Fire up both services concurrently
start_ollama &
start_comfyui &
wait

# Start Flask
log "  Starting Flask web app on http://0.0.0.0:$FLASK_PORT"
python webapp/app.py &

# Wait for Flask
for _ in $(seq 1 10); do
  if curl -sf http://127.0.0.1:$FLASK_PORT >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo ""
printf "\033[1;32m%s\033[0m\n" "========================================"
printf "\033[1;32m%s\033[0m\n" "   All services running!"
printf "\033[1;32m%s\033[0m\n" "   Open: http://localhost:$FLASK_PORT"
printf "\033[1;32m%s\033[0m\n" "========================================"
echo ""

wait
