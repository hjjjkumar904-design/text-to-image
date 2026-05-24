import re
from urllib.parse import urlparse

import cloudscraper
from bs4 import BeautifulSoup


def scrape_webnovel(url: str) -> dict:
    s = cloudscraper.create_scraper()
    r = s.get(url, timeout=30)
    soup = BeautifulSoup(r.text, 'html.parser')

    title_el = soup.select_one('h1[class*="title"]')
    title = title_el.get_text(strip=True) if title_el else (soup.title.string.strip() if soup.title else 'Unknown')

    path = urlparse(url).path.rstrip('/')
    parts = path.split('/')
    book_id = ''
    for p in reversed(parts):
        if p.isdigit():
            if not book_id:
                book_id = p  # last number = chapter_id (skip)
            else:
                book_id = p  # second-to-last = book_id
                break

    match = re.search(r'"firstChapterId"\s*:\s*"(\d+)"', r.text)
    first_chapter_id = match.group(1) if match else None

    match_count = re.search(r'"chapterNum"\s*:\s*(\d+)', r.text)
    total_chapters = int(match_count.group(1)) if match_count else 2000

    chapters = []
    if first_chapter_id:
        names_url = f'https://www.webnovel.com/book/{book_id}/{first_chapter_id}'
        nr = cloudscraper.create_scraper().get(names_url, timeout=30)
        nsoup = BeautifulSoup(nr.text, 'html.parser')
        first_title = nsoup.title.string.strip() if nsoup.title else 'Chapter 1'
        first_title = re.sub(r'\s*-\s*WebNovel$', '', first_title)
        chapters.append({'title': first_title, 'url': names_url, 'id': first_chapter_id})

    return {
        'title': title,
        'chapters': chapters,
        'book_id': book_id,
        'total_chapters': total_chapters,
        'first_chapter_id': first_chapter_id,
    }


def fetch_webnovel_chapter_text(url: str) -> str:
    for attempt in range(3):
        s = cloudscraper.create_scraper()
        try:
            r = s.get(url, timeout=45)
        except Exception:
            continue
        soup = BeautifulSoup(r.text, 'html.parser')
        for sel in ['.cha-content', 'div.cha-page', 'div.j_page', '[class*="cha-page"]']:
            content = soup.select_one(sel)
            if content:
                text = content.get_text(separator='\n', strip=True)
                lines = text.split('\n')
                start = 0
                for i, line in enumerate(lines):
                    if re.match(r'^(Chapter|Ch\.)\s+\d+|^"', line):
                        start = i
                        break
                text = '\n'.join(lines[start:])
                text = re.sub(r'^Chapter\s+\d+[:\-–—\s]*.*?(?:\n|$)', '', text).strip()
                if text:
                    return text
        # Fallback: extract from JSON-embedded content fields
        content_matches = re.findall(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', r.text)
        if content_matches:
            paragraphs = []
            for cm in content_matches:
                cm = cm.replace('\\/', '/').replace('\\"', '"').replace('\\n', '\n')
                cm = cm.encode('utf-8').decode('unicode_escape') if '\\u' in cm else cm
                cm = re.sub(r'<[^>]+>', '', cm)
                cm = cm.strip()
                if cm:
                    paragraphs.append(cm)
            if paragraphs:
                text = '\n'.join(paragraphs)
                text = re.sub(r'^Chapter\s+\d+[:\-–—\s]*.*?(?:\n|$)', '', text).strip()
                if text:
                    return text
    return ''
