"""
Knowledge Builder — Orchestrates the full RAG knowledge base construction.

Run this script ONCE to:
  1. Load all static expert knowledge (hardcoded in static_knowledge/ modules).
  2. Scrape web sources (Zerodha Varsity, Investopedia, NSE India).
  3. Chunk all content into ~500-token passages.
  4. Embed each chunk using sentence-transformers.
  5. Store everything in the PostgreSQL knowledge_chunks table (pgvector).

Usage:
    python backend/rag/knowledge_builder.py [--skip-web] [--rebuild]

Options:
    --skip-web    Skip web scraping (use only static knowledge). Useful for offline environments.
    --rebuild     Drop and rebuild knowledge_chunks table (clears previous data).

Estimated runtime:
    Static knowledge only (~50 chunks): 30 seconds.
    With web scraping (~250 chunks total): 3-5 minutes (limited by rate limiting delays).
"""
import argparse
import logging
import os
import sys
import time
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("niftymind.rag.builder")


def load_static_knowledge():
    """Load all hardcoded expert knowledge from static_knowledge/ modules."""
    from rag.static_knowledge.options_theory import CHUNKS as options_chunks
    from rag.static_knowledge.order_flow import CHUNKS as order_flow_chunks
    from rag.static_knowledge.volume_profile import CHUNKS as volume_chunks
    from rag.static_knowledge.technical_analysis import CHUNKS as technical_chunks
    from rag.static_knowledge.sentiment_analysis import CHUNKS as sentiment_chunks
    from rag.static_knowledge.news_trading import CHUNKS as news_chunks
    from rag.static_knowledge.global_macro import CHUNKS as macro_chunks
    from rag.static_knowledge.risk_management import CHUNKS as risk_chunks
    from rag.static_knowledge.btst_strategies import CHUNKS as btst_chunks
    from rag.static_knowledge.scalping_strategies import CHUNKS as scalping_chunks
    from rag.static_knowledge.consensus_voting import CHUNKS as consensus_chunks

    all_chunks = (
        options_chunks
        + order_flow_chunks
        + volume_chunks
        + technical_chunks
        + sentiment_chunks
        + news_chunks
        + macro_chunks
        + risk_chunks
        + btst_chunks
        + scalping_chunks
        + consensus_chunks
    )
    logger.info(f"Loaded {len(all_chunks)} static knowledge chunks.")
    return all_chunks


def scrape_web_sources() -> List:
    """Scrape Zerodha Varsity, Investopedia, NSE India."""
    from rag.scrapers.zerodha_varsity import ZerodhaVarsityScraper
    from rag.scrapers.web_sources import InvestopediaScraper, NSEEducationScraper

    all_pages = []
    for ScraperClass in [ZerodhaVarsityScraper, InvestopediaScraper, NSEEducationScraper]:
        try:
            scraper = ScraperClass()
            pages = scraper.scrape()
            all_pages.extend(pages)
            logger.info(f"{scraper.source_name}: {len(pages)} pages scraped.")
        except Exception as e:
            logger.warning(f"Scraper {ScraperClass.__name__} failed: {e}")

    return all_pages


def insert_chunks_to_db(chunks_data: List[dict], db_url: str):
    """
    Embed and insert chunks into PostgreSQL knowledge_chunks table.

    chunks_data: list of dicts with keys: domain, source, title, content
    """
    import numpy as np
    import psycopg2
    from pgvector.psycopg2 import register_vector
    from rag.embedder import embed_texts, chunk_text

    conn = psycopg2.connect(db_url)
    register_vector(conn)
    cur = conn.cursor()

    inserted = 0
    batch_size = 16

    for i in range(0, len(chunks_data), batch_size):
        batch = chunks_data[i:i + batch_size]

        # Sub-chunk long content pieces
        expanded = []
        for item in batch:
            text_chunks = chunk_text(item["content"], chunk_size=500, overlap=50)
            for j, sub_chunk in enumerate(text_chunks):
                expanded.append({
                    "domain":  item["domain"],
                    "source":  item["source"],
                    "title":   f"{item['title']} ({j+1}/{len(text_chunks)})" if len(text_chunks) > 1 else item["title"],
                    "content": sub_chunk,
                })

        if not expanded:
            continue

        texts = [f"{e['title']}: {e['content']}" for e in expanded]
        embeddings = embed_texts(texts)

        for item, embedding in zip(expanded, embeddings):
            cur.execute(
                """
                INSERT INTO knowledge_chunks (domain, source, title, content, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                """,
                (
                    item["domain"],
                    item["source"],
                    item["title"],
                    item["content"],
                    embedding.tolist(),
                ),
            )
            inserted += 1

        conn.commit()
        logger.info(f"Inserted batch {i//batch_size + 1}: {len(expanded)} sub-chunks.")

    cur.close()
    conn.close()
    logger.info(f"Total inserted: {inserted} chunks.")
    return inserted


def build_knowledge_base(skip_web: bool = False, rebuild: bool = False):
    """Main entry point for knowledge base construction."""
    import psycopg2
    from pgvector.psycopg2 import register_vector
    from rag.setup_knowledge_db import setup_knowledge_db

    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/niftymind")
    logger.info("Starting NiftyMind RAG knowledge base build...")

    # Setup/rebuild table
    if rebuild:
        logger.info("Rebuilding: dropping existing knowledge_chunks...")
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        conn.cursor().execute("DROP TABLE IF EXISTS knowledge_chunks;")
        conn.close()

    setup_knowledge_db(db_url)

    # Check if already populated
    conn = psycopg2.connect(db_url)
    register_vector(conn)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM knowledge_chunks;")
    existing = cur.fetchone()[0]
    cur.close()
    conn.close()

    if existing > 0 and not rebuild:
        logger.info(f"Knowledge base already has {existing} chunks. Use --rebuild to refresh.")
        return existing

    # Load static knowledge
    static_chunks = load_static_knowledge()
    chunks_data = [
        {"domain": c.domain, "source": c.source, "title": c.title, "content": c.content}
        for c in static_chunks
    ]

    # Scrape web sources
    if not skip_web:
        logger.info("Scraping web sources (this takes 3-5 min due to rate limiting)...")
        from rag.scrapers.zerodha_varsity import ZerodhaVarsityScraper
        from rag.scrapers.web_sources import InvestopediaScraper, NSEEducationScraper

        for ScraperClass in [ZerodhaVarsityScraper, InvestopediaScraper, NSEEducationScraper]:
            try:
                scraper = ScraperClass()
                pages = scraper.scrape()
                for page in pages:
                    chunks_data.append({
                        "domain":  page.domain,
                        "source":  page.source,
                        "title":   page.title,
                        "content": page.content,
                    })
                logger.info(f"{scraper.source_name}: {len(pages)} pages.")
            except Exception as e:
                logger.warning(f"Scraper failed: {e}")
    else:
        logger.info("Skipping web scraping (--skip-web flag).")

    logger.info(f"Total knowledge items to embed: {len(chunks_data)}")

    # Embed and insert
    start = time.time()
    total_inserted = insert_chunks_to_db(chunks_data, db_url)
    elapsed = time.time() - start

    logger.info(f"Knowledge base built in {elapsed:.1f}s. Total chunks: {total_inserted}")
    logger.info("RAG system is ready. Each agent will now retrieve expert context at inference time.")
    return total_inserted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build NiftyMind RAG knowledge base")
    parser.add_argument("--skip-web", action="store_true", help="Skip web scraping")
    parser.add_argument("--rebuild", action="store_true", help="Drop and rebuild knowledge base")
    args = parser.parse_args()

    build_knowledge_base(skip_web=args.skip_web, rebuild=args.rebuild)
