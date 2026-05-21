#!/usr/bin/env python3
"""Batch process Reverend Insanity chapters: scrape -> scenes -> enrich -> generate images"""

import cloudscraper
import json
import os
import re
import sys
import time
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output', 'reverend_insanity')
os.makedirs(OUTPUT_DIR, exist_ok=True)

COMFYUI_URL = 'http://127.0.0.1:8188'
OLLAMA_URL = 'http://127.0.0.1:11434'

BOOK_ID = '7996858406002505'
FIRST_CHAPTER_ID = '21533585005668024'
MAX_CHAPTERS = 10


def get_chapter_text(session, chapter_id):
    url = f'https://www.webnovel.com/book/{BOOK_ID}/{chapter_id}'
    r = session.get(url, timeout=30)
    soup = BeautifulSoup(r.text, 'html.parser')
    
    content_el = soup.select_one('.cha-content')
    if not content_el:
        print(f'  WARNING: No .cha-content found')
        return None, None
    
    text = content_el.get_text(separator='\n', strip=True)
    
    # Extract next chapter ID
    match = re.search(r'"nextChapterId"\s*:\s*"(\d+)"', r.text)
    next_id = match.group(1) if match else None
    
    return text, next_id


def split_into_scenes(text):
    scenes = []
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    
    current_scene = []
    for p in paragraphs:
        current_scene.append(p)
        if len(current_scene) >= 5:
            scenes.append('\n'.join(current_scene))
            current_scene = []
    
    if current_scene:
        scenes.append('\n'.join(current_scene))
    
    return scenes if scenes else [text]


def enrich_prompt(scene_text):
    prompt = (
        f'Transform this story scene into a detailed Stable Diffusion XL prompt. '
        f'Describe the characters, setting, lighting, mood, camera angle, art style. '
        f'Return ONLY the prompt text, no explanations.\n\nScene: {scene_text}'
    )
    try:
        r = requests.post(
            f'{OLLAMA_URL}/api/generate',
            json={'model': 'qwen2.5:7b', 'prompt': prompt, 'stream': False},
            timeout=60
        )
        if r.status_code == 200:
            enriched = r.json().get('response', '').strip()
            if enriched:
                return enriched
    except Exception as e:
        print(f'  Ollama error: {e}')
    
    # Fallback: create a basic prompt from the text
    return f'masterpiece, best quality, {scene_text[:300]}, cinematic lighting, fantasy art, 8k'


def generate_image(prompt, negative, chapter_num, scene_num):
    payload = {
        'prompt': prompt[:1000],
        'negative': negative,
        'steps': 20,
        'cfg': 7.5,
        'width': 832,
        'height': 1216,
    }
    try:
        r = requests.post(f'{COMFYUI_URL}/prompt', json={'prompt': payload}, timeout=30)
        if r.status_code == 200:
            task_id = r.json().get('task_id', '')
            return task_id
    except Exception as e:
        print(f'  Generation error: {e}')
    return None


def wait_for_image(task_id, timeout=120):
    for i in range(timeout):
        try:
            r = requests.get(f'http://127.0.0.1:5000/api/task/{task_id}', timeout=10)
            data = r.json()
            if data.get('status') == 'completed':
                return data.get('result', [])
            elif data.get('status') == 'failed':
                return None
        except:
            pass
        time.sleep(2)
    return None


def process_chapters():
    session = cloudscraper.create_scraper()
    
    chapter_id = FIRST_CHAPTER_ID
    all_results = []
    
    for ch in range(1, MAX_CHAPTERS + 1):
        print(f'\n{"="*60}')
        print(f'Chapter {ch}')
        print(f'{"="*60}')
        
        text, next_id = get_chapter_text(session, chapter_id)
        if not text:
            print(f'  FAILED to get chapter text')
            break
        
        print(f'  Text length: {len(text)} chars')
        
        # Save raw text
        ch_dir = os.path.join(OUTPUT_DIR, f'chapter_{ch:04d}')
        os.makedirs(ch_dir, exist_ok=True)
        with open(os.path.join(ch_dir, 'text.txt'), 'w', encoding='utf-8') as f:
            f.write(text)
        
        # Split into scenes
        scenes = split_into_scenes(text)
        print(f'  Scenes: {len(scenes)}')
        
        chapter_images = []
        for si, scene in enumerate(scenes):
            print(f'\n  Scene {si+1}/{len(scenes)} (text: {len(scene)} chars)')
            
            # Enrich with Ollama
            enriched = enrich_prompt(scene)
            print(f'    Enriched prompt: {enriched[:80]}...')
            
            # Save to file
            with open(os.path.join(ch_dir, f'scene_{si+1:03d}.txt'), 'w', encoding='utf-8') as f:
                f.write(f'Original:\n{scene}\n\nEnriched:\n{enriched}')
            
            # Generate image
            negative = 'blurry, low quality, bad anatomy, distorted face, extra limbs, watermark, text, signature, deformed, ugly, poorly drawn, out of frame'
            
            # For now, just print what we would do
            print(f'    Ready to generate image for scene {si+1}')
            chapter_images.append({
                'scene': si + 1,
                'text': scene[:100],
                'prompt': enriched,
            })
        
        all_results.append({
            'chapter': ch,
            'chapter_id': chapter_id,
            'scenes': len(scenes),
            'images': chapter_images,
        })
        
        # Save chapter metadata
        with open(os.path.join(ch_dir, 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump({'chapter': ch, 'chapter_id': chapter_id, 'scenes': len(scenes)}, f, indent=2)
        
        if not next_id:
            print(f'  No next chapter found, stopping')
            break
        
        chapter_id = next_id
    
    # Save full results
    with open(os.path.join(OUTPUT_DIR, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    
    print(f'\n{"="*60}')
    print(f'Done! Processed {len(all_results)} chapters')
    print(f'Results saved to {OUTPUT_DIR}')
    return all_results


if __name__ == '__main__':
    process_chapters()
