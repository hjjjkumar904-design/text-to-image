from .webnovel import scrape_webnovel, fetch_webnovel_chapter_text
from .royalroad import scrape_royalroad, fetch_royalroad_chapter_text
from .scribblehub import scrape_scribblehub, fetch_scribblehub_chapter_text
from .generic import scrape_generic, fetch_generic_chapter_text
from .base import detect_site, CHAPTER_PATTERNS, _get_session, _get_fresh_session

SITE_FETCHERS = {
    'royalroad': (scrape_royalroad, fetch_royalroad_chapter_text),
    'scribblehub': (scrape_scribblehub, fetch_scribblehub_chapter_text),
    'webnovel': (scrape_webnovel, fetch_webnovel_chapter_text),
    'generic': (scrape_generic, fetch_generic_chapter_text),
}


def scrape_story(url: str) -> dict:
    site = detect_site(url)
    fetcher = SITE_FETCHERS.get(site) or SITE_FETCHERS['generic']
    return fetcher[0](url)


def fetch_chapter_text(url: str) -> str:
    site = detect_site(url)
    if site == 'webnovel':
        return fetch_webnovel_chapter_text(url)
    if site == 'royalroad':
        return fetch_royalroad_chapter_text(url)
    if site == 'scribblehub':
        return fetch_scribblehub_chapter_text(url)
    return fetch_generic_chapter_text(url)
