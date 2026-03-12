"""
Static Expert Knowledge for each NiftyMind agent domain.

Each module exports a list of KnowledgeChunk objects that are loaded
into the pgvector database during the knowledge build phase.
These represent distilled expertise from:
  - Options theory textbooks (Sheldon Natenberg, Lawrence McMillan)
  - Market Profile theory (J. Peter Steidlmayer, CBOT)
  - Technical analysis (John Murphy, Thomas Bulkowski)
  - Global macro frameworks (Ray Dalio, Stanley Druckenmiller)
  - India-specific trading knowledge (Zerodha Varsity, NSE Academy)
  - Academic papers on market microstructure and trading systems
"""
from dataclasses import dataclass


@dataclass
class KnowledgeChunk:
    domain: str       # Agent domain key
    source: str       # Original source name
    title: str        # Descriptive title for the chunk
    content: str      # Raw text content (~500 tokens)
