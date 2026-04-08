import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import aiohttp
import psycopg2

logger = logging.getLogger("niftymind.news_feed")

IST = timezone(timedelta(hours=5, minutes=30))

RSS_FEEDS = [
    {
        "name": "MoneyControl",
        "url": "https://www.moneycontrol.com/rss/marketreports.xml",
        "category": "market",
    },
    {
        "name": "ET Markets",
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "category": "market",
    },
    {
        "name": "LiveMint",
        "url": "https://www.livemint.com/rss/markets",
        "category": "market",
    },
]

CALENDAR_RSS_FEEDS = [
    {
        "name": "ForexFactory",
        "url": "https://www.forexfactory.com/rss.xml",
    },
    {
        "name": "FXStreet",
        "url": "https://www.fxstreet.com/rss/economic-calendar",
    },
]

INDIA_EVENT_KEYWORDS = [
    "india", "rbi", "rupee", "inr", "nifty", "sensex", "bse", "nse",
    "repo rate", "cpi india", "wpi", "gdp india", "iip", "fiscal deficit",
]
GLOBAL_HIGH_IMPACT_KEYWORDS = [
    "fed", "fomc", "non-farm", "nfp", "cpi us", "pce", "ecb",
    "boe", "boj", "opec", "crude", "oil", "treasury",
]


class NewsFeed:
    def __init__(self, publisher):
        self.publisher = publisher
        self._session: aiohttp.ClientSession | None = None
        self._seen_headlines: set = set()
        self._seen_calendar_events: set = set()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def start(self, shutdown_event: asyncio.Event):
        logger.info("News feed starting")
        while not shutdown_event.is_set():
            try:
                await self._fetch_and_publish()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"News feed error: {e}")

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=120.0)
                break
            except asyncio.TimeoutError:
                continue

        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("News feed stopped")

    async def _fetch_and_publish(self):
        session = await self._get_session()

        all_articles = []
        for feed in RSS_FEEDS:
            try:
                articles = await self._fetch_rss(session, feed)
                all_articles.extend(articles)
            except Exception as e:
                logger.warning(f"Failed to fetch RSS from {feed['name']}: {e}")

        new_articles = []
        for article in all_articles:
            headline = article.get("title", "")
            if headline and headline not in self._seen_headlines:
                self._seen_headlines.add(headline)
                new_articles.append(article)

        if len(self._seen_headlines) > 1000:
            self._seen_headlines = set(list(self._seen_headlines)[-500:])

        if new_articles:
            news_payload = {
                "timestamp": datetime.now(IST).isoformat(),
                "articles": new_articles,
                "source_count": len(RSS_FEEDS),
                "new_count": len(new_articles),
            }
            await self.publisher.publish_news(news_payload)
            logger.info(f"Published {len(new_articles)} new articles")

            # Cache articles in-memory for API fallback when DB is unavailable
            try:
                from api.server import get_app_state
                cache = get_app_state().get("news_cache", [])
                for a in new_articles:
                    cache.insert(0, a)
                # Keep only latest 100
                if len(cache) > 100:
                    del cache[100:]
            except Exception:
                pass

            # Persist articles to audit_logs so the /api/news endpoint can serve them
            self._persist_news_to_db(new_articles)

        try:
            calendar = await self._fetch_economic_calendar(session)
            if calendar:
                await self.publisher.publish_economic_calendar(calendar)
                events = calendar.get("events", [])
                logger.info(f"Published economic calendar with {len(events)} events")
                # Persist calendar events to DB
                self._persist_calendar_to_db(events)
        except Exception as e:
            logger.warning(f"Failed to fetch economic calendar: {e}")

    async def _fetch_rss(self, session: aiohttp.ClientSession, feed: dict) -> list[dict]:
        articles = []
        try:
            async with session.get(feed["url"], timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return articles
                text = await resp.text()

                import xml.etree.ElementTree as ET
                root = ET.fromstring(text)

                for item in root.iter("item"):
                    title = item.findtext("title", "").strip()
                    description = item.findtext("description", "").strip()
                    pub_date = item.findtext("pubDate", "")
                    link = item.findtext("link", "")

                    if title:
                        articles.append({
                            "title": title,
                            "description": description[:500] if description else "",
                            "published": pub_date,
                            "link": link,
                            "source": feed["name"],
                            "category": feed["category"],
                        })
        except Exception as e:
            logger.warning(f"RSS parse error for {feed['name']}: {e}")
        return articles[:20]

    async def _fetch_economic_calendar(self, session: aiohttp.ClientSession) -> dict | None:
        today = datetime.now(IST).strftime("%Y-%m-%d")
        events: list[dict] = []

        for cal_feed in CALENDAR_RSS_FEEDS:
            try:
                raw_events = await self._fetch_calendar_rss(session, cal_feed)
                events.extend(raw_events)
            except Exception as e:
                logger.warning(f"Calendar RSS error for {cal_feed['name']}: {e}")

        new_events = []
        for ev in events:
            key = ev.get("event", "")
            if key and key not in self._seen_calendar_events:
                self._seen_calendar_events.add(key)
                new_events.append(ev)

        if len(self._seen_calendar_events) > 500:
            self._seen_calendar_events = set(list(self._seen_calendar_events)[-250:])

        if not new_events:
            return None

        return {
            "timestamp": datetime.now(IST).isoformat(),
            "date": today,
            "events": new_events,
        }

    async def _fetch_calendar_rss(self, session: aiohttp.ClientSession, feed: dict) -> list[dict]:
        events = []
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
            async with session.get(
                feed["url"],
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return events
                text = await resp.text()

                import xml.etree.ElementTree as ET
                root = ET.fromstring(text)

                for item in root.iter("item"):
                    title = item.findtext("title", "").strip()
                    description = item.findtext("description", "").strip()
                    pub_date = item.findtext("pubDate", "")

                    if not title:
                        continue

                    impact = self._classify_event_impact(title, description)
                    country = self._detect_country(title, description)

                    events.append({
                        "event": title,
                        "description": description[:300] if description else "",
                        "date": pub_date,
                        "impact": impact,
                        "country": country,
                        "source": feed["name"],
                    })
        except Exception as e:
            logger.debug(f"Calendar RSS parse error for {feed['name']}: {e}")
        return events[:30]

    def _classify_event_impact(self, title: str, description: str) -> str:
        combined = (title + " " + description).lower()
        for kw in GLOBAL_HIGH_IMPACT_KEYWORDS:
            if kw in combined:
                return "HIGH"
        for kw in INDIA_EVENT_KEYWORDS:
            if kw in combined:
                return "HIGH"
        return "MEDIUM"

    def _persist_news_to_db(self, articles: list[dict]):
        """Store news articles in audit_logs for the /api/news endpoint."""
        conn = None
        try:
            db_url = os.getenv("DATABASE_URL", "")
            if not db_url:
                return
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            now = datetime.now(IST)
            for article in articles:
                title = article.get("title", "")
                source = article.get("source", "Unknown")
                impact = self._classify_event_impact(title, article.get("description", ""))
                details = {
                    "headline": title,
                    "description": article.get("description", "")[:300],
                    "source": source,
                    "category": article.get("category", "market"),
                    "impact": impact.lower(),
                    "link": article.get("link", ""),
                    "published": article.get("published", ""),
                }
                cur.execute(
                    """INSERT INTO audit_logs (event_type, source, message, details, timestamp)
                       VALUES (%s, %s, %s, %s, %s)""",
                    ("NEWS_CLASSIFIED", source, title[:500], json.dumps(details), now),
                )
            conn.commit()
            logger.debug(f"Persisted {len(articles)} news articles to DB")
        except Exception as e:
            logger.warning(f"Failed to persist news to DB: {e}")
        finally:
            if conn:
                conn.close()

    def _persist_calendar_to_db(self, events: list[dict]):
        """Store calendar events in audit_logs for the /api/news endpoint."""
        conn = None
        try:
            db_url = os.getenv("DATABASE_URL", "")
            if not db_url:
                return
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            now = datetime.now(IST)
            for event in events:
                event_name = event.get("event", "")
                source = event.get("source", "Unknown")
                details = {
                    "headline": event_name,
                    "source": source,
                    "impact": event.get("impact", "MEDIUM").lower(),
                    "country": event.get("country", "GLOBAL"),
                    "category": "economic_calendar",
                    "event_time": event.get("date", ""),
                    "description": event.get("description", ""),
                }
                cur.execute(
                    """INSERT INTO audit_logs (event_type, source, message, details, timestamp)
                       VALUES (%s, %s, %s, %s, %s)""",
                    ("NEWS_CLASSIFIED", source, event_name[:500], json.dumps(details), now),
                )
            conn.commit()
            logger.debug(f"Persisted {len(events)} calendar events to DB")
        except Exception as e:
            logger.warning(f"Failed to persist calendar events to DB: {e}")
        finally:
            if conn:
                conn.close()

    def _detect_country(self, title: str, description: str) -> str:
        combined = (title + " " + description).lower()
        for kw in INDIA_EVENT_KEYWORDS:
            if kw in combined:
                return "IN"
        if any(kw in combined for kw in ["fed", "fomc", "us ", "nfp", "non-farm", "pce"]):
            return "US"
        if any(kw in combined for kw in ["ecb", "euro"]):
            return "EU"
        if "boj" in combined or "japan" in combined:
            return "JP"
        if "boe" in combined or "uk " in combined:
            return "GB"
        return "GLOBAL"
