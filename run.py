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
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMFYUI_DIR = ROOT / 'ComfyUI'
FLASK_PORT = 5000
COMFYUI_PORT = 8188
OLLAMA_PORT = 11434


def log(msg):
    print(f'  \033[36m{msg}\033[0m')


def check_port(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def start_ollama():
    if check_port(OLLAMA_PORT):
        log('Ollama already running')
        return True
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
        log('Ollama not installed')
        return False


def start_comfyui():
    if check_port(COMFYUI_PORT):
        log('ComfyUI already running')
        return True
    log('Starting ComfyUI...')
    main_py = COMFYUI_DIR / 'main.py'
    if not main_py.exists():
        log(f'ComfyUI not found at {main_py}')
        return False
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


def main():
    print()
    print('  \033[1;35m' + '=' * 56 + '\033[0m')
    print('  \033[1;35m   Story-to-Image Pipeline — Auto Launch\033[0m')
    print('  \033[1;35m' + '=' * 56 + '\033[0m')
    print()

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
