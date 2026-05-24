import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import cloudscraper
import requests
import yaml
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from webapp.scraper import scrape_webnovel, fetch_chapter_text as _fetch_chapter_text

app = Flask(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / 'config' / 'config.yaml'
OUTPUT_DIR = PROJECT_ROOT / 'output'
SCENES_DIR = PROJECT_ROOT / 'data' / 'scenes'
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SCENES_DIR, exist_ok=True)
sys.path.insert(0, str(PROJECT_ROOT))

COUNTER_PATH = PROJECT_ROOT / '.opencode_counter'
COMFYUI_OUTPUT = PROJECT_ROOT / 'ComfyUI' / 'output'

setup_status = {'done': False, 'comfyui': False, 'ollama': False, 'error': ''}
tasks = {}
tasks_lock = threading.RLock()
scenes_lock = threading.Lock()
image_counter = 0
counter_lock = threading.RLock()


def _load_counter():
    global image_counter
    with counter_lock:
        try:
            if COUNTER_PATH.exists():
                image_counter = int(COUNTER_PATH.read_text().strip())
                return
            max_img = 0
            for d in [OUTPUT_DIR / 'reverend_insanity', COMFYUI_OUTPUT / 'reverend_insanity']:
                if d.exists():
                    for p in d.glob('ch*_img_*.png'):
                        m = re.search(r'img_(\d+)', p.name)
                        if m:
                            max_img = max(max_img, int(m.group(1)))
            image_counter = max_img
        except Exception:
            image_counter = 0


def _save_counter():
    with counter_lock:
        COUNTER_PATH.write_text(str(image_counter))


_load_counter()


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

    def _ensure_hf_cli():
        try:
            subprocess.run(['hf', '--version'], capture_output=True, timeout=10)
        except:
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'huggingface-hub'], timeout=60)

    def _ensure_juggernaut():
        ckpt_dir = PROJECT_ROOT / 'ComfyUI' / 'models' / 'checkpoints'
        ckpt_path = ckpt_dir / 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'
        if ckpt_path.exists():
            return
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        _ensure_hf_cli()
        try:
            subprocess.run(
                ['hf', 'download', 'RunDiffusion/Juggernaut-XL-v9',
                 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors',
                 '--local-dir', str(ckpt_dir)],
                timeout=900, capture_output=True
            )
        except Exception as e:
            print(f'[auto_setup] Juggernaut download failed: {e}', flush=True)

    def _ensure_anima():
        pairs = [
            ('split_files/diffusion_models/anima-base-v1.0.safetensors',
             PROJECT_ROOT / 'ComfyUI' / 'models' / 'diffusion_models'),
            ('split_files/text_encoders/qwen_3_06b_base.safetensors',
             PROJECT_ROOT / 'ComfyUI' / 'models' / 'text_encoders'),
            ('split_files/vae/qwen_image_vae.safetensors',
             PROJECT_ROOT / 'ComfyUI' / 'models' / 'vae'),
        ]
        _ensure_hf_cli()
        for rel_path, dest_dir in pairs:
            fname = Path(rel_path).name
            dest_path = dest_dir / fname
            if dest_path.exists():
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.run(
                    ['hf', 'download', 'circlestone-labs/Anima', rel_path,
                     '--local-dir', '/tmp/anima_dl'],
                    timeout=900, capture_output=True
                )
                src = Path(f'/tmp/anima_dl/{rel_path}')
                if src.exists():
                    src.rename(dest_path)
                    print(f'[auto_setup] Downloaded {fname}', flush=True)
            except Exception as e:
                print(f'[auto_setup] Anima download failed for {fname}: {e}', flush=True)

    def _ensure_realvisxl():
        ckpt_dir = PROJECT_ROOT / 'ComfyUI' / 'models' / 'checkpoints'
        ckpt_path = ckpt_dir / 'RealVisXL_V5.0_fp16.safetensors'
        if ckpt_path.exists():
            return
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        _ensure_hf_cli()
        try:
            subprocess.run(
                ['hf', 'download', 'SG161222/RealVisXL_V5.0',
                 'RealVisXL_V5.0_fp16.safetensors',
                 '--local-dir', str(ckpt_dir)],
                timeout=900, capture_output=True
            )
        except Exception as e:
            print(f'[auto_setup] RealVisXL download failed: {e}', flush=True)

    def _ensure_flux():
        files = [
            ('flux1-dev-fp8.safetensors',
             PROJECT_ROOT / 'ComfyUI' / 'models' / 'unet',
             'Comfy-Org/flux1-dev'),
            ('t5xxl_fp8_e4m3fn.safetensors',
             PROJECT_ROOT / 'ComfyUI' / 'models' / 'clip',
             'comfyanonymous/flux_text_encoders'),
            ('clip_l.safetensors',
             PROJECT_ROOT / 'ComfyUI' / 'models' / 'clip',
             'comfyanonymous/flux_text_encoders'),
        ]
        _ensure_hf_cli()
        for fname, dest_dir, repo in files:
            dest_path = dest_dir / fname
            if dest_path.exists():
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.run(
                    ['hf', 'download', repo, fname, '--local-dir', str(dest_dir)],
                    timeout=1200, capture_output=True
                )
                if dest_path.exists():
                    print(f'[auto_setup] Downloaded Flux: {fname}', flush=True)
            except Exception as e:
                print(f'[auto_setup] Flux download failed for {fname}: {e}', flush=True)
        # Download Flux VAE (ae.safetensors) from ungated source
        vae_path = PROJECT_ROOT / 'ComfyUI' / 'models' / 'vae' / 'ae.safetensors'
        if not vae_path.exists():
            try:
                subprocess.run(
                    ['hf', 'download', 'diffusers/FLUX.1-vae',
                     'diffusion_pytorch_model.safetensors',
                     '--local-dir', '/tmp/flux_vae'],
                    timeout=300, capture_output=True
                )
                src = Path('/tmp/flux_vae/diffusion_pytorch_model.safetensors')
                if src.exists():
                    import shutil
                    shutil.copy2(src, vae_path)
                    print(f'[auto_setup] Downloaded Flux VAE (ae.safetensors)', flush=True)
            except Exception as e:
                print(f'[auto_setup] Flux VAE download failed: {e}', flush=True)

    def _ensure_ollama_model():
        try:
            r = requests.get(f'{ollama_url}/api/tags', timeout=3)
            if r.status_code == 200:
                setup_status['ollama'] = True
                model_name = ollama_cfg.get('model', 'qwen2.5:7b')
                tags = r.json().get('models', [])
                if not any(model_name in m['name'] for m in tags):
                    threading.Thread(target=lambda: os.system(f'ollama pull {model_name}'), daemon=True).start()
            else:
                model_name = ollama_cfg.get('model', 'qwen2.5:7b')
                threading.Thread(target=lambda: os.system(f'ollama pull {model_name}'), daemon=True).start()
        except:
            pass

    try:
        r = requests.get(f'{comfyui_url}/system_stats', timeout=5)
        if r.status_code == 200:
            setup_status['comfyui'] = True
    except:
        try:
            subprocess.Popen(
                [sys.executable, str(PROJECT_ROOT / 'ComfyUI' / 'main.py'), '--listen', '--port', '8188'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except:
            pass

    threading.Thread(target=_ensure_juggernaut, daemon=True).start()
    threading.Thread(target=_ensure_realvisxl, daemon=True).start()
    threading.Thread(target=_ensure_anima, daemon=True).start()
    threading.Thread(target=_ensure_flux, daemon=True).start()
    _ensure_ollama_model()

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
            total = result.get('total_chapters', 2000)
            chapter_id = result['first_chapter_id']
            chapters = []
            for i in range(1, chapter_end + 1):
                chap_url = f'https://www.webnovel.com/book/{result["book_id"]}/{chapter_id}'
                try:
                    chap_resp = cloudscraper.create_scraper().get(chap_url, timeout=30)
                    if i >= chapter_start:
                        csoup = BeautifulSoup(chap_resp.text, 'html.parser')
                        page_title = csoup.title.string.strip() if csoup.title else f'Chapter {i}'
                        page_title = re.sub(r'\s*-\s*WebNovel$', '', page_title)
                        chapters.append({'title': page_title, 'url': chap_url, 'id': chapter_id})
                    next_match = re.search(r'"nextChapterId"\s*:\s*"(\d+)"', chap_resp.text)
                    if not next_match:
                        break
                    chapter_id = next_match.group(1)
                except Exception:
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
        text = _fetch_chapter_text(url)
        if not text:
            # Fallback: try raw fetch with direct text extraction
            from fetchers.base import _get_session
            s = _get_session()
            r = s.get(url, timeout=30)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, 'html.parser')
            for sel in ['.cha-content', 'div.cha-page', 'div.j_page', '[class*="cha-page"]']:
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(separator='\n', strip=True)
                    break
            # Try JSON-embedded content
            if not text:
                import re
                matches = re.findall(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', r.text)
                if matches:
                    paragraphs = []
                    for cm in matches:
                        cm = cm.replace('\\/', '/').replace('\\"', '"').replace('\\n', '\n')
                        if '\\u' in cm:
                            cm = cm.encode('utf-8').decode('unicode_escape')
                        cm = re.sub(r'<[^>]+>', '', cm)
                        cm = cm.strip()
                        if cm:
                            paragraphs.append(cm)
                    if paragraphs:
                        text = '\n'.join(paragraphs)
        return jsonify({'text': text, 'url': url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/split-scenes', methods=['POST'])
def api_split_scenes():
    html = request.json.get('html', '').strip()
    url = request.json.get('url', '').strip()
    chapter_num = request.json.get('chapter_num', 1)
    chapter_title = request.json.get('chapter_title', f'Chapter {chapter_num}')

    config = load_config()
    ollama_cfg = config.get('ollama', {})
    ollama_url = ollama_cfg.get('url', 'http://127.0.0.1:11434')
    model = ollama_cfg.get('model', 'qwen2.5:7b')

    text = html
    if not text and url:
        try:
            text = _fetch_chapter_text(url)
        except Exception as e:
            print(f'[split-scenes] fetch_chapter_text error: {e}', flush=True)
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    prompt = f"""Analyze this chapter's narrative structure and split it into distinct scenes.

A SCENE is a continuous narrative unit where ALL of these stay the same:
1. Physical setting/location (a cave, a market, a courtyard)
2. Characters present (who is in the scene)
3. Time (continuous — no jumps forward or backward)
4. Dramatic focus (what the scene is about, the active goal)

A NEW SCENE starts when ANY of those changes: a new location, a character enters/leaves, time passes, or the topic/goal shifts entirely.

Rules:
- Every scene must have a clear dramatic purpose (not just "this happens")
- Scenes must be contiguous — no skipping parts of the text
- If the text describes two different things happening in different places, they are separate scenes
- Dialogues that shift topic or introduce new conflict are new scenes
- Be thorough: short transitions are valid scenes

For each scene, output:
- scene_number: sequential integer starting at 1
- summary: what happens AND why it matters (2-3 sentences: the action, the stakes, how it advances the story)
- text: the first 350 characters of that scene, copied verbatim from the input

Return ONLY valid JSON, nothing else:
{{"scenes": [{{"scene_number": 1, "summary": "...", "text": "..."}}]}}

Chapter {chapter_num}: {chapter_title}

Input text:
{text[:4000]}

JSON:"""

    try:
        resp = requests.post(
            f'{ollama_url}/api/generate',
            json={'model': model, 'prompt': prompt, 'stream': False},
            timeout=180,
        )
        if resp.status_code == 200:
            raw = resp.json().get('response', '')
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            raw = raw.strip()
            try:
                data = json.loads(raw)
                scenes = data.get('scenes', [])
                # Enrich each scene with context-aware prompt via Ollama
                for s in scenes:
                    s.setdefault('prompt', '')
                    s.setdefault('text', s.get('text', '') or s.get('start_line', ''))
                return jsonify({'scenes': scenes, 'chapter': chapter_num, 'title': chapter_title})
            except json.JSONDecodeError:
                pass
    except Exception:
        pass

    return jsonify({'scenes': [], 'chapter': chapter_num, 'title': chapter_title})


@app.route('/api/scenes', methods=['GET', 'POST'])
def api_scenes():
    scenes_file = SCENES_DIR / 'scenes.json'
    if request.method == 'POST':
        data = request.json
        if not isinstance(data, dict):
            return jsonify({'error': 'Payload must be a JSON object'}), 400
        if 'scenes' in data and not isinstance(data['scenes'], list):
            return jsonify({'error': 'scenes must be an array'}), 400
        with scenes_lock:
            with open(scenes_file, 'w') as f:
                json.dump(data, f, indent=2)
        return jsonify({'status': 'saved', 'count': len(data.get('scenes', []))})
    if scenes_file.exists():
        with open(scenes_file) as f:
            return jsonify(json.load(f))
    return jsonify({'story': '', 'chapters': [], 'scenes': [], 'current_chapter': 1})


@app.route('/api/enrich', methods=['POST'])
def api_enrich():
    text = request.json.get('text', '').strip()
    context = request.json.get('context', '')
    style = request.json.get('style', 'cinematic fantasy')
    model_name = request.json.get('model', 'juggernaut-xl')
    if not text:
        return jsonify({'error': 'Text is required'}), 400

    config = load_config()
    ollama_cfg = config.get('ollama', {})
    ollama_url = ollama_cfg.get('url', 'http://127.0.0.1:11434')
    model = ollama_cfg.get('model', 'qwen2.5:7b')

    ctx_blurb = ''
    if context:
        ctx_blurb = f'\n\nStory context (previous scenes):\n{context[:2000]}'

    if model_name == 'anima':
        prompt = f"""You are an expert Danbooru tagger and prompt engineer for the Anima anime model. Convert this story scene into detailed Danbooru-style tags and a natural language prompt.

Rules:
- Start with quality tags: "masterpiece, best quality, score_7, safe, newest, highres"
- Describe the scene with Danbooru tags: character appearance, action, setting, mood, camera angle
- Use lowercase, spaces instead of underscores, comma-separated tags
- Include artist/style tags: "@anonymous, animated, detailed background, cinematic lighting"
- End with a 1-2 sentence natural language description of the scene
- Maintain consistency with story context
- Art style: {style}
- Output ONLY the prompt, no labels or explanations
{ctx_blurb}

Scene:
{text[:2000]}

Enhanced prompt:"""
    elif model_name in ('flux-dev', 'flux'):
        prompt = f"""You are an expert prompt engineer for FLUX, the state-of-the-art image generation model. Convert this story scene into a detailed natural language prompt.

Rules:
- Write a descriptive paragraph (NOT comma-separated tags) — Flux works best with flowing natural language
- Describe: setting, lighting, mood, camera angle, character appearance, action, composition
- Use vivid sensory details (colors, textures, atmosphere)
- Include photographic/cinematic terms (e.g. "shot on 35mm film", "cinematic lighting", "shallow depth of field")
- Maintain consistency with story context
- Art style: {style}
- Output ONLY the prompt, no labels or explanations
- Keep it under 200 characters — Flux performs best with concise natural language
{ctx_blurb}

Scene:
{text[:2000]}

Enhanced prompt:"""
    else:
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
            return jsonify({'enriched': enriched, 'success': True})
    except Exception:
        pass

    return jsonify({'enriched': text, 'success': False})


def generate_next_image_id():
    global image_counter
    with counter_lock:
        image_counter += 1
        _save_counter()
        return f'img_{image_counter:06d}'


def build_workflow(model_name, prompt, negative, steps, cfg, width, height, filename, base_quality, guidance=None):
    models_config = {
        'juggernaut-xl': {
            'checkpoint': 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors',
            'prompt_template': '{base_quality}, {prompt}',
            'anime_tags': '',
        },
        'realvisxl': {
            'checkpoint': 'RealVisXL_V5.0_fp16.safetensors',
            'prompt_template': '{base_quality}, {prompt}',
            'anime_tags': '',
        },
        'anima': {
            'unet': 'anima-base-v1.0.safetensors',
            'clip': 'qwen_3_06b_base.safetensors',
            'clip_type': 'qwen_image',
            'vae': 'qwen_image_vae.safetensors',
            'prompt_template': 'masterpiece, best quality, score_7, safe, {prompt}',
            'anime_tags': ', newest, highres, anime screenshot, official art',
        },
        'flux-dev': {
            'unet': 'flux1-dev-fp8.safetensors',
            't5': 't5xxl_fp8_e4m3fn.safetensors',
            'clip_l': 'clip_l.safetensors',
            'vae': 'ae.safetensors',
            'prompt_template': '{prompt}',
            'default_steps': 30,
            'default_guidance': 3.5,
        },
    }

    name_lower = model_name.lower().replace(' ', '-')
    if name_lower == 'flux-dev' or name_lower == 'flux':
        model_key = 'flux-dev'
    elif name_lower == 'anima':
        model_key = 'anima'
    elif name_lower in models_config:
        model_key = name_lower
    else:
        model_key = 'juggernaut-xl'

    mcfg = models_config[model_key]
    full_prompt = mcfg['prompt_template'].format(base_quality=base_quality, prompt=prompt) + mcfg.get('anime_tags', '')
    seed = int(time.time() * 1000) % 2**32

    if model_key == 'flux-dev':
        g = guidance if guidance is not None else mcfg.get('default_guidance', 3.5)
        return {
            "1": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": mcfg['t5'], "clip_name2": mcfg['clip_l'], "type": "flux"}},
            "2": {"class_type": "UNETLoader", "inputs": {"unet_name": mcfg['unet'], "weight_dtype": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": mcfg['vae']}},
            "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "5": {"class_type": "CLIPTextEncodeFlux", "inputs": {"clip": ["1", 0], "clip_l": full_prompt[:1500], "t5xxl": full_prompt[:1500], "guidance": g}},
            "6": {"class_type": "CLIPTextEncodeFlux", "inputs": {"clip": ["1", 0], "clip_l": negative[:1500], "t5xxl": negative[:1500], "guidance": g}},
            "7": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler", "scheduler": "normal", "denoise": 1, "model": ["2", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["4", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": f'reverend_insanity/{filename.replace(".png","")}', "images": ["8", 0]}},
        }

    if model_key == 'anima':
        return {
            "1": {"class_type": "CLIPLoader", "inputs": {"clip_name": mcfg['clip'], "type": mcfg['clip_type']}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": full_prompt[:1500], "clip": ["1", 0]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative[:1500], "clip": ["1", 0]}},
            "4": {"class_type": "UNETLoader", "inputs": {"unet_name": mcfg['unet'], "weight_dtype": "default"}},
            "5": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["4", 0], "shift": 4.0}},
            "6": {"class_type": "VAELoader", "inputs": {"vae_name": mcfg['vae']}},
            "7": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "8": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "normal", "denoise": 1, "model": ["5", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["7", 0]}},
            "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["6", 0]}},
            "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": f'reverend_insanity/{filename.replace(".png","")}', "images": ["9", 0]}},
        }

    # SDXL models (Juggernaut XL, RealVisXL)
    return {
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
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
    guidance = request.json.get('guidance', None)

    workflow = build_workflow(model, prompt, negative, steps, cfg, width, height, filename, base_quality, guidance)

    task_id = uuid.uuid4().hex[:8]
    with tasks_lock:
        tasks[task_id] = {'status': 'queued', 'result': None, 'error': None, 'comfyui_prompt_id': None, 'cancel': False}

    def run():
        with tasks_lock:
            tasks[task_id]['status'] = 'running'
        try:
            resp = requests.post(f'{comfyui_url}/prompt', json={'prompt': workflow}, timeout=60)
            if resp.status_code != 200:
                with tasks_lock:
                    tasks[task_id]['status'] = 'failed'
                    tasks[task_id]['error'] = f'ComfyUI error: {resp.text[:200]}'
                return
            result_data = resp.json()
            prompt_id = result_data.get('prompt_id', '')
            with tasks_lock:
                tasks[task_id]['comfyui_prompt_id'] = prompt_id

            for _ in range(120):
                with tasks_lock:
                    if tasks[task_id].get('cancel'):
                        try:
                            requests.post(f'{comfyui_url}/interrupt', timeout=5)
                        except:
                            pass
                        tasks[task_id]['status'] = 'cancelled'
                        tasks[task_id]['error'] = 'Cancelled by user'
                        return
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
                                if src_path.exists():
                                    if src_path != dst_path:
                                        if dst_path.exists():
                                            dst_path.unlink()
                                        src_path.rename(dst_path)
                                    img_path = f'/output/{dst_name}'
                                images.append(img_path)
                        if images:
                            with tasks_lock:
                                tasks[task_id]['status'] = 'completed'
                                tasks[task_id]['result'] = images
                                tasks[task_id]['_completed_at'] = time.time()
                            return
                except:
                    pass
            with tasks_lock:
                tasks[task_id]['status'] = 'failed'
                tasks[task_id]['error'] = 'Timeout waiting for image'
        except Exception as e:
            with tasks_lock:
                tasks[task_id]['status'] = 'failed'
                tasks[task_id]['error'] = str(e)

    t = threading.Thread(target=run, daemon=True)
    t.start()

    return jsonify({'task_id': task_id, 'filename': filename, 'model': model})

# Schedule periodic task cleanup
def _cleanup_old_tasks():
    while True:
        time.sleep(600)
        cutoff = time.time() - 600
        with tasks_lock:
            stale = [tid for tid, t in list(tasks.items())
                     if t.get('_completed_at', float('inf')) < cutoff]
            for tid in stale:
                del tasks[tid]

threading.Thread(target=_cleanup_old_tasks, daemon=True).start()


@app.route('/api/task/<task_id>')
def api_task(task_id):
    with tasks_lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify({'error': 'Task not found'}), 404
        return jsonify({
            'status': task['status'],
            'result': task.get('result'),
            'error': task.get('error'),
    })


@app.route('/api/cancel-task/<task_id>', methods=['POST'])
def api_cancel_task(task_id):
    with tasks_lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify({'error': 'Task not found'}), 404
        if task['status'] in ('completed', 'failed', 'cancelled'):
            return jsonify({'status': task['status'], 'message': 'Task already finished'})
        task['cancel'] = True
        prompt_id = task.get('comfyui_prompt_id')
    if prompt_id:
        try:
            comfyui_url = load_config().get('comfyui', {}).get('url', 'http://127.0.0.1:8188')
            requests.post(f'{comfyui_url}/interrupt', timeout=5)
        except:
            pass
    return jsonify({'status': 'cancelling'})


AVAILABLE_MODELS = [
    {'id': 'flux-dev', 'name': 'Flux.1 Dev fp8 (Best Quality)', 'type': 'flux'},
    {'id': 'juggernaut-xl', 'name': 'Juggernaut XL v9 (Photorealistic)', 'type': 'sdxl'},
    {'id': 'realvisxl', 'name': 'RealVisXL V5.0 (Photorealistic)', 'type': 'sdxl'},
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
    videos = []

    for base_dir in [OUTPUT_DIR, COMFYUI_OUTPUT]:
        ri = base_dir / 'reverend_insanity'
        if ri.exists():
            for png in sorted(ri.glob('*.png')):
                if png.name.startswith('anim_') and '_f' in png.name:
                    continue  # skip animation frame intermediates
                url = f'/output/reverend_insanity/{png.name}'
                if url not in images:
                    images.append(url)
            for vid in sorted(ri.glob('*.gif')) + sorted(ri.glob('*.mp4')):
                url = f'/output/reverend_insanity/{vid.name}'
                if url not in videos:
                    videos.append(url)

    for png in sorted(OUTPUT_DIR.glob('**/*.png')):
        rel = str(png.relative_to(OUTPUT_DIR))
        url = f'/output/{rel}'
        if url not in images:
            images.append(url)

    return jsonify({'images': images, 'videos': videos})


@app.route('/api/export-scenes')
def api_export_scenes():
    scenes_file = SCENES_DIR / 'scenes.json'
    if scenes_file.exists():
        with open(scenes_file) as f:
            data = json.load(f)
        return jsonify(data)
    return jsonify({'story': '', 'chapters': [], 'scenes': [], 'current_chapter': 1})


@app.route('/api/download-zip')
def api_download_zip():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for d in [COMFYUI_OUTPUT, OUTPUT_DIR]:
            if d.exists():
                for png in sorted(d.rglob('*.png')):
                    arcname = str(png.relative_to(d.parent))
                    zf.write(png, arcname)
    buf.seek(0)
    return buf.getvalue(), 200, {'Content-Type': 'application/zip', 'Content-Disposition': 'attachment; filename=images.zip'}


@app.route('/api/reset-counter', methods=['POST'])
def api_reset_counter():
    with counter_lock:
        global image_counter
        image_counter = 0
        _save_counter()
    return jsonify({'counter': image_counter})


@app.route('/api/animate', methods=['POST'])
def api_animate():
    prompt = request.json.get('prompt', '').strip()
    negative = request.json.get('negative', '')
    steps = request.json.get('steps', 20)
    cfg = request.json.get('cfg', 7.0)
    width = request.json.get('width', 1216)
    height = request.json.get('height', 832)
    chapter = request.json.get('chapter', 1)
    scene = request.json.get('scene', 1)
    model = request.json.get('model', 'juggernaut-xl')
    frames = min(request.json.get('frames', 8), 16)
    guidance = request.json.get('guidance', None)

    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400

    config = load_config()
    comfyui_url = config.get('comfyui', {}).get('url', 'http://127.0.0.1:8188')
    neg_prompt = config.get('prompts', {}).get('negative_prompt', 'blurry, low quality, bad anatomy')
    base_quality = config.get('prompts', {}).get('base_quality', 'masterpiece, best quality, highly detailed, cinematic lighting, 8k')
    negative = negative or neg_prompt

    task_id = uuid.uuid4().hex[:8]
    with tasks_lock:
        tasks[task_id] = {'status': 'queued', 'result': None, 'error': None, 'cancel': False}

    def run():
        with tasks_lock:
            tasks[task_id]['status'] = 'running'
        try:
            # Use a temp counter that doesn't affect the main image_counter
            anim_serial = int(time.time() * 1000) % 100000
            frame_paths = []
            ri_out = COMFYUI_OUTPUT / 'reverend_insanity'
            ri_out.mkdir(parents=True, exist_ok=True)
            anim_name = f'anim_ch{chapter:04d}_sc{scene:04d}_{anim_serial:05d}'

            for f_idx in range(frames):
                with tasks_lock:
                    if tasks[task_id].get('cancel'):
                        try:
                            requests.post(f'{comfyui_url}/interrupt', timeout=5)
                        except:
                            pass
                        tasks[task_id]['status'] = 'cancelled'
                        tasks[task_id]['error'] = 'Cancelled by user'
                        return

                prefix = f'reverend_insanity/{anim_name}_f{f_idx:03d}'
                workflow = build_workflow(
                    model, prompt, negative, steps, cfg, width, height,
                    f'{anim_name}_f{f_idx:03d}.png', base_quality, guidance
                )
                # Vary seed for each frame
                for node_id, node in workflow.items():
                    if isinstance(node, dict) and node.get('class_type') == 'KSampler':
                        node['inputs']['seed'] = int(time.time() * 1000) % 2**32 + f_idx * 31337

                resp = requests.post(f'{comfyui_url}/prompt', json={'prompt': workflow}, timeout=120)
                if resp.status_code != 200:
                    continue
                prompt_id = resp.json().get('prompt_id', '')

                # Wait for image - longer timeout for T4
                found = None
                for _ in range(180):
                    time.sleep(2)
                    try:
                        hr = requests.get(f'{comfyui_url}/history/{prompt_id}', timeout=5)
                        if hr.status_code == 200:
                            hist = hr.json()
                            outputs = hist.get(prompt_id, {}).get('outputs', {})
                            for node_id, node_out in outputs.items():
                                for img_data in node_out.get('images', []):
                                    src = COMFYUI_OUTPUT / img_data.get('subfolder', '') / img_data.get('filename', '')
                                    if src.exists():
                                        dst = ri_out / f'{anim_name}_f{f_idx:03d}.png'
                                        if src != dst:
                                            src.rename(dst)
                                        found = str(dst)
                                        break
                                if found:
                                    break
                        if found:
                            break
                    except:
                        pass

                if found:
                    frame_paths.append(found)
                else:
                    print(f'[animate] Frame {f_idx} timed out', flush=True)

            if len(frame_paths) < 2:
                with tasks_lock:
                    tasks[task_id]['status'] = 'failed'
                    tasks[task_id]['error'] = f'Only {len(frame_paths)} frames generated'
                return

            # Stitch into GIF (universal browser support, no encoder deps)
            video_name = f'{anim_name}.gif'
            video_path = str(ri_out / video_name)
            palette_path = str(ri_out / f'{video_name}.palette.png')
            import subprocess as sp
            # Generate palette for better quality
            sp.run([
                'ffmpeg', '-y', '-framerate', '4',
                '-pattern_type', 'glob',
                '-i', f'{str(ri_out)}/{anim_name}_f*.png',
                '-vf', 'palettegen=stats_mode=diff',
                palette_path
            ], capture_output=True, timeout=60)
            sp.run([
                'ffmpeg', '-y', '-framerate', '4',
                '-pattern_type', 'glob',
                '-i', f'{str(ri_out)}/{anim_name}_f*.png',
                '-i', palette_path,
                '-lavfi', 'paletteuse=dither=bayer',
                video_path
            ], capture_output=True, timeout=60)
            Path(palette_path).unlink(missing_ok=True)
            # Clean up animation frame PNGs
            for fp in ri_out.glob(f'{anim_name}_f*.png'):
                fp.unlink(missing_ok=True)

            rel_path = f'/output/reverend_insanity/{video_name}'
            with tasks_lock:
                tasks[task_id]['status'] = 'completed'
                tasks[task_id]['result'] = [rel_path]
                tasks[task_id]['_completed_at'] = time.time()
        except Exception as e:
            with tasks_lock:
                tasks[task_id]['status'] = 'failed'
                tasks[task_id]['error'] = str(e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return jsonify({'task_id': task_id})


@app.route('/api/delete-image', methods=['POST'])
def api_delete_image():
    url = request.json.get('url', '')
    if not url:
        return jsonify({'error': 'URL required'}), 400
    filename = url.split('/')[-1]
    if not (filename.endswith('.png') or filename.endswith('.mp4') or filename.endswith('.gif')):
        return jsonify({'error': 'Only PNG, MP4 and GIF files'}), 400
    deleted = []
    for d in [OUTPUT_DIR / 'reverend_insanity', COMFYUI_OUTPUT / 'reverend_insanity']:
        p = d / filename
        if p.exists():
            p.unlink()
            deleted.append(str(p))
        # Also clean up animation frame intermediates
        stem = Path(filename).stem
        for ext in ['.png', '.gif']:
            for f in d.glob(f'{stem}*{ext}'):
                if f.exists():
                    f.unlink()
                    deleted.append(str(f))
    return jsonify({'deleted': deleted})


auto_setup()

if __name__ == '__main__':
    port = int(os.environ.get('FLASK_PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
