"""
RAG Configuration

Controls embedding model selection, vector dimensions, and retrieval parameters.
Designed to be zero-dependency on external embedding APIs — uses local
sentence-transformers model for privacy, speed, and zero cost.
"""
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RAGConfig:
    # Embedding model — BAAI/bge-small-en-v1.5 is fast (384-dim) with excellent
    # retrieval quality. Swap to "BAAI/bge-large-en-v1.5" (1024-dim) for higher
    # quality at the cost of ~4x slower embedding generation.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Retrieval parameters
    top_k: int = 5                     # Number of chunks to retrieve per query
    similarity_threshold: float = 0.30  # Minimum cosine similarity to include chunk
    max_context_tokens: int = 2000      # Max tokens to inject into system prompt

    # Chunking parameters
    chunk_size: int = 500              # Target tokens per chunk
    chunk_overlap: int = 50            # Overlap between adjacent chunks

    # Database
    db_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "postgresql://localhost/niftymind")
    )
    table_name: str = "knowledge_chunks"

    # Feature flag — set RAG_ENABLED=false to bypass RAG (useful in testing)
    enabled: bool = field(
        default_factory=lambda: os.getenv("RAG_ENABLED", "true").lower() == "true"
    )


# Agent domain identifiers — used to scope knowledge retrieval
AGENT_DOMAINS = {
    "agent_1_options_chain": "options_chain",
    "agent_2_order_flow":    "order_flow",
    "agent_3_volume_profile": "volume_profile",
    "agent_4_technical":     "technical_analysis",
    "agent_5_sentiment":     "sentiment_analysis",
    "agent_6_news":          "news_trading",
    "agent_7_macro":         "global_macro",
    "agent_8_scalping":      "scalping",
    "agent_9_intraday":      "consensus_voting",
    "agent_10_btst":         "btst_strategies",
    "agent_11_risk":         "risk_management",
    "agent_12_consensus":    "consensus_voting",
}

# Default global config instance
rag_config = RAGConfig()
