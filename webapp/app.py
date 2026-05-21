import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from flask import Flask, jsonify, render_template, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from webapp.scraper import scrape_webnovel, fetch_chapter_text

app = Flask(__name__)
app.config['SECRET_KEY'] = 'story-pipeline-secret'

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / 'config' / 'config.yaml'
OUTPUT_DIR = PROJECT_ROOT / 'output'
os.makedirs(OUTPUT_DIR, exist_ok=True)
sys.path.insert(0, str(PROJECT_ROOT))

setup_status = {'done': False, 'comfyui': False, 'ollama': False, 'error': ''}
generation_tasks: dict = {}


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def setup_background():
    global setup_status
    try:
        config = load_config()

        # Check / start ComfyUI
        comfy_url = config['comfyui']['url']
        try:
            r = requests.get(f'{comfy_url}/system_stats', timeout=3)
            if r.status_code == 200:
                setup_status['comfyui'] = True
        except requests.RequestException:
            comfy_dir = PROJECT_ROOT / 'ComfyUI'
            if comfy_dir.exists():
                log_path = PROJECT_ROOT / 'comfyui_server.log'
                proc = subprocess.Popen(
                    ['python', 'main.py', '--listen', '--port', '8188'],
                    cwd=str(comfy_dir),
                    stdout=open(log_path, 'w'),
                    stderr=subprocess.STDOUT,
                )
                for _ in range(30):
                    try:
                        r = requests.get(f'{comfy_url}/system_stats', timeout=2)
                        if r.status_code == 200:
                            setup_status['comfyui'] = True
                            break
                    except requests.RequestException:
                        time.sleep(2)

        # Check Ollama
        ollama_config = config.get('ollama', {})
        ollama_url = ollama_config.get('url', 'http://127.0.0.1:11434')
        try:
            r = requests.get(f'{ollama_url}/api/tags', timeout=3)
            if r.status_code == 200:
                setup_status['ollama'] = True
                models = r.json().get('models', [])
                model_name = ollama_config.get('model', 'llama3.1:8b')
                if not any(m['name'].startswith(model_name) for m in models):
                    subprocess.Popen(['ollama', 'pull', model_name])
        except requests.RequestException:
            pass

        setup_status['done'] = True
    except Exception as e:
        setup_status['done'] = True
        setup_status['error'] = str(e)


@app.route('/')
def index():
    return render_template('index.html', setup=setup_status)


@app.route('/api/status')
def api_status():
    return jsonify(setup_status)


@app.route('/api/scrape', methods=['POST'])
def api_scrape():
    url = request.json.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    try:
        data = scrape_webnovel(url)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/fetch-chapter', methods=['POST'])
def api_fetch_chapter():
    url = request.json.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    try:
        text = fetch_chapter_text(url)
        return jsonify({'text': text[:15000]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/enrich', methods=['POST'])
def api_enrich():
    text = request.json.get('text', '').strip()
    if not text:
        return jsonify({'error': 'Text is required'}), 400

    config = load_config()
    ollama_cfg = config.get('ollama', {})
    ollama_url = ollama_cfg.get('url', 'http://127.0.0.1:11434')
    model = ollama_cfg.get('model', 'llama3.1:8b')

    prompt = f"""You are an expert prompt engineer for SDXL image generation. Improve this story scene into a detailed image generation prompt.

Rules:
- Describe the setting, lighting, mood, camera angle, and character appearance
- Use descriptive cinematic keywords
- Output ONLY the enhanced prompt text, no explanations

Scene text:
{text[:2000]}

Enhanced prompt:"""

    try:
        resp = requests.post(
            f'{ollama_url}/api/generate',
            json={'model': model, 'prompt': prompt, 'stream': False},
            timeout=60,
        )
        if resp.status_code == 200:
            enriched = resp.json().get('response', text).strip()
            return jsonify({'enriched': enriched})
    except Exception as e:
        pass

    return jsonify({'enriched': text})


@app.route('/api/generate', methods=['POST'])
def api_generate():
    prompt = request.json.get('prompt', '').strip()
    negative = request.json.get('negative', '')
    steps = request.json.get('steps', 30)
    cfg = request.json.get('cfg', 7.5)
    width = request.json.get('width', 1216)
    height = request.json.get('height', 832)

    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400

    task_id = str(uuid.uuid4())[:8]
    generation_tasks[task_id] = {'status': 'queued', 'result': None, 'error': None}

    def run_gen():
        try:
            generation_tasks[task_id]['status'] = 'running'
            config = load_config()
            workflow_path = PROJECT_ROOT / config['comfyui']['workflow']
            comfy_url = config['comfyui']['url']

            with open(workflow_path) as f:
                workflow = json.load(f)

            for node_id, node in workflow.items():
                if node.get('class_type') == 'CLIPTextEncode':
                    inputs = node.get('inputs', {})
                    text = str(inputs.get('text', ''))
                    if 'POSITIVE_PLACEHOLDER' in text or 'masterpiece' in text.lower() or 'quality' in text.lower():
                        inputs['text'] = prompt
                    elif 'NEGATIVE_PLACEHOLDER' in text or 'blurry' in text.lower():
                        inputs['text'] = negative
                if node.get('class_type') == 'KSampler':
                    node['inputs']['steps'] = steps
                    node['inputs']['cfg'] = cfg
                if node.get('class_type') == 'EmptyLatentImage':
                    node['inputs']['width'] = width
                    node['inputs']['height'] = height
                if node.get('class_type') == 'SaveImage':
                    node['inputs']['filename_prefix'] = f'gen_{task_id}'

            payload = {'prompt': workflow, 'client_id': task_id}
            resp = requests.post(f'{comfy_url}/prompt', json=payload, timeout=30)
            if resp.status_code != 200:
                raise Exception(f'ComfyUI error: {resp.text}')

            prompt_id = resp.json().get('prompt_id')
            for _ in range(200):
                r = requests.get(f'{comfy_url}/history/{prompt_id}', timeout=10)
                history = r.json()
                if prompt_id in history:
                    status = history[prompt_id].get('status', {})
                    if status.get('completed'):
                        outputs = history[prompt_id].get('outputs', {})
                        images = []
                        for node_out in outputs.values():
                            for img in node_out.get('images', []):
                                img_url = f'{comfy_url}/view?filename={img["filename"]}&subfolder={img.get("subfolder", "")}'
                                img_resp = requests.get(img_url)
                                if img_resp.status_code == 200:
                                    save_dir = OUTPUT_DIR / task_id
                                    save_dir.mkdir(parents=True, exist_ok=True)
                                    img_path = save_dir / img['filename']
                                    with open(img_path, 'wb') as f:
                                        f.write(img_resp.content)
                                    images.append(f'/output/{task_id}/{img["filename"]}')
                        generation_tasks[task_id]['result'] = images
                        generation_tasks[task_id]['status'] = 'completed'
                        return
                    if status.get('error'):
                        raise Exception(f'Generation error: {status["error"]}')
                time.sleep(2)
            raise Exception('Generation timed out')
        except Exception as e:
            generation_tasks[task_id]['status'] = 'failed'
            generation_tasks[task_id]['error'] = str(e)

    threading.Thread(target=run_gen, daemon=True).start()
    return jsonify({'task_id': task_id})


@app.route('/api/task/<task_id>')
def api_task_status(task_id):
    task = generation_tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(task)


@app.route('/output/<task_id>/<filename>')
def serve_output(task_id, filename):
    return send_from_directory(OUTPUT_DIR / task_id, filename)


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    config = load_config()
    if request.method == 'POST':
        data = request.json
        if 'steps' in data:
            config['generation']['steps'] = int(data['steps'])
        if 'cfg' in data:
            config['generation']['cfg'] = float(data['cfg'])
        if 'ollama_enabled' in data:
            config['ollama']['enabled'] = bool(data['ollama_enabled'])
        if 'ollama_model' in data:
            config['ollama']['model'] = data['ollama_model']
        with open(CONFIG_PATH, 'w') as f:
            yaml.dump(config, f)
        return jsonify({'ok': True})
    return jsonify({
        'steps': config['generation']['steps'],
        'cfg': config['generation']['cfg'],
        'ollama_enabled': config.get('ollama', {}).get('enabled', False),
        'ollama_model': config.get('ollama', {}).get('model', 'llama3.1:8b'),
        'comfyui_url': config['comfyui']['url'],
    })


@app.route('/api/list-models')
def api_list_models():
    config = load_config()
    ollama_url = config.get('ollama', {}).get('url', 'http://127.0.0.1:11434')
    try:
        r = requests.get(f'{ollama_url}/api/tags', timeout=5)
        if r.status_code == 200:
            models = [m['name'] for m in r.json().get('models', [])]
            return jsonify({'models': models})
    except Exception:
        pass
    return jsonify({'models': []})


if __name__ == '__main__':
    threading.Thread(target=setup_background, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=True)
