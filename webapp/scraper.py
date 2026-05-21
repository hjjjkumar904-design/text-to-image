import re
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

import cloudscraper


CHAPTER_PATTERNS = [
    re.compile(r'chapter\s+\d+', re.IGNORECASE),
    re.compile(r'ch\.?\s*\d+', re.IGNORECASE),
    re.compile(r'page\s+\d+', re.IGNORECASE),
]

CS = None


def _get_session():
    global CS
    if CS is None:
        CS = cloudscraper.create_scraper()
    return CS


def detect_site(url: str) -> str:
    hostname = urlparse(url).hostname or ''
    if 'royalroad' in hostname:
        return 'royalroad'
    if 'scribblehub' in hostname:
        return 'scribblehub'
    if 'webnovel' in hostname:
        return 'webnovel'
    if 'novel' in hostname:
        return 'generic_novel'
    return 'generic'


def scrape_royalroad(url: str) -> dict:
    resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(resp.text, 'html.parser')
    title = soup.select_one('h1.font-white')
    title_text = title.get_text(strip=True) if title else 'Unknown Story'
    chapter_items = soup.select('table#chapters tr')
    chapters = []
    for row in chapter_items:
        link = row.select_one('a')
        if link:
            href = urljoin(url, link.get('href', ''))
            chap_title = link.get_text(strip=True)
            if href and chap_title:
                chapters.append({'title': chap_title, 'url': href})
    return {'title': title_text, 'chapters': chapters}


def scrape_scribblehub(url: str) -> dict:
    resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(resp.text, 'html.parser')
    title = soup.select_one('.fic_title')
    title_text = title.get_text(strip=True) if title else 'Unknown Story'
    chapter_links = soup.select('a.tiptip[href*="/chapter/"]')
    chapters = []
    for link in chapter_links:
        href = urljoin(url, link.get('href', ''))
        chap_title = link.get_text(strip=True)
        if href and chap_title:
            chapters.append({'title': chap_title, 'url': href})
    return {'title': title_text, 'chapters': chapters}


def scrape_webnovel_com(url: str) -> dict:
    s = _get_session()
    r = s.get(url, timeout=30)
    soup = BeautifulSoup(r.text, 'html.parser')

    title_el = soup.select_one('h1[class*="title"]')
    title = title_el.get_text(strip=True) if title_el else (soup.title.string.strip() if soup.title else 'Unknown')

    book_id_match = re.search(r'_(\d+)$', urlparse(url).path.rstrip('/'))
    book_id = book_id_match.group(1) if book_id_match else ''

    match = re.search(r'"firstChapterId"\s*:\s*"(\d+)"', r.text)
    first_chapter_id = match.group(1) if match else None

    match_count = re.search(r'"chapterNum"\s*:\s*(\d+)', r.text)
    total_chapters = int(match_count.group(1)) if match_count else 2000

    chapters = []
    if first_chapter_id:
        chapter_id = first_chapter_id
        # Only fetch first few to get chapter name pattern, then extrapolate
        names_url = f'https://www.webnovel.com/book/{book_id}/{chapter_id}'
        nr = s.get(names_url, timeout=30)
        nsoup = BeautifulSoup(nr.text, 'html.parser')
        first_title = nsoup.title.string.strip() if nsoup.title else f'Chapter 1'
        first_title = re.sub(r'\s*-\s*WebNovel$', '', first_title)
        chapters.append({'title': first_title, 'url': names_url, 'id': chapter_id})

    return {'title': title, 'chapters': chapters, 'book_id': book_id, 'total_chapters': total_chapters, 'first_chapter_id': first_chapter_id}


def scrape_generic(url: str) -> dict:
    resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(resp.text, 'html.parser')
    title = soup.title.get_text(strip=True) if soup.title else 'Unknown Story'
    chapters = []
    for a in soup.find_all('a', href=True):
        text = a.get_text(strip=True)
        href = a['href']
        if any(p.search(text) for p in CHAPTER_PATTERNS):
            full_url = urljoin(url, href)
            chapters.append({'title': text, 'url': full_url})
    return {'title': title, 'chapters': chapters}


def fetch_chapter_text(url: str) -> str:
    site = detect_site(url)
    if site == 'webnovel':
        return fetch_webnovel_chapter_text(url)
    resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(resp.text, 'html.parser')
    for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer']):
        tag.decompose()
    for selector in ['article', '.chapter-content', '.entry-content', '.story-content', 'main', '#chapter-content']:
        content = soup.select_one(selector)
        if content:
            return content.get_text(separator='\n', strip=True)
    return soup.get_text(separator='\n', strip=True)[:10000]


def fetch_webnovel_chapter_text(url: str) -> str:
    s = _get_session()
    r = s.get(url, timeout=30)
    soup = BeautifulSoup(r.text, 'html.parser')
    content = soup.select_one('.cha-content')
    if content:
        return content.get_text(separator='\n', strip=True)
    return ''


def scrape_webnovel(url: str) -> dict:
    site = detect_site(url)
    if site == 'royalroad':
        return scrape_royalroad(url)
    elif site == 'scribblehub':
        return scrape_scribblehub(url)
    elif site == 'webnovel':
        return scrape_webnovel_com(url)
    else:
        return scrape_generic(url)
