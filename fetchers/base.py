import re
from urllib.parse import urlparse

import cloudscraper

CHAPTER_PATTERNS = [
    re.compile(r'chapter\s+\d+', re.IGNORECASE),
    re.compile(r'ch\.?\s*\d+', re.IGNORECASE),
    re.compile(r'page\s+\d+', re.IGNORECASE),
]


def _get_session():
    """Always return a fresh session to avoid stale-session Cloudflare blocks."""
    return cloudscraper.create_scraper()


def _get_fresh_session():
    """Alias for _get_session — kept for backward compat."""
    return cloudscraper.create_scraper()


def detect_site(url: str) -> str:
    hostname = urlparse(url).hostname or ''
    if 'royalroad' in hostname:
        return 'royalroad'
    if 'scribblehub' in hostname:
        return 'scribblehub'
    if 'webnovel' in hostname:
        return 'webnovel'
    if 'novel' in hostname:
        return 'generic'
    return 'generic'
