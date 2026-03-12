"""
Setup script for the pgvector knowledge base.

Creates the knowledge_chunks table with a vector column for semantic search.
Must be run once before using the RAG system:

    python backend/rag/setup_knowledge_db.py

Requires:
    - PostgreSQL with pgvector extension
    - DATABASE_URL environment variable
"""
import os
import sys
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("niftymind.rag.setup")


def setup_knowledge_db(db_url: str | None = None):
    import psycopg2
    from pgvector.psycopg2 import register_vector

    url = db_url or os.getenv("DATABASE_URL", "postgresql://localhost/niftymind")
    logger.info(f"Connecting to database...")

    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()

    # Enable pgvector extension
    logger.info("Enabling pgvector extension...")
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    register_vector(conn)

    # Create knowledge_chunks table
    logger.info("Creating knowledge_chunks table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id          SERIAL PRIMARY KEY,
            domain      TEXT NOT NULL,
            source      TEXT NOT NULL,
            title       TEXT NOT NULL,
            content     TEXT NOT NULL,
            embedding   vector(384),
            metadata    JSONB DEFAULT '{}',
            created_at  TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # Index for fast approximate nearest-neighbor search
    # Using IVFFlat with 100 lists (good for < 1M rows)
    logger.info("Creating vector index (IVFFlat)...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_idx
        ON knowledge_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
    """)

    # Index on domain for filtered queries
    cur.execute("""
        CREATE INDEX IF NOT EXISTS knowledge_chunks_domain_idx
        ON knowledge_chunks (domain);
    """)

    cur.close()
    conn.close()
    logger.info("Knowledge database setup complete.")


if __name__ == "__main__":
    setup_knowledge_db()
