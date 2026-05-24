#!/usr/bin/env python3
"""Full pipeline: scrape webnovel chapters, enrich, generate images"""

import cloudscraper
import json
import os
import re
import sys
import time
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output', 'reverend_insanity')
os.makedirs(OUTPUT_DIR, exist_ok=True)

BOOK_ID = '7996858406002505'
FIRST_CHAPTER_ID = '21533585005668024'
MAX_CHAPTERS = 5
FLASK_URL = 'http://127.0.0.1:5000'


def get_chapter_text(session, chapter_id):
    url = f'https://www.webnovel.com/book/{BOOK_ID}/{chapter_id}'
    r = session.get(url, timeout=30)
    soup = BeautifulSoup(r.text, 'html.parser')

    title_el = soup.select_one('h1[class*="title"]')
    title = title_el.get_text(strip=True) if title_el else (soup.title.string.strip() if soup.title else f'Chapter')

    content_el = soup.select_one('.cha-content')
    if not content_el:
        return None, None, title

    text = content_el.get_text(separator='\n', strip=True)
    match = re.search(r'"nextChapterId"\s*:\s*"(\d+)"', r.text)
    next_id = match.group(1) if match else None
    return text, next_id, title


def split_into_scenes(text):
    scenes = []
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    current = []
    for p in paragraphs:
        current.append(p)
        if len(current) >= 5:
            scenes.append('\n'.join(current))
            current = []
    if current:
        scenes.append('\n'.join(current))
    return scenes if scenes else [text]


def enrich_via_flask(scene_text):
    try:
        r = requests.post(f'{FLASK_URL}/api/enrich',
                          json={'text': scene_text}, timeout=120)
        data = r.json()
        return data.get('enriched', scene_text)
    except Exception as e:
        print(f'    Enrich error: {e}')
        return f'masterpiece, best quality, {scene_text[:300]}, cinematic lighting, fantasy art, detailed, 8k'


def generate_via_flask(prompt, negative):
    try:
        r = requests.post(f'{FLASK_URL}/api/generate', json={
            'prompt': prompt[:1500],
            'negative': negative,
            'steps': 20,
            'cfg': 7.5,
            'width': 832,
            'height': 1216,
        }, timeout=30)
        data = r.json()
        return data.get('task_id')
    except Exception as e:
        print(f'    Generate error: {e}')
        return None


def poll_task(task_id, timeout=180):
    for i in range(timeout):
        try:
            r = requests.get(f'{FLASK_URL}/api/task/{task_id}', timeout=10)
            data = r.json()
            if data.get('status') == 'completed':
                return data.get('result', [])
            if data.get('status') == 'failed':
                return None
        except:
            pass
        time.sleep(2)
    return None


def process():
    session = cloudscraper.create_scraper()
    chapter_id = FIRST_CHAPTER_ID
    negative = 'blurry, low quality, bad anatomy, distorted face, extra limbs, watermark, text, signature, deformed, ugly, poorly drawn, out of frame'
    all_data = []

    for ch in range(1, MAX_CHAPTERS + 1):
        print(f'\n{"="*60}')
        print(f'Chapter {ch}')
        print(f'{"="*60}')

        text, next_id, title = get_chapter_text(session, chapter_id)
        if not text:
            print(f'  FAILED to get text')
            break

        print(f'  Title: {title}')
        print(f'  Text: {len(text)} chars')

        ch_dir = os.path.join(OUTPUT_DIR, f'chapter_{ch:04d}')
        os.makedirs(ch_dir, exist_ok=True)

        # Save raw
        with open(os.path.join(ch_dir, 'text.txt'), 'w', encoding='utf-8') as f:
            f.write(text)

        scenes = split_into_scenes(text)
        print(f'  Scenes: {len(scenes)}')

        chapter_data = {'chapter': ch, 'title': title, 'scenes': []}

        for si, scene_text in enumerate(scenes):
            print(f'\n  [{ch}.{si+1}] ({len(scene_text)} chars)')

            enriched = enrich_via_flask(scene_text)
            print(f'    Enriched: {enriched[:60]}...')

            task_id = generate_via_flask(enriched, negative)
            if task_id:
                print(f'    Task: {task_id}')
                result = poll_task(task_id)
                if result:
                    print(f'    Done: {result}')
                    chapter_data['scenes'].append({
                        'scene': si + 1,
                        'text': scene_text[:200],
                        'prompt': enriched,
                        'images': result,
                    })
                else:
                    print(f'    Failed/Timed out')
            else:
                print(f'    Failed to queue')

        all_data.append(chapter_data)

        # Save chapter data
        with open(os.path.join(ch_dir, 'data.json'), 'w', encoding='utf-8') as f:
            json.dump(chapter_data, f, indent=2, ensure_ascii=False)

        if not next_id:
            break
        chapter_id = next_id

    # Save full results
    with open(os.path.join(OUTPUT_DIR, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

    print(f'\nDone! {len(all_data)} chapters processed.')
    return all_data


if __name__ == '__main__':
    process()
