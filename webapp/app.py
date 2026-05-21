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

import cloudscraper
import requests
import yaml
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from webapp.scraper import scrape_webnovel, fetch_chapter_text

_CLOUDSCRAPER = None
def _get_cloudscraper():
    global _CLOUDSCRAPER
    if _CLOUDSCRAPER is None:
        _CLOUDSCRAPER = cloudscraper.create_scraper()
    return _CLOUDSCRAPER

app = Flask(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / 'config' / 'config.yaml'
OUTPUT_DIR = PROJECT_ROOT / 'output'
os.makedirs(OUTPUT_DIR, exist_ok=True)
sys.path.insert(0, str(PROJECT_ROOT))

setup_status = {'done': False, 'comfyui': False, 'ollama': False, 'error': ''}
tasks = {}
story_sessions = {}
image_counter = 0
counter_lock = threading.Lock()


def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)


def save_config(cfg):
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(cfg, f, default_flow_style=False)


def auto_setup():
    config = load_config()
    comfyui_url = config.get('comfyui', {}).get('url', 'http://127.0.0.1:8188')
    ollama_cfg = config.get('ollama', {})
    ollama_url = ollama_cfg.get('url', 'http://127.0.0.1:11434')

    try:
        r = requests.get(f'{comfyui_url}/system_stats', timeout=5)
        if r.status_code == 200:
            setup_status['comfyui'] = True
    except:
        try:
            subprocess.Popen(
                ['python', str(PROJECT_ROOT / 'ComfyUI' / 'main.py'), '--listen', '--port', '8188'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except:
            pass

    try:
        r = requests.get(f'{ollama_url}/api/tags', timeout=3)
        if r.status_code == 200:
            setup_status['ollama'] = True
        else:
            model_name = ollama_cfg.get('model', 'llama3.1:8b')
            threading.Thread(target=lambda: os.system(f'ollama pull {model_name}'), daemon=True).start()
    except:
        pass

    setup_status['done'] = True


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    comfyui_url = load_config().get('comfyui', {}).get('url', 'http://127.0.0.1:8188')
    ollama_url = load_config().get('ollama', {}).get('url', 'http://127.0.0.1:11434')
    try:
        r = requests.get(f'{comfyui_url}/system_stats', timeout=3)
        setup_status['comfyui'] = r.status_code == 200
    except:
        setup_status['comfyui'] = False
    try:
        r = requests.get(f'{ollama_url}/api/tags', timeout=3)
        setup_status['ollama'] = r.status_code == 200
    except:
        setup_status['ollama'] = False
    return jsonify(setup_status)


@app.route('/api/scrape', methods=['POST'])
def api_scrape():
    url = request.json.get('url', '').strip()
    chapter_start = request.json.get('chapter_start', 1)
    chapter_end = request.json.get('chapter_end', 10)
    if not url:
        return jsonify({'error': 'URL required'}), 400
    try:
        result = scrape_webnovel(url)
        if result.get('error'):
            return jsonify(result), 400

        site_name = urlparse(url).hostname or ''
        is_webnovel = 'webnovel' in site_name

        if is_webnovel and result.get('first_chapter_id'):
            scraper = _get_cloudscraper()
            total = result.get('total_chapters', 2000)
            chapter_id = result['first_chapter_id']
            chapters = []
            chap_resp = None
            for i in range(1, chapter_end + 1):
                chap_url = f'https://www.webnovel.com/book/{result["book_id"]}/{chapter_id}'
                if i >= chapter_start:
                    try:
                        chap_resp = scraper.get(chap_url, timeout=30)
                        csoup = BeautifulSoup(chap_resp.text, 'html.parser')
                        page_title = csoup.title.string.strip() if csoup.title else f'Chapter {i}'
                        page_title = re.sub(r'\s*-\s*WebNovel$', '', page_title)
                        chapters.append({'title': page_title, 'url': chap_url, 'id': chapter_id})
                    except Exception:
                        chapters.append({'title': f'Chapter {i}', 'url': chap_url, 'id': chapter_id})
                if chap_resp:
                    next_match = re.search(r'"nextChapterId"\s*:\s*"(\d+)"', chap_resp.text)
                    if not next_match:
                        break
                    chapter_id = next_match.group(1)
                else:
                    break

            result['chapters'] = chapters
            result['total_chapters'] = total
            result['range'] = {'start': chapter_start, 'end': chapter_start + len(chapters) - 1}
            return jsonify(result)

        chapters = result.get('chapters', [])
        total = len(chapters)
        start_idx = max(0, min(chapter_start - 1, total - 1))
        end_idx = max(start_idx, min(chapter_end, total))
        selected = chapters[start_idx:end_idx]
        result['chapters'] = selected
        result['total_chapters'] = total
        result['range'] = {'start': start_idx + 1, 'end': end_idx}
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/fetch-chapter', methods=['POST'])
def api_fetch_chapter():
    url = request.json.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL required'}), 400
    try:
        text = fetch_chapter_text(url)
        return jsonify({'text': text, 'url': url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/enrich', methods=['POST'])
def api_enrich():
    text = request.json.get('text', '').strip()
    context = request.json.get('context', '')
    style = request.json.get('style', 'cinematic fantasy')
    if not text:
        return jsonify({'error': 'Text is required'}), 400

    config = load_config()
    ollama_cfg = config.get('ollama', {})
    ollama_url = ollama_cfg.get('url', 'http://127.0.0.1:11434')
    model = ollama_cfg.get('model', 'qwen2.5:7b')

    ctx_blurb = ''
    if context:
        ctx_blurb = f'\n\nStory context (previous scenes):\n{context[:2000]}'

    prompt = f"""You are an expert SDXL prompt engineer. Transform this story scene into a detailed, cinematic image prompt.

Rules:
- Describe setting, lighting, mood, camera angle, character appearance, action
- Use vivid cinematic keywords (e.g. dramatic lighting, golden hour, deep shadows)
- Maintain consistency with story context if provided
- Art style: {style}
- Output ONLY the prompt, no labels or explanations
{ctx_blurb}

Scene:
{text[:2000]}

Enhanced prompt:"""

    try:
        resp = requests.post(
            f'{ollama_url}/api/generate',
            json={'model': model, 'prompt': prompt, 'stream': False},
            timeout=90,
        )
        if resp.status_code == 200:
            enriched = resp.json().get('response', text).strip()
            enriched = re.sub(r'^(Enhanced prompt:|Prompt:|\*\*)', '', enriched).strip()
            return jsonify({'enriched': enriched})
    except Exception:
        pass

    return jsonify({'enriched': text})


def generate_next_image_id():
    global image_counter
    with counter_lock:
        image_counter += 1
        return f'img_{image_counter:06d}'


def build_workflow(model_name, prompt, negative, steps, cfg, width, height, filename, base_quality):
    models_config = {
        'juggernaut-xl': {
            'checkpoint': 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors',
            'prompt_template': '{base_quality}, {prompt}',
            'anime_tags': '',
        },
        'anima': {
            'unet': 'anima-base-v1.0.safetensors',
            'clip': 'qwen_3_06b_base.safetensors',
            'clip_type': 'qwen_image',
            'vae': 'qwen_image_vae.safetensors',
            'prompt_template': 'masterpiece, best quality, score_7, safe, {prompt}',
            'anime_tags': ', year 2025, newest, highres, anime screenshot, official art',
        },
    }
    model_key = 'anima' if model_name.lower() == 'anima' else 'juggernaut-xl'
    mcfg = models_config[model_key]

    full_prompt = mcfg['prompt_template'].format(base_quality=base_quality, prompt=prompt) + mcfg.get('anime_tags', '')

    if model_key == 'anima':
        return {
            "1": {"class_type": "CLIPLoader", "inputs": {"clip_name": mcfg['clip'], "type": mcfg['clip_type']}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": full_prompt[:1500], "clip": ["1", 0]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative[:1500], "clip": ["1", 0]}},
            "4": {"class_type": "UNETLoader", "inputs": {"unet_name": mcfg['unet'], "weight_dtype": "default"}},
            "5": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["4", 0], "shift": 4.0}},
            "6": {"class_type": "VAELoader", "inputs": {"vae_name": mcfg['vae']}},
            "7": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "8": {"class_type": "KSampler", "inputs": {"seed": int(time.time() * 1000) % 2**32, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "normal", "denoise": 1, "model": ["5", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["7", 0]}},
            "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["6", 0]}},
            "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": f'reverend_insanity/{filename.replace(".png","")}', "images": ["9", 0]}},
        }
    else:
        return {
            "3": {"class_type": "KSampler", "inputs": {"seed": int(time.time() * 1000) % 2**32, "steps": steps, "cfg": cfg, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": mcfg['checkpoint']}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": full_prompt[:1500], "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative[:1500], "clip": ["4", 1]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": f'reverend_insanity/{filename.replace(".png","")}', "images": ["8", 0]}},
        }


@app.route('/api/generate', methods=['POST'])
def api_generate():
    prompt = request.json.get('prompt', '').strip()
    negative = request.json.get('negative', '')
    steps = request.json.get('steps', 25)
    cfg = request.json.get('cfg', 7.0)
    width = request.json.get('width', 1216)
    height = request.json.get('height', 832)
    chapter = request.json.get('chapter', 1)
    scene = request.json.get('scene', 1)
    model = request.json.get('model', 'juggernaut-xl')

    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400

    config = load_config()
    comfyui_url = config.get('comfyui', {}).get('url', 'http://127.0.0.1:8188')
    neg_prompt = config.get('prompts', {}).get('negative_prompt',
        'blurry, low quality, bad anatomy, distorted face, extra limbs, watermark, text, signature, deformed, ugly, poorly drawn, out of frame')
    base_quality = config.get('prompts', {}).get('base_quality',
        'masterpiece, best quality, highly detailed, cinematic lighting, 8k')

    negative = negative or neg_prompt
    img_id = generate_next_image_id()
    filename = f'ch{chapter:04d}_sc{scene:04d}_{img_id}.png'

    workflow = build_workflow(model, prompt, negative, steps, cfg, width, height, filename, base_quality)

    task_id = uuid.uuid4().hex[:8]
    tasks[task_id] = {'status': 'queued', 'result': None, 'error': None}

    def run():
        tasks[task_id]['status'] = 'running'
        try:
            resp = requests.post(f'{comfyui_url}/prompt', json={'prompt': workflow}, timeout=60)
            if resp.status_code != 200:
                tasks[task_id]['status'] = 'failed'
                tasks[task_id]['error'] = f'ComfyUI error: {resp.text[:200]}'
                return
            result_data = resp.json()
            prompt_id = result_data.get('prompt_id', '')

            for _ in range(120):
                time.sleep(2)
                try:
                    hr = requests.get(f'{comfyui_url}/history/{prompt_id}', timeout=5)
                    if hr.status_code == 200:
                        hist = hr.json()
                        outputs = hist.get(prompt_id, {}).get('outputs', {})
                        images = []
                        for node_id, node_out in outputs.items():
                            for img_data in node_out.get('images', []):
                                img_path = f'/output/{img_data.get("subfolder", "")}/{img_data.get("filename", "")}'
                                src_path = COMFYUI_OUTPUT / img_data.get("subfolder", "") / img_data.get("filename", "")
                                dst_name = f'{img_data.get("subfolder", "")}/{filename}'
                                dst_path = COMFYUI_OUTPUT / dst_name
                                if src_path.exists() and not dst_path.exists():
                                    src_path.rename(dst_path)
                                    img_path = f'/output/{dst_name}'
                                images.append(img_path)
                        if images:
                            tasks[task_id]['status'] = 'completed'
                            tasks[task_id]['result'] = images
                            return
                except:
                    pass
            tasks[task_id]['status'] = 'failed'
            tasks[task_id]['error'] = 'Timeout waiting for image'
        except Exception as e:
            tasks[task_id]['status'] = 'failed'
            tasks[task_id]['error'] = str(e)
        tasks[task_id]['status'] = 'failed'

    t = threading.Thread(target=run, daemon=True)
    t.start()

    return jsonify({'task_id': task_id, 'filename': filename})


@app.route('/api/task/<task_id>')
def api_task(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify({
        'status': task['status'],
        'result': task.get('result'),
        'error': task.get('error'),
    })


AVAILABLE_MODELS = [
    {'id': 'juggernaut-xl', 'name': 'Juggernaut XL v9 (Photorealistic)', 'type': 'sdxl'},
    {'id': 'anima', 'name': 'Anima 2B (Anime/Illustration)', 'type': 'diffusion'},
]


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    config = load_config()
    if request.method == 'POST':
        data = request.json
        if 'ollama_enabled' in data:
            config['ollama']['enabled'] = bool(data['ollama_enabled'])
        if 'ollama_model' in data:
            config['ollama']['model'] = data['ollama_model']
        if 'steps' in data:
            config['generation']['steps'] = int(data['steps'])
        if 'cfg' in data:
            config['generation']['cfg'] = float(data['cfg'])
        if 'style' in data:
            config['prompts']['style'] = data['style']
        if 'base_quality' in data:
            config['prompts']['base_quality'] = data['base_quality']
        if 'negative_prompt' in data:
            config['prompts']['negative_prompt'] = data['negative_prompt']
        if 'model' in data:
            config['models']['active'] = data['model']
        save_config(config)
        return jsonify({'status': 'saved'})

    ollama_cfg = config.get('ollama', {})
    gen = config.get('generation', {})
    prompts = config.get('prompts', {})
    models_config = config.get('models', {})
    return jsonify({
        'comfyui_url': config.get('comfyui', {}).get('url', ''),
        'ollama_enabled': ollama_cfg.get('enabled', False),
        'ollama_model': ollama_cfg.get('model', 'qwen2.5:7b'),
        'steps': gen.get('steps', 25),
        'cfg': gen.get('cfg', 7.0),
        'style': prompts.get('style', 'cinematic fantasy'),
        'base_quality': prompts.get('base_quality', 'masterpiece, best quality, highly detailed, cinematic lighting, 8k'),
        'negative_prompt': prompts.get('negative_prompt',
            'blurry, low quality, bad anatomy, distorted face, extra limbs, watermark, text'),
        'model': models_config.get('active', 'juggernaut-xl'),
        'available_models': AVAILABLE_MODELS,
    })


@app.route('/api/list-models')
def api_list_models():
    ollama_url = load_config().get('ollama', {}).get('url', 'http://127.0.0.1:11434')
    try:
        r = requests.get(f'{ollama_url}/api/tags', timeout=5)
        if r.status_code == 200:
            models = [m['name'] for m in r.json().get('models', [])]
            return jsonify({'models': models})
    except:
        pass
    return jsonify({'models': []})


COMFYUI_OUTPUT = PROJECT_ROOT / 'ComfyUI' / 'output'


@app.route('/output/<path:filename>')
def serve_output(filename):
    path = OUTPUT_DIR / filename
    if path.exists():
        return send_from_directory(str(OUTPUT_DIR), filename)
    fallback = COMFYUI_OUTPUT / filename
    if fallback.exists():
        return send_from_directory(str(COMFYUI_OUTPUT), filename)
    return '', 404


@app.route('/api/gallery')
def api_gallery():
    images = []

    ri_dir = OUTPUT_DIR / 'reverend_insanity'
    if ri_dir.exists():
        for png in sorted(ri_dir.glob('*.png')):
            images.append(f'/output/reverend_insanity/{png.name}')

    comfy_ri = COMFYUI_OUTPUT / 'reverend_insanity'
    if comfy_ri.exists():
        for png in sorted(comfy_ri.glob('*.png')):
            rel = f'/output/reverend_insanity/{png.name}'
            if rel not in images:
                images.append(rel)

    for png in sorted(OUTPUT_DIR.glob('**/*.png')):
        rel = str(png.relative_to(OUTPUT_DIR))
        url = f'/output/{rel}'
        if url not in images:
            images.append(url)

    return jsonify({'images': images})


auto_setup()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
