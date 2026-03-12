"""
Additional web scrapers for public financial education content.

Targets:
1. Investopedia - publicly accessible financial education
2. NSE India education pages (publicly available)
3. CBOE Options Institute education articles
"""
import logging
from typing import List

from .base_scraper import BaseScraper, ScrapedPage

logger = logging.getLogger("niftymind.rag.scraper.web")


# Investopedia topics relevant to NiftyMind agents (all publicly accessible)
INVESTOPEDIA_PAGES = [
    # Options theory
    ("https://www.investopedia.com/terms/i/iv.asp", "Implied Volatility", "options_chain"),
    ("https://www.investopedia.com/terms/g/greeks.asp", "The Greeks in Options", "options_chain"),
    ("https://www.investopedia.com/terms/m/maxpain.asp", "Max Pain Theory", "options_chain"),
    ("https://www.investopedia.com/terms/p/putcallratio.asp", "Put Call Ratio", "options_chain"),
    ("https://www.investopedia.com/terms/o/openinterest.asp", "Open Interest", "options_chain"),
    ("https://www.investopedia.com/terms/v/vix.asp", "VIX Volatility Index", "sentiment_analysis"),
    # Technical analysis
    ("https://www.investopedia.com/terms/v/vwap.asp", "VWAP", "volume_profile"),
    ("https://www.investopedia.com/terms/m/marketprofile.asp", "Market Profile", "volume_profile"),
    ("https://www.investopedia.com/terms/e/ema.asp", "Exponential Moving Average", "technical_analysis"),
    ("https://www.investopedia.com/terms/r/rsi.asp", "Relative Strength Index", "technical_analysis"),
    ("https://www.investopedia.com/terms/p/pivotpoint.asp", "Pivot Points", "technical_analysis"),
    # Macro
    ("https://www.investopedia.com/terms/d/dollarindex.asp", "US Dollar Index DXY", "global_macro"),
    ("https://www.investopedia.com/terms/f/foreign-institutional-investors.asp", "Foreign Institutional Investors", "sentiment_analysis"),
    # Risk management
    ("https://www.investopedia.com/terms/k/kellycriterion.asp", "Kelly Criterion", "risk_management"),
    ("https://www.investopedia.com/terms/p/positionsizing.asp", "Position Sizing", "risk_management"),
]


class InvestopediaScraper(BaseScraper):
    """Scraper for Investopedia financial education articles."""

    def __init__(self):
        super().__init__("Investopedia", "options_chain")

    def scrape(self) -> List[ScrapedPage]:
        pages = []
        for url, title, domain in INVESTOPEDIA_PAGES:
            logger.info(f"Scraping Investopedia: {title}")
            resp = self._polite_get(url)
            if not resp:
                continue

            # Investopedia main content is in <div id="article-body">
            text = self._extract_text(resp.text, "#article-body")
            if not text or len(text) < 200:
                text = self._extract_text(resp.text, ".comp.mntl-sc-block")
            if not text or len(text) < 100:
                text = self._extract_text(resp.text, "article")

            if len(text) < 100:
                logger.warning(f"Minimal content from: {url}")
                continue

            pages.append(ScrapedPage(
                url=url,
                title=title,
                content=text[:6000],
                source="Investopedia",
                domain=domain,
            ))
            logger.info(f"  OK: {len(text)} chars")

        logger.info(f"Investopedia: scraped {len(pages)} pages.")
        return pages


# NSE India publicly available educational pages
NSE_PAGES = [
    ("https://www.nseindia.com/products-services/equity-derivatives-nifty-options", "NSE Nifty Options Overview", "options_chain"),
    ("https://www.nseindia.com/products-services/equity-derivatives-banknifty-options", "NSE BankNifty Options Overview", "options_chain"),
]


class NSEEducationScraper(BaseScraper):
    """Scraper for NSE India public educational content."""

    def __init__(self):
        super().__init__("NSE India", "options_chain")

    def scrape(self) -> List[ScrapedPage]:
        pages = []
        for url, title, domain in NSE_PAGES:
            logger.info(f"Scraping NSE: {title}")
            resp = self._polite_get(url)
            if not resp:
                continue

            text = self._extract_text(resp.text, ".container")
            if not text or len(text) < 100:
                text = self._extract_text(resp.text)

            if len(text) < 100:
                continue

            pages.append(ScrapedPage(
                url=url,
                title=title,
                content=text[:5000],
                source="NSE India",
                domain=domain,
            ))

        logger.info(f"NSE India: scraped {len(pages)} pages.")
        return pages


def get_all_scrapers() -> List[BaseScraper]:
    """Return all available scrapers for knowledge building."""
    return [
        ZerodhaVarsityScraper() if _import_varsity() else None,
        InvestopediaScraper(),
        NSEEducationScraper(),
    ]


def _import_varsity():
    try:
        from .zerodha_varsity import ZerodhaVarsityScraper  # noqa: F401
        return True
    except ImportError:
        return False
