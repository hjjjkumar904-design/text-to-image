import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetchers import (
    detect_site,
    scrape_story as scrape_webnovel,
    fetch_chapter_text,
    fetch_webnovel_chapter_text,
    scrape_royalroad,
    scrape_scribblehub,
    scrape_generic,
    fetch_royalroad_chapter_text,
    fetch_scribblehub_chapter_text,
    fetch_generic_chapter_text,
    CHAPTER_PATTERNS,
    _get_session,
    _get_fresh_session,
)

__all__ = [
    'scrape_webnovel',
    'fetch_chapter_text',
    'fetch_webnovel_chapter_text',
    'scrape_royalroad',
    'scrape_scribblehub',
    'scrape_generic',
    'fetch_royalroad_chapter_text',
    'fetch_scribblehub_chapter_text',
    'fetch_generic_chapter_text',
    'detect_site',
    'CHAPTER_PATTERNS',
    '_get_session',
    '_get_fresh_session',
]
