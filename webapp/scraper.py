import re
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup


CHAPTER_PATTERNS = [
    re.compile(r'chapter\s+\d+', re.IGNORECASE),
    re.compile(r'ch\.?\s*\d+', re.IGNORECASE),
    re.compile(r'page\s+\d+', re.IGNORECASE),
]


def detect_site(url: str) -> str:
    hostname = urlparse(url).hostname or ''
    if 'royalroad' in hostname:
        return 'royalroad'
    if 'scribblehub' in hostname:
        return 'scribblehub'
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
    resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(resp.text, 'html.parser')
    for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer']):
        tag.decompose()
    for selector in ['article', '.chapter-content', '.entry-content', '.story-content', 'main', '#chapter-content']:
        content = soup.select_one(selector)
        if content:
            return content.get_text(separator='\n', strip=True)
    return soup.get_text(separator='\n', strip=True)[:10000]


def scrape_webnovel(url: str) -> dict:
    site = detect_site(url)
    if site == 'royalroad':
        return scrape_royalroad(url)
    elif site == 'scribblehub':
        return scrape_scribblehub(url)
    else:
        return scrape_generic(url)
