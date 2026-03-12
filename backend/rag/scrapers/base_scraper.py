"""
Base scraper with rate limiting, retry logic, and HTML→text extraction.
"""
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("niftymind.rag.scraper")


@dataclass
class ScrapedPage:
    url: str
    title: str
    content: str   # clean plain text
    source: str    # human-readable source name
    domain: str    # agent domain this content belongs to


class BaseScraper:
    """Base class for all knowledge scrapers."""

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; NiftyMindBot/1.0; +https://github.com/niftymind; "
            "Educational research bot)"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    REQUEST_DELAY = 2.0   # seconds between requests (polite crawling)
    TIMEOUT = 15           # seconds per request
    MAX_RETRIES = 3

    def __init__(self, source_name: str, agent_domain: str):
        self.source_name = source_name
        self.agent_domain = agent_domain
        self._last_request_time = 0.0

    def _polite_get(self, url: str) -> Optional[requests.Response]:
        """Rate-limited GET with retries."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - elapsed)

        for attempt in range(self.MAX_RETRIES):
            try:
                resp = requests.get(
                    url,
                    headers=self.DEFAULT_HEADERS,
                    timeout=self.TIMEOUT,
                )
                self._last_request_time = time.time()
                if resp.status_code == 200:
                    return resp
                elif resp.status_code == 429:
                    wait = 2 ** (attempt + 2)
                    logger.warning(f"Rate limited on {url}. Waiting {wait}s.")
                    time.sleep(wait)
                else:
                    logger.warning(f"HTTP {resp.status_code} for {url}")
                    return None
            except requests.RequestException as e:
                logger.error(f"Request error (attempt {attempt+1}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)

        return None

    def _extract_text(self, html: str, content_selector: str = "article") -> str:
        """Extract clean plain text from HTML using BeautifulSoup."""
        soup = BeautifulSoup(html, "lxml")

        # Remove boilerplate elements
        for tag in soup(["script", "style", "nav", "header", "footer",
                         "aside", "form", "button", "iframe", "noscript"]):
            tag.decompose()

        # Try content selector first, fallback to body
        content = soup.select_one(content_selector)
        if not content:
            content = soup.find("main") or soup.find("body")

        if not content:
            return ""

        # Get text with reasonable spacing
        text = content.get_text(separator="\n", strip=True)

        # Clean up whitespace
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    def scrape(self) -> List[ScrapedPage]:
        """Override in subclasses. Returns list of ScrapedPage objects."""
        raise NotImplementedError
