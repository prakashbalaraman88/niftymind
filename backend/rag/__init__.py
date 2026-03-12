"""
NiftyMind RAG (Retrieval-Augmented Generation) Module

Provides each AI agent with domain-specific expert knowledge retrieved
from a pgvector knowledge base, dramatically improving the depth and
accuracy of each agent's analysis.

Usage:
    from rag.retriever import retrieve_knowledge
    chunks = await retrieve_knowledge("options_chain", query_text, top_k=5)
"""
