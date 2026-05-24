#!/usr/bin/env python3
"""
Story-to-Image Pipeline — Auto Setup & Launch
Starts ComfyUI, Ollama, and the Flask web app automatically.
"""

import os
import subprocess
import sys
import time
import webbrowser
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMFYUI_DIR = ROOT / 'ComfyUI'
FLASK_PORT = 5000
COMFYUI_PORT = 8188
OLLAMA_PORT = 11434

ANIMA_FILES = [
    ('split_files/diffusion_models/anima-base-v1.0.safetensors', COMFYUI_DIR / 'models' / 'diffusion_models'),
    ('split_files/text_encoders/qwen_3_06b_base.safetensors', COMFYUI_DIR / 'models' / 'text_encoders'),
    ('split_files/vae/qwen_image_vae.safetensors', COMFYUI_DIR / 'models' / 'vae'),
]

JUGGERNAUT_FILE = 'checkpoints/Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'


def log(msg):
    print(f'  \033[36m{msg}\033[0m')


def check_port(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def install_ollama():
    import shutil
    if shutil.which('ollama'):
        return True
    log('Installing Ollama...')
    try:
        r = subprocess.run(['sh'], input=subprocess.run(['curl', '-fsSL', 'https://ollama.com/install.sh'], capture_output=True).stdout, capture_output=True, timeout=120)
        if shutil.which('ollama'):
            log('Ollama installed')
            return True
    except Exception as e:
        log(f'Ollama install failed: {e}')
    return False


def install_comfyui():
    if (COMFYUI_DIR / 'main.py').exists():
        return True
    log('Cloning ComfyUI...')
    try:
        subprocess.run(['git', 'clone', '--depth', '1', 'https://github.com/comfyanonymous/ComfyUI.git', str(COMFYUI_DIR)], check=True, timeout=120)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(COMFYUI_DIR / 'requirements.txt')], check=True, timeout=120)
        for d in ['checkpoints', 'diffusion_models', 'text_encoders', 'vae', 'clip', 'clip_vision', 'ipadapter', 'loras', 'upscale_models', 'controlnet', 'embeddings']:
            (COMFYUI_DIR / 'models' / d).mkdir(parents=True, exist_ok=True)
        log('ComfyUI installed')
        return True
    except Exception as e:
        log(f'ComfyUI install failed: {e}')
        return False


def start_ollama():
    if check_port(OLLAMA_PORT):
        log('Ollama already running')
        return True
    if not install_ollama():
        log('Ollama not installed — install from https://ollama.com')
        return False
    log('Starting Ollama...')
    try:
        subprocess.Popen(['ollama', 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(15):
            if check_port(OLLAMA_PORT):
                log('Ollama ready')
                return True
            time.sleep(1)
        log('Ollama start issued (may take a moment)')
        return True
    except FileNotFoundError:
        log('Ollama not found')
        return False


def start_comfyui():
    if check_port(COMFYUI_PORT):
        log('ComfyUI already running')
        return True
    if not install_comfyui():
        log('ComfyUI install failed')
        return False
    log('Starting ComfyUI...')
    main_py = COMFYUI_DIR / 'main.py'
    with open('/tmp/comfyui_server.log', 'w') as logf:
        subprocess.Popen(
            [sys.executable, str(main_py), '--listen', '--port', str(COMFYUI_PORT)],
            cwd=str(COMFYUI_DIR),
            stdout=logf, stderr=subprocess.STDOUT,
        )
    for _ in range(30):
        if check_port(COMFYUI_PORT):
            log('ComfyUI ready')
            return True
        time.sleep(2)
    log('ComfyUI start timed out — check /tmp/comfyui_server.log')
    return False


def ensure_ollama_model():
    import requests, yaml
    config_path = ROOT / 'config' / 'config.yaml'
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        model = cfg.get('ollama', {}).get('model', 'qwen2.5:7b')
    except:
        model = 'qwen2.5:7b'

    try:
        r = requests.get(f'http://127.0.0.1:{OLLAMA_PORT}/api/tags', timeout=5)
        models = [m['name'] for m in r.json().get('models', [])]
        if any(model.startswith(m) or m.startswith(model) for m in models):
            log(f'Model {model} already pulled')
            return
        log(f'Pulling {model} (may take a while)...')
        subprocess.Popen(['ollama', 'pull', model], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f'Model check failed: {e}')


def start_flask():
    log('Starting Flask web app...')
    app_py = ROOT / 'webapp' / 'app.py'
    with open('/tmp/flask_app.log', 'w') as logf:
        proc = subprocess.Popen(
            [sys.executable, str(app_py)],
            cwd=str(ROOT),
            stdout=logf, stderr=subprocess.STDOUT,
        )
    for _ in range(10):
        if check_port(FLASK_PORT):
            log('Flask app ready!')
            return proc
        time.sleep(1)
    log('Flask start timed out — check /tmp/flask_app.log')
    return proc


def ensure_diffusion_models():
    log('Checking diffusion models...')
    model_dir = COMFYUI_DIR / 'models'
    
    # Check Juggernaut XL
    jgg_dest = model_dir / 'checkpoints'
    jgg_fname = os.path.basename(JUGGERNAUT_FILE)
    if not (jgg_dest / jgg_fname).exists():
        log('Juggernaut XL checkpoint not found')
        log('Download manually from: https://huggingface.co/RunDiffusion/Juggernaut-XL-v9')
        log('Place at: ComfyUI/models/checkpoints/Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors')
    
    # Check Anima model files
    missing = []
    for rel_path, dest_dir in ANIMA_FILES:
        fname = os.path.basename(rel_path)
        if not (dest_dir / fname).exists():
            missing.append((rel_path, dest_dir))
    
    if not missing:
        log('All models present')
        return
    
    missing_names = [os.path.basename(p) for p, _ in missing]
    log(f'Downloading {len(missing)} missing model(s): {", ".join(missing_names)}')
    log('This may take a while depending on file sizes...')
    for rel_path, dest_dir in missing:
        fname = os.path.basename(rel_path)
        os.makedirs(dest_dir, exist_ok=True)
        try:
            tmp = '/tmp/anima_dl'
            os.makedirs(tmp, exist_ok=True)
            subprocess.run(
                ['hf', 'download', 'circlestone-labs/Anima', rel_path, '--local-dir', tmp],
                capture_output=True, timeout=600,
            )
            src = Path(tmp) / rel_path
            if src.exists():
                import shutil
                shutil.move(str(src), str(dest_dir / fname))
                log(f'  Downloaded {fname}')
            else:
                # Try to find it anywhere in the temp dir
                found = list(Path(tmp).rglob(fname))
                if found:
                    shutil.move(str(found[0]), str(dest_dir / fname))
                    log(f'  Downloaded {fname}')
                else:
                    log(f'  File not found after download: {rel_path}')
        except Exception as e:
            log(f'  Failed to download {fname}: {e}')
    log('Model check complete')


def main():
    print()
    print('  \033[1;35m' + '=' * 56 + '\033[0m')
    print('  \033[1;35m   Story-to-Image Pipeline — Auto Launch\033[0m')
    print('  \033[1;35m' + '=' * 56 + '\033[0m')
    print()

    ensure_diffusion_models()
    start_ollama()
    ensure_ollama_model()
    start_comfyui()
    flask_proc = start_flask()

    print()
    print('  \033[1;32m' + '=' * 56 + '\033[0m')
    print(f'  \033[1;32m   All services running!\033[0m')
    print(f'  \033[1;32m   Open: http://localhost:{FLASK_PORT}\033[0m')
    print('  \033[1;32m' + '=' * 56 + '\033[0m')
    print()
    print('  Flask running in background (PID: %d)' % flask_proc.pid)
    print('  Logs: /tmp/flask_app.log')
    print()
    print('  To stop: kill %d' % flask_proc.pid)
    print()


if __name__ == '__main__':
    main()
