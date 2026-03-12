"""
Text Embedder using sentence-transformers

Converts text chunks and query strings into dense vector embeddings
using BAAI/bge-small-en-v1.5 (384 dimensions).

The model is loaded once and cached as a module-level singleton to
avoid re-loading on every call (model load takes ~2s).
"""
import logging
import os
from typing import List

import numpy as np

logger = logging.getLogger("niftymind.rag.embedder")

_model = None
_model_name: str = ""


def _get_model(model_name: str = "BAAI/bge-small-en-v1.5"):
    """Lazy-load and cache the sentence-transformer model."""
    global _model, _model_name
    if _model is None or _model_name != model_name:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {model_name}")
            _model = SentenceTransformer(model_name)
            _model_name = model_name
            logger.info(f"Embedding model loaded (dim={_model.get_sentence_embedding_dimension()})")
        except ImportError:
            logger.error("sentence-transformers not installed. Run: pip install sentence-transformers")
            raise
    return _model


def embed_texts(texts: List[str], model_name: str = "BAAI/bge-small-en-v1.5") -> np.ndarray:
    """
    Embed a list of texts into dense vectors.

    For BGE models, the query prefix "Represent this sentence: " is added
    automatically by SentenceTransformer when encode() is called.

    Returns:
        np.ndarray of shape (len(texts), embedding_dim), dtype=float32
    """
    model = _get_model(model_name)
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,   # L2 normalize for cosine similarity via dot product
        convert_to_numpy=True,
    )
    return embeddings.astype(np.float32)


def embed_query(query: str, model_name: str = "BAAI/bge-small-en-v1.5") -> np.ndarray:
    """
    Embed a single query string.
    BGE models perform best when queries are prefixed with "query: ".
    """
    prefixed = f"query: {query}"
    result = embed_texts([prefixed], model_name=model_name)
    return result[0]


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Split text into overlapping chunks by approximate token count.
    Uses whitespace tokenization as a cheap token approximation (1 token ≈ 0.75 words).
    """
    words = text.split()
    # Approximate: chunk_size tokens ≈ chunk_size * 0.75 words
    words_per_chunk = int(chunk_size * 0.75)
    overlap_words = int(overlap * 0.75)

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + words_per_chunk, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end >= len(words):
            break
        start += words_per_chunk - overlap_words

    return [c for c in chunks if len(c.strip()) > 50]
