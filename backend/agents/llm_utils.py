"""
LLM Utilities — Claude API wrapper with RAG context injection and Extended Thinking.

query_claude() supports:
  1. RAG context injection: retrieves expert knowledge from pgvector per agent domain.
  2. Extended Thinking: enables Claude to reason step-by-step before answering,
     dramatically improving accuracy on complex multi-factor trading decisions.
     Applied only to decision agents (intraday, BTST) where reasoning depth matters most.

Architecture:
  Analysis agents (1-7): Standard Sonnet 4.6. Fast (~2-4s), runs every 3-5 min.
  Decision agents (9-10): Sonnet 4.6 + Extended Thinking. Slower (~8-15s), runs every 3 min.
    Extended Thinking lets Claude internally evaluate all signal combinations, edge cases,
    and risk factors before committing to a trade proposal — like a professional trader
    thinking through a setup before clicking the button.
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("niftymind.llm_utils")

# Agents that use Extended Thinking for deeper multi-factor reasoning
EXTENDED_THINKING_AGENTS = {"agent_9_intraday", "agent_10_btst"}

# Extended thinking budget in tokens.
# 8000 tokens of thinking ≈ 3-4 pages of internal reasoning.
# Must be < max_tokens in the API call.
THINKING_BUDGET_TOKENS = 8000


def _build_rag_system_prompt(
    system_prompt: str,
    agent_id: str,
    query_context: str,
) -> str:
    """
    Retrieve relevant knowledge from pgvector and prepend it to the system prompt.

    Falls back to original system_prompt if RAG is disabled, not populated,
    or any error occurs (fail-open — never breaks the agent pipeline).
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
        logger.debug(f"RAG context injection skipped ({agent_id}): {e}")
        return system_prompt


def _extract_text_from_response(response) -> str:
    """
    Extract text from Claude response content blocks.

    Extended Thinking responses contain multiple blocks:
      - ThinkingBlock: Claude's internal chain-of-thought (not shown to users)
      - TextBlock: The actual response text (contains our JSON)

    Standard responses contain only TextBlock(s).
    """
    for block in response.content:
        if block.type == "text":
            return block.text
    # Fallback: try direct text access on first block
    if response.content:
        return getattr(response.content[0], "text", "")
    return ""


async def query_claude(
    system_prompt: str,
    user_message: str,
    anthropic_config=None,
    agent_id: str | None = None,
    rag_query: str | None = None,
) -> dict:
    """
    Call Claude API with optional RAG context injection and Extended Thinking.

    Args:
        system_prompt:    Base system prompt for the agent.
        user_message:     The user-facing message with live market data.
        anthropic_config: Config object with api_key, model, max_tokens.
        agent_id:         Agent identifier. Used for:
                          - RAG domain lookup (all agents).
                          - Extended Thinking activation (decision agents only).
        rag_query:        Custom query for RAG retrieval. Defaults to first 500
                          chars of user_message if not provided.

    Returns:
        dict with parsed JSON response from Claude, or fallback dict on error.

    Extended Thinking:
        When agent_id is in EXTENDED_THINKING_AGENTS (intraday, BTST), Claude
        is given a 8,000-token "thinking budget" to reason through all signals,
        weigh evidence, consider edge cases, and evaluate risk before answering.
        This token usage is not billed at the same rate as output tokens and
        the thinking content is NOT included in the JSON response.
    """
    from anthropic import AsyncAnthropic

    api_key = anthropic_config.api_key if anthropic_config else os.getenv("ANTHROPIC_API_KEY", "")
    model = (
        anthropic_config.model if anthropic_config
        else os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    )
    base_max_tokens = anthropic_config.max_tokens if anthropic_config else 4096

    # RAG context injection — enrich system prompt with domain expert knowledge
    effective_system_prompt = system_prompt
    if agent_id:
        query = rag_query or user_message[:500]
        effective_system_prompt = _build_rag_system_prompt(system_prompt, agent_id, query)

    client = AsyncAnthropic(api_key=api_key)

    use_extended_thinking = agent_id in EXTENDED_THINKING_AGENTS

    if use_extended_thinking:
        # Extended Thinking requires max_tokens > budget_tokens.
        # We set max_tokens = budget + output_budget (4096 for the JSON response).
        extended_max_tokens = THINKING_BUDGET_TOKENS + 4096

        logger.debug(
            f"Extended Thinking enabled for {agent_id}: "
            f"budget={THINKING_BUDGET_TOKENS} tokens, max={extended_max_tokens} tokens"
        )

        response = await client.messages.create(
            model=model,
            max_tokens=extended_max_tokens,
            thinking={
                "type": "enabled",
                "budget_tokens": THINKING_BUDGET_TOKENS,
            },
            system=effective_system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
    else:
        response = await client.messages.create(
            model=model,
            max_tokens=base_max_tokens,
            system=effective_system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

    raw_text = _extract_text_from_response(response)

    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw_text[start:end])
    except json.JSONDecodeError:
        pass

    logger.warning(f"Could not parse JSON from Claude response for {agent_id}")
    return {"raw_response": raw_text, "direction": "NEUTRAL", "confidence": 0.3}
