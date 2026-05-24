#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
export PATH="$PATH:/usr/local/bin:/usr/bin:/home/zeus/miniconda3/envs/cloudspace/bin"

COMFYUI_PORT=8188
OLLAMA_PORT=11434
FLASK_PORT=5000

log() { printf "\033[36m%s\033[0m\n" "$1"; }
ok()  { printf "\033[32m%s\033[0m\n" "$1"; }
warn(){ printf "\033[33m%s\033[0m\n" "$1"; }

# --- Auto-install: Ollama ---
install_ollama() {
  if command -v ollama &>/dev/null; then
    return 0
  fi
  log "  Installing Ollama..."
  if command -v curl &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh 2>/tmp/ollama_install.log
    if command -v ollama &>/dev/null; then
      ok "  Ollama installed"
      return 0
    fi
  fi
  warn "  Ollama install failed — get it from https://ollama.com"
  return 1
}

# --- Auto-install: ComfyUI ---
install_comfyui() {
  if [ -f "ComfyUI/main.py" ]; then
    return 0
  fi
  log "  Cloning ComfyUI..."
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git /tmp/ComfyUI 2>/tmp/comfyui_install.log
  if [ -f "/tmp/ComfyUI/main.py" ]; then
    rm -rf ComfyUI 2>/dev/null
    mv /tmp/ComfyUI .
    log "  Installing ComfyUI dependencies..."
    PYTHON=$(command -v python3 || command -v python)
    "$PYTHON" -m pip install -r ComfyUI/requirements.txt --quiet 2>/tmp/comfyui_deps.log
    # Create model dirs
    mkdir -p ComfyUI/models/{checkpoints,diffusion_models,text_encoders,vae,clip,clip_vision,ipadapter,loras,upscale_models,controlnet,embeddings}
    ok "  ComfyUI installed"
  else
    warn "  ComfyUI clone failed — check /tmp/comfyui_install.log"
    return 1
  fi
}

# --- Auto-install: huggingface-cli ---
install_hf_cli() {
  if command -v hf &>/dev/null; then
    return 0
  fi
  log "  Installing huggingface-cli..."
  PYTHON=$(command -v python3 || command -v python)
  "$PYTHON" -m pip install -q huggingface-hub 2>/tmp/hf_install.log
  if command -v hf &>/dev/null; then
    ok "  hf CLI ready"
  fi
}

# --- Ollama ---
start_ollama() {
  if curl -sf http://127.0.0.1:$OLLAMA_PORT/api/tags >/dev/null 2>&1; then
    ok "  Ollama already running"
    return
  fi
  install_ollama || return
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
  install_comfyui || return
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

# --- Model check (All models) ---
ensure_models() {
  log "  Checking model files..."
  local missing=0

  # Juggernaut XL checkpoint
  if [ ! -f "ComfyUI/models/checkpoints/Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors" ]; then
    warn "    Juggernaut-XL missing — downloading (7.1 GB, may take a while)..."
    mkdir -p ComfyUI/models/checkpoints
    hf download RunDiffusion/Juggernaut-XL-v9 Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors \
      --local-dir ComfyUI/models/checkpoints 2>/tmp/juggernaut_dl.log
    if [ -f "ComfyUI/models/checkpoints/Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors" ]; then
      ok "    Juggernaut-XL downloaded"
    else
      warn "    Juggernaut-XL download failed — check /tmp/juggernaut_dl.log"
      missing=1
    fi
  else
    ok "  Juggernaut-XL checkpoint present"
  fi

  # RealVisXL V5.0 checkpoint
  if [ ! -f "ComfyUI/models/checkpoints/RealVisXL_V5.0_fp16.safetensors" ]; then
    warn "    RealVisXL V5.0 missing — downloading (6.9 GB)..."
    mkdir -p ComfyUI/models/checkpoints
    hf download SG161222/RealVisXL_V5.0 RealVisXL_V5.0_fp16.safetensors \
      --local-dir ComfyUI/models/checkpoints 2>/tmp/realvisxl_dl.log
    if [ -f "ComfyUI/models/checkpoints/RealVisXL_V5.0_fp16.safetensors" ]; then
      ok "    RealVisXL V5.0 downloaded"
    else
      warn "    RealVisXL V5.0 download failed — check /tmp/realvisxl_dl.log"
      missing=1
    fi
  else
    ok "  RealVisXL V5.0 checkpoint present"
  fi

  # Anima diffusion model + text encoder + VAE
  if [ -f "ComfyUI/models/diffusion_models/anima-base-v1.0.safetensors" ] && \
     [ -f "ComfyUI/models/text_encoders/qwen_3_06b_base.safetensors" ] && \
     [ -f "ComfyUI/models/vae/qwen_image_vae.safetensors" ]; then
    ok "  All Anima models present"
  else
    log "  Downloading missing Anima models..."
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
  fi

  # Flux.1-dev fp8
  if [ -f "ComfyUI/models/unet/flux1-dev-fp8.safetensors" ] && \
     [ -f "ComfyUI/models/clip/t5xxl_fp8_e4m3fn.safetensors" ] && \
     [ -f "ComfyUI/models/clip/clip_l.safetensors" ] && \
     [ -f "ComfyUI/models/vae/ae.safetensors" ]; then
    ok "  All Flux.1-dev models present"
  else
    log "  Downloading missing Flux.1-dev models..."
    local flux_repos="flux1-dev-fp8.safetensors:Comfy-Org/flux1-dev:ComfyUI/models/unet"
    flux_repos="$flux_repos t5xxl_fp8_e4m3fn.safetensors:comfyanonymous/flux_text_encoders:ComfyUI/models/clip"
    flux_repos="$flux_repos clip_l.safetensors:comfyanonymous/flux_text_encoders:ComfyUI/models/clip"
    for entry in $flux_repos; do
      fname=$(echo "$entry" | cut -d: -f1)
      repo=$(echo "$entry" | cut -d: -f2)
      dest=$(echo "$entry" | cut -d: -f3)
      if [ ! -f "$dest/$fname" ]; then
        mkdir -p "$dest"
        log "    Downloading $fname..."
        hf download "$repo" "$fname" --local-dir "$dest" 2>/tmp/flux_${fname}_dl.log
        if [ -f "$dest/$fname" ]; then
          ok "    Downloaded $fname"
        else
          warn "    $fname download failed — check /tmp/flux_${fname}_dl.log"
          missing=1
        fi
      fi
    done
    # Flux VAE (ae.safetensors) from ungated source
    if [ ! -f "ComfyUI/models/vae/ae.safetensors" ]; then
      log "    Downloading Flux VAE (ae.safetensors)..."
      mkdir -p /tmp/flux_vae ComfyUI/models/vae
      hf download diffusers/FLUX.1-vae diffusion_pytorch_model.safetensors --local-dir /tmp/flux_vae 2>/tmp/flux_vae_dl.log
      if [ -f "/tmp/flux_vae/diffusion_pytorch_model.safetensors" ]; then
        cp /tmp/flux_vae/diffusion_pytorch_model.safetensors ComfyUI/models/vae/ae.safetensors
        ok "    Downloaded Flux VAE"
      else
        warn "    Flux VAE download failed — check /tmp/flux_vae_dl.log"
        missing=1
      fi
    fi
  fi

  if [ "$missing" -eq 0 ]; then
    ok "  Model check complete"
  fi
}

# --- Ollama model pull ---
ensure_ollama_model() {
  local model_name="${1:-qwen2.5:7b}"
  if curl -sf http://127.0.0.1:$OLLAMA_PORT/api/tags >/dev/null 2>&1; then
    if curl -sf http://127.0.0.1:$OLLAMA_PORT/api/tags | python3 -c "import json,sys;d=json.load(sys.stdin);exit(0 if any('$model_name' in m['name'] for m in d.get('models',[])) else 1)" 2>/dev/null; then
      ok "  Ollama model $model_name already pulled"
      return 0
    fi
    log "  Pulling Ollama model $model_name (may take a while)..."
    ollama pull "$model_name" 2>/tmp/ollama_pull.log
    if [ $? -eq 0 ]; then
      ok "  Ollama model $model_name pulled"
    else
      warn "  Ollama model pull failed — check /tmp/ollama_pull.log"
    fi
  fi
}

# --- Start all services in parallel ---
echo ""
printf "\033[1;35m%s\033[0m\n" "========================================"
printf "\033[1;35m%s\033[0m\n" "   Story-to-Image Pipeline — Launcher"
printf "\033[1;35m%s\033[0m\n" "========================================"
echo ""

install_hf_cli
ensure_models

# Fire up both services concurrently
start_ollama &
start_comfyui &
wait

# Pull the Ollama model now that Ollama is running
ensure_ollama_model "$(python3 -c "import yaml;print(yaml.safe_load(open('config/config.yaml'))['ollama']['model'])" 2>/dev/null || echo 'qwen2.5:7b')"

# Start Flask (skip if already running)
FLASK_ACTUAL=$FLASK_PORT
start_flask() {
  if curl -sf http://127.0.0.1:$FLASK_PORT >/dev/null 2>&1; then
    ok "  Flask already running on :$FLASK_ACTUAL"
    return 0
  fi
  for try in $FLASK_PORT $((FLASK_PORT+1)) $((FLASK_PORT+2)); do
    if ! curl -sf http://127.0.0.1:$try >/dev/null 2>&1; then
      FLASK_ACTUAL=$try
      break
    fi
  done
  log "  Starting Flask web app on http://0.0.0.0:$FLASK_ACTUAL"
  nohup env FLASK_PORT=$FLASK_ACTUAL python webapp/app.py > /tmp/flask_app.log 2>&1 &
  for _ in $(seq 1 10); do
    if curl -sf http://127.0.0.1:$FLASK_ACTUAL >/dev/null 2>&1; then
      ok "  Flask ready on :$FLASK_ACTUAL"
      return 0
    fi
    sleep 1
  done
  log "  Flask start timed out — check /tmp/flask_app.log"
}

start_flask

echo ""
printf "\033[1;32m%s\033[0m\n" "========================================"
printf "\033[1;32m%s\033[0m\n" "   All services running!"
printf "\033[1;32m%s\033[0m\n" "   Open: http://localhost:$FLASK_ACTUAL"
printf "\033[1;32m%s\033[0m\n" "========================================"
echo ""
printf "\033[2m%s\033[0m\n" "  Press Ctrl+C to stop all services"

# Keep running — monitor services and tail Flask log
trap 'log "Shutting down..."; exit 0' INT TERM
while true; do
  sleep 30
  if ! curl -sf http://127.0.0.1:$FLASK_ACTUAL >/dev/null 2>&1; then
    warn "  Flask seems down — restarting..."
    nohup env FLASK_PORT=$FLASK_ACTUAL python webapp/app.py > /tmp/flask_app.log 2>&1 &
  fi
done
