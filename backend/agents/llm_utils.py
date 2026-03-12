"""
LLM Utilities — Claude API wrapper with RAG context injection.

query_claude() accepts an optional `agent_id` parameter. When provided and the
RAG knowledge base is populated, it automatically retrieves the most relevant
expert knowledge chunks and prepends them to the system prompt, giving Claude
expert-level domain context at inference time.

This makes each agent behave like a domain specialist, not just a general LLM.
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("niftymind.llm_utils")


def _build_rag_system_prompt(
    system_prompt: str,
    agent_id: str,
    query_context: str,
) -> str:
    """
    Retrieve relevant knowledge from pgvector and prepend it to the system prompt.

    Falls back to original system_prompt if:
    - RAG is disabled (RAG_ENABLED=false).
    - pgvector table is not populated yet.
    - sentence-transformers is not installed.
    - Any other error (fail open, don't break the agent).
    """
    try:
        from rag.config import AGENT_DOMAINS, rag_config
        from rag.retriever import retrieve_knowledge, format_rag_context

        if not rag_config.enabled:
            return system_prompt

        domain = AGENT_DOMAINS.get(agent_id)
        if not domain:
            return system_prompt

        chunks = retrieve_knowledge(domain, query_context, top_k=5)
        if not chunks:
            return system_prompt

        rag_context = format_rag_context(chunks)
        enriched_prompt = f"{rag_context}\n\n{system_prompt}"
        logger.debug(
            f"RAG enriched prompt for {agent_id}: "
            f"{len(chunks)} chunks, +{len(rag_context)} chars"
        )
        return enriched_prompt

    except Exception as e:
        # RAG is best-effort — never break the agent pipeline
        logger.debug(f"RAG context injection skipped ({agent_id}): {e}")
        return system_prompt


async def query_claude(
    system_prompt: str,
    user_message: str,
    anthropic_config=None,
    agent_id: str | None = None,
    rag_query: str | None = None,
) -> dict:
    """
    Call Claude API with optional RAG context injection.

    Args:
        system_prompt:    Base system prompt for the agent.
        user_message:     The user-facing message with live market data.
        anthropic_config: Config object with api_key, model, max_tokens.
        agent_id:         Agent identifier for RAG domain lookup (e.g. "agent_1_options_chain").
        rag_query:        Custom query string for RAG retrieval. Defaults to first 500 chars
                          of user_message if not provided.

    Returns:
        dict with parsed JSON response from Claude, or fallback dict on error.
    """
    from anthropic import AsyncAnthropic

    api_key = anthropic_config.api_key if anthropic_config else os.getenv("ANTHROPIC_API_KEY", "")
    model = anthropic_config.model if anthropic_config else os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    max_tokens = anthropic_config.max_tokens if anthropic_config else 4096

    # RAG context injection — builds expert knowledge context into system prompt
    effective_system_prompt = system_prompt
    if agent_id:
        query = rag_query or user_message[:500]
        effective_system_prompt = _build_rag_system_prompt(system_prompt, agent_id, query)

    client = AsyncAnthropic(api_key=api_key)

    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=effective_system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = response.content[0].text

    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw_text[start:end])
    except json.JSONDecodeError:
        pass

    logger.warning(f"Could not parse JSON from Claude response, returning raw text")
    return {"raw_response": raw_text, "direction": "NEUTRAL", "confidence": 0.3}
