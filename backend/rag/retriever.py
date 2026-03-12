"""
RAG Retriever

Performs semantic similarity search against the knowledge_chunks pgvector table.
Called at agent inference time to inject relevant expert context into Claude's
system prompt.

Designed to be async-safe and connection-pool friendly.
"""
import logging
import os
from typing import List

import psycopg2
from pgvector.psycopg2 import register_vector

from rag.config import rag_config
from rag.embedder import embed_query

logger = logging.getLogger("niftymind.rag.retriever")


def _get_conn():
    url = rag_config.db_url
    conn = psycopg2.connect(url)
    register_vector(conn)
    return conn


def retrieve_knowledge(
    domain: str,
    query: str,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
) -> List[dict]:
    """
    Retrieve the most relevant knowledge chunks for a given agent domain and query.

    Args:
        domain:               Agent domain key (e.g. "options_chain", "global_macro")
        query:                The current analysis context / question
        top_k:                Number of chunks to return (defaults to rag_config.top_k)
        similarity_threshold: Minimum cosine similarity (defaults to rag_config.similarity_threshold)

    Returns:
        List of dicts: [{"title": ..., "content": ..., "source": ..., "similarity": ...}]
    """
    if not rag_config.enabled:
        return []

    k = top_k or rag_config.top_k
    threshold = similarity_threshold or rag_config.similarity_threshold

    try:
        query_vec = embed_query(query)
        conn = _get_conn()
        cur = conn.cursor()

        # Cosine similarity search filtered by domain
        # pgvector cosine distance = 1 - cosine_similarity; so similarity = 1 - distance
        cur.execute(
            """
            SELECT
                title,
                content,
                source,
                1 - (embedding <=> %s::vector) AS similarity
            FROM knowledge_chunks
            WHERE domain = %s
              AND 1 - (embedding <=> %s::vector) >= %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (query_vec.tolist(), domain, query_vec.tolist(), threshold, query_vec.tolist(), k),
        )

        rows = cur.fetchall()
        cur.close()
        conn.close()

        results = [
            {
                "title":      row[0],
                "content":    row[1],
                "source":     row[2],
                "similarity": float(row[3]),
            }
            for row in rows
        ]

        logger.debug(f"RAG [{domain}] retrieved {len(results)} chunks for query: {query[:80]}")
        return results

    except Exception as e:
        logger.warning(f"RAG retrieval failed for domain={domain}: {e}")
        return []


def format_rag_context(chunks: List[dict], max_tokens: int | None = None) -> str:
    """
    Format retrieved chunks into a compact context block to inject into system prompts.

    Returns a markdown-formatted string ready for prepending to a system prompt.
    """
    if not chunks:
        return ""

    max_t = max_tokens or rag_config.max_context_tokens
    lines = ["## Expert Knowledge Base\n"]
    token_count = 0

    for chunk in chunks:
        entry = f"### {chunk['title']} (source: {chunk['source']})\n{chunk['content']}\n"
        approx_tokens = len(entry.split()) * 1.33  # rough words-to-tokens ratio
        if token_count + approx_tokens > max_t:
            break
        lines.append(entry)
        token_count += approx_tokens

    lines.append("---\nApply the above expert knowledge to your analysis below.\n")
    return "\n".join(lines)
