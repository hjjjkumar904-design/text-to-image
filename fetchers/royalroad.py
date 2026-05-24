from bs4 import BeautifulSoup
from urllib.parse import urljoin

import cloudscraper


def _fresh_session():
    return cloudscraper.create_scraper()


def scrape_royalroad(url: str) -> dict:
    for attempt in range(3):
        try:
            s = _fresh_session()
            resp = s.get(url, timeout=30)
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
        except Exception as e:
            if attempt == 2:
                return {'title': 'Unknown Story', 'chapters': [], 'error': str(e)}
    return {'title': 'Unknown Story', 'chapters': []}


def fetch_royalroad_chapter_text(url: str) -> str:
    for attempt in range(3):
        try:
            s = _fresh_session()
            resp = s.get(url, timeout=30)
            soup = BeautifulSoup(resp.text, 'html.parser')
            content = soup.select_one('.chapter-content')
            if content:
                for tag in content.find_all(['script', 'style']):
                    tag.decompose()
                return content.get_text(separator='\n', strip=True)
            return ''
        except Exception:
            if attempt == 2:
                return ''
    return ''
