"""
Zerodha Varsity Scraper

Zerodha Varsity (https://zerodha.com/varsity/) is a free, openly licensed
financial education platform. Content is licensed under Creative Commons
Attribution-ShareAlike 4.0 (CC BY-SA 4.0), which permits educational use.

Targets the most relevant modules for NiftyMind agents:
- Module 5: Options Theory & Trading
- Module 6: Option Strategies
- Module 8: Currency & Commodity Futures (macro)
- Module 10: Technical Analysis
- Module 11: Futures Trading
"""
import logging
from typing import List

from .base_scraper import BaseScraper, ScrapedPage

logger = logging.getLogger("niftymind.rag.scraper.zerodha")

# Zerodha Varsity chapter URLs mapped to agent domains
# Format: (url, title, agent_domain)
VARSITY_CHAPTERS = [
    # Module 5: Options Theory
    ("https://zerodha.com/varsity/chapter/call-option-basics/", "Call Option Basics", "options_chain"),
    ("https://zerodha.com/varsity/chapter/basic-option-jargons/", "Option Jargons - ITM ATM OTM", "options_chain"),
    ("https://zerodha.com/varsity/chapter/moneyness-of-an-option-contract/", "Moneyness of Options", "options_chain"),
    ("https://zerodha.com/varsity/chapter/an-introduction-to-the-option-greeks/", "Introduction to Option Greeks", "options_chain"),
    ("https://zerodha.com/varsity/chapter/delta-part-1/", "Delta - Part 1", "options_chain"),
    ("https://zerodha.com/varsity/chapter/delta-part-2/", "Delta - Part 2", "options_chain"),
    ("https://zerodha.com/varsity/chapter/gamma-scalping/", "Gamma and Gamma Scalping", "options_chain"),
    ("https://zerodha.com/varsity/chapter/theta/", "Theta - Time Decay", "options_chain"),
    ("https://zerodha.com/varsity/chapter/vega/", "Vega - Volatility Sensitivity", "options_chain"),
    ("https://zerodha.com/varsity/chapter/volatility-basics/", "Volatility Basics", "options_chain"),
    ("https://zerodha.com/varsity/chapter/volatility-applications/", "Volatility Applications", "options_chain"),
    ("https://zerodha.com/varsity/chapter/the-black-and-scholes-pricing-formula/", "Black-Scholes Formula", "options_chain"),
    ("https://zerodha.com/varsity/chapter/the-option-chain/", "Reading the Option Chain", "options_chain"),
    ("https://zerodha.com/varsity/chapter/put-call-ratio/", "Put Call Ratio", "options_chain"),
    # Module 10: Technical Analysis
    ("https://zerodha.com/varsity/chapter/introduction-to-technical-analysis/", "Introduction to Technical Analysis", "technical_analysis"),
    ("https://zerodha.com/varsity/chapter/support-and-resistance/", "Support and Resistance", "technical_analysis"),
    ("https://zerodha.com/varsity/chapter/volume-price-analysis/", "Volume Price Analysis", "technical_analysis"),
    ("https://zerodha.com/varsity/chapter/moving-averages/", "Moving Averages", "technical_analysis"),
    ("https://zerodha.com/varsity/chapter/indicators-part-1/", "Technical Indicators Part 1", "technical_analysis"),
    ("https://zerodha.com/varsity/chapter/indicators-part-2/", "Technical Indicators Part 2 (RSI, MACD)", "technical_analysis"),
    # Module 4: Futures Trading
    ("https://zerodha.com/varsity/chapter/leverage-payoff/", "Futures Leverage and Payoff", "risk_management"),
    ("https://zerodha.com/varsity/chapter/margin-and-m2m/", "Margin and Mark to Market", "risk_management"),
]


class ZerodhaVarsityScraper(BaseScraper):
    """Scraper for Zerodha Varsity educational content (CC BY-SA 4.0 licensed)."""

    def __init__(self):
        super().__init__("Zerodha Varsity", "options_chain")  # domain varies per chapter

    def scrape(self) -> List[ScrapedPage]:
        pages = []
        for url, title, domain in VARSITY_CHAPTERS:
            logger.info(f"Scraping Varsity: {title}")
            resp = self._polite_get(url)
            if not resp:
                logger.warning(f"Failed to fetch: {url}")
                continue

            # Varsity uses <div class="post-content"> for article body
            text = self._extract_text(resp.text, ".post-content")
            if not text or len(text) < 200:
                text = self._extract_text(resp.text, "article")

            if not text or len(text) < 100:
                logger.warning(f"No content extracted from: {url}")
                continue

            pages.append(ScrapedPage(
                url=url,
                title=title,
                content=text[:8000],  # Cap at 8K chars per page
                source="Zerodha Varsity",
                domain=domain,
            ))
            logger.info(f"  OK: {len(text)} chars extracted")

        logger.info(f"Zerodha Varsity: scraped {len(pages)} pages.")
        return pages
