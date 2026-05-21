#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

COMFYUI_DIR="$SCRIPT_DIR/ComfyUI"
COMFYUI_PORT=${COMFYUI_PORT:-8188}
COMFYUI_URL="http://127.0.0.1:$COMFYUI_PORT"

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Start ComfyUI and optionally run the story pipeline."
    echo ""
    echo "Options:"
    echo "  --story FILE    Run pipeline on FILE after ComfyUI starts"
    echo "  --output DIR    Output directory for generated images"
    echo "  --port PORT     ComfyUI port (default: 8188)"
    echo "  --no-comfyui    Skip starting ComfyUI (use existing instance)"
    echo "  --background    Start ComfyUI in background"
    echo "  --help          Show this help"
    echo ""
    echo "Examples:"
    echo "  $0                                          # Start ComfyUI only"
    echo "  $0 --background                             # Start ComfyUI in background"
    echo "  $0 --story data/stories/example_story.txt   # Start ComfyUI + run pipeline"
    echo "  $0 --no-comfyui --story my_story.txt        # Use existing ComfyUI + run"
    exit 0
}

STORY=""
OUTPUT=""
BACKGROUND=false
NO_COMFYUI=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --story) STORY="$2"; shift 2 ;;
        --output) OUTPUT="$2"; shift 2 ;;
        --port) COMFYUI_PORT="$2"; shift 2 ;;
        --no-comfyui) NO_COMFYUI=true; shift ;;
        --background) BACKGROUND=true; shift ;;
        --help|-h) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

cleanup() {
    if [ -n "$COMFYUI_PID" ] && kill -0 "$COMFYUI_PID" 2>/dev/null; then
        echo ""
        echo "Stopping ComfyUI (PID: $COMFYUI_PID)..."
        kill "$COMFYUI_PID" 2>/dev/null
        wait "$COMFYUI_PID" 2>/dev/null
        echo "ComfyUI stopped."
    fi
}
trap cleanup EXIT INT TERM

if [ ! -d "$COMFYUI_DIR" ]; then
    echo "Error: ComfyUI not found at $COMFYUI_DIR"
    echo "Run 'bash scripts/setup.sh' first to install."
    exit 1
fi

if [ ! -f "$COMFYUI_DIR/models/checkpoints/juggernautXL_v9.safetensors" ]; then
    echo "Warning: Juggernaut XL v9 checkpoint not found."
    echo "Run 'python3 scripts/download_models.py' to download models."
    echo "Continuing anyway (ComfyUI will use default SDXL model if available)..."
fi

if [ "$NO_COMFYUI" = false ]; then
    echo "Starting ComfyUI on port $COMFYUI_PORT..."

    START_CMD="python '$COMFYUI_DIR/main.py' --listen --port '$COMFYUI_PORT'"
    eval "$START_CMD &"
    COMFYUI_PID=$!

    echo "Waiting for ComfyUI to be ready..."
    for i in $(seq 1 60); do
        if curl -sf "$COMFYUI_URL/system_stats" > /dev/null 2>&1; then
            echo "ComfyUI ready at $COMFYUI_URL (PID: $COMFYUI_PID)"
            break
        fi
        if [ "$i" -eq 60 ]; then
            echo "Error: ComfyUI failed to start within 60 seconds."
            exit 1
        fi
        sleep 1
    done
fi

if [ -n "$STORY" ]; then
    if [ ! -f "$STORY" ]; then
        echo "Error: Story file not found: $STORY"
        exit 1
    fi

    echo ""
    echo "Running story pipeline on: $STORY"
    CMD="python run.py --story '$STORY'"
    if [ -n "$OUTPUT" ]; then
        CMD="$CMD --output '$OUTPUT'"
    fi

    eval "$CMD"
fi

if [ "$BACKGROUND" = false ] && [ "$NO_COMFYUI" = false ]; then
    echo ""
    echo "ComfyUI is running at http://localhost:$COMFYUI_PORT"
    echo "Press Ctrl+C to stop."
    wait "$COMFYUI_PID" 2>/dev/null
fi
