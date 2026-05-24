import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from .base import CHAPTER_PATTERNS


def _get_session():
    return cloudscraper.create_scraper()


def scrape_generic(url: str) -> dict:
    for attempt in range(3):
        try:
            resp = _get_session().get(url, timeout=30)
            break
        except Exception:
            if attempt == 2:
                return {'error': f'Failed to fetch {url}', 'title': 'Unknown Story', 'chapters': []}
    else:
        return {'error': f'Failed to fetch {url}', 'title': 'Unknown Story', 'chapters': []}
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


def fetch_generic_chapter_text(url: str) -> str:
    for attempt in range(3):
        try:
            resp = _get_session().get(url, timeout=30)
            break
        except Exception:
            if attempt == 2:
                return ''
    else:
        return ''
    soup = BeautifulSoup(resp.text, 'html.parser')
    for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer']):
        tag.decompose()
    for selector in ['article', '.chapter-content', '.entry-content', '.story-content', 'main', '#chapter-content']:
        content = soup.select_one(selector)
        if content:
            return content.get_text(separator='\n', strip=True)
    return soup.get_text(separator='\n', strip=True)[:10000]
