"""
NiftyMind LLM Utilities — Multi-Provider Router with RAG and Extended Thinking.

Implements a tiered model strategy for optimal speed vs accuracy:

  TIER 1 — Analysis Agents (1-7): Gemini 3 Flash
    Fast (~0.9s), cheapest ($0.50/$3 per 1M tokens), runs every 3-5 minutes.
    High-frequency signal generation where latency matters.

  TIER 2 — Decision Agents (9, 10): Claude Sonnet 4.6 + Extended Thinking
    Deep reasoning (~8-15s), proven JSON reliability, runs every 3 min.
    Trade proposals where accuracy matters far more than speed.

Both tiers benefit from RAG context injection (pgvector expert knowledge).

CONFIGURATION (via environment variables):
  ANALYSIS_LLM_PROVIDER   = gemini | claude        (default: gemini)
  ANALYSIS_LLM_MODEL      = gemini-3-flash-preview  (default shown)
  DECISION_LLM_PROVIDER   = claude | gemini         (default: claude)
  DECISION_LLM_MODEL      = claude-sonnet-4-6       (default shown)
  ANTHROPIC_API_KEY       = sk-ant-...
  GEMINI_API_KEY          = AIza...
  THINKING_BUDGET_TOKENS  = 8000                    (default)

Toggle between providers without touching agent code — just change the env vars.
"""
import json
import logging
import os
import sys
from abc import ABC, abstractmethod

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("niftymind.llm_utils")

# ──────────────────────────────────────────────────────────────────────────────
# Agent tier configuration
# ──────────────────────────────────────────────────────────────────────────────

# Decision agents get Claude + Extended Thinking regardless of DECISION_LLM_PROVIDER
# because Extended Thinking is Claude-exclusive and gives the best trade analysis.
EXTENDED_THINKING_AGENTS = {"agent_9_intraday", "agent_10_btst"}

# All 7 analysis agents use the fast/cheap provider
ANALYSIS_AGENTS = {
    "agent_1_options_chain",
    "agent_2_order_flow",
    "agent_3_volume_profile",
    "agent_4_technical",
    "agent_5_sentiment",
    "agent_6_news",
    "agent_7_macro",
}

THINKING_BUDGET_TOKENS = int(os.getenv("THINKING_BUDGET_TOKENS", "8000"))

# Default models per provider
_DEFAULTS = {
    "claude": {
        "analysis": os.getenv("ANALYSIS_LLM_MODEL", "claude-haiku-4-5-20251001"),
        "decision": os.getenv("DECISION_LLM_MODEL", "claude-sonnet-4-20250514"),
    },
    "gemini": {
        "analysis": os.getenv("ANALYSIS_LLM_MODEL", "gemini-3-flash-preview"),
        "decision": os.getenv("DECISION_LLM_MODEL", "gemini-3.1-pro-preview"),
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# Abstract LLM client interface
# ──────────────────────────────────────────────────────────────────────────────

class BaseLLMClient(ABC):
    """Provider-agnostic LLM interface. Implement for each supported provider."""

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        max_tokens: int,
        use_thinking: bool = False,
        thinking_budget: int = 0,
    ) -> str:
        """Return raw text response from the LLM."""


# ──────────────────────────────────────────────────────────────────────────────
# Claude (Anthropic) client
# ──────────────────────────────────────────────────────────────────────────────

class ClaudeClient(BaseLLMClient):
    """
    Anthropic Claude client.

    Supports Extended Thinking for decision agents — Claude privately reasons
    through all signal combinations and risk factors before producing the
    final JSON trade proposal.
    """

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        max_tokens: int,
        use_thinking: bool = False,
        thinking_budget: int = THINKING_BUDGET_TOKENS,
    ) -> str:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=self._api_key)

        if use_thinking:
            # Extended Thinking requires max_tokens > thinking_budget
            extended_max = thinking_budget + 4096
            response = await client.messages.create(
                model=model,
                max_tokens=extended_max,
                thinking={"type": "enabled", "budget_tokens": thinking_budget},
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            # Extract only the TextBlock (skip ThinkingBlocks)
            for block in response.content:
                if block.type == "text":
                    return block.text
            return ""

        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text


# ──────────────────────────────────────────────────────────────────────────────
# Gemini (Google) client
# ──────────────────────────────────────────────────────────────────────────────

class GeminiClient(BaseLLMClient):
    """
    Google Gemini client using the google-genai SDK.

    Uses thinking_level="HIGH" for decision agents (equivalent to Gemini's
    reasoning mode), and no thinking for fast analysis agents.

    Note on "thought signatures": Google Gemini 3 returns encrypted thought
    signatures in multi-turn conversations. For our single-turn JSON analysis
    calls this is not an issue — each agent call is stateless.
    """

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        max_tokens: int,
        use_thinking: bool = False,
        thinking_budget: int = THINKING_BUDGET_TOKENS,
    ) -> str:
        import asyncio
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)

        # Gemini combines system prompt + user message into a single contents list
        full_prompt = f"{system_prompt}\n\n---\n\n{user_message}"

        config_params: dict = {
            "max_output_tokens": max_tokens,
            "response_mime_type": "application/json",  # enforce JSON output
        }

        if use_thinking:
            config_params["thinking_config"] = types.ThinkingConfig(
                thinking_budget=thinking_budget
            )

        # google-genai SDK is sync — run in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=model,
                contents=full_prompt,
                config=types.GenerateContentConfig(**config_params),
            ),
        )

        return response.text or ""


# ──────────────────────────────────────────────────────────────────────────────
# Client factory & caching
# ──────────────────────────────────────────────────────────────────────────────

_client_cache: dict[str, BaseLLMClient] = {}


def _get_client(provider: str) -> BaseLLMClient:
    if provider in _client_cache:
        return _client_cache[provider]

    if provider == "claude":
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        client: BaseLLMClient = ClaudeClient(api_key=key)

    elif provider == "gemini":
        key = os.getenv("GEMINI_API_KEY", "")
        if not key:
            raise ValueError("GEMINI_API_KEY not set")
        client = GeminiClient(api_key=key)

    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Use 'claude' or 'gemini'.")

    _client_cache[provider] = client
    return client


# ──────────────────────────────────────────────────────────────────────────────
# RAG context injection
# ──────────────────────────────────────────────────────────────────────────────

def _build_rag_system_prompt(system_prompt: str, agent_id: str, query: str) -> str:
    """Prepend retrieved expert knowledge chunks to the system prompt. Fail-open."""
    try:
        from rag.config import AGENT_DOMAINS, rag_config
        from rag.retriever import retrieve_knowledge, format_rag_context

        if not rag_config.enabled:
            return system_prompt

        domain = AGENT_DOMAINS.get(agent_id)
        if not domain:
            return system_prompt

        chunks = retrieve_knowledge(domain, query, top_k=5)
        if not chunks:
            return system_prompt

        rag_context = format_rag_context(chunks)
        logger.debug(f"RAG: {agent_id} got {len(chunks)} chunks ({len(rag_context)} chars)")
        return f"{rag_context}\n\n{system_prompt}"

    except Exception as e:
        logger.debug(f"RAG skipped ({agent_id}): {e}")
        return system_prompt


# ──────────────────────────────────────────────────────────────────────────────
# Main public interface
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_provider_and_model(agent_id: str | None, anthropic_config) -> tuple[str, str, bool]:
    """
    Returns (provider, model, use_thinking) for a given agent.

    Decision:
      - Decision agents (intraday, BTST): Claude + Extended Thinking.
      - Analysis agents: configured via ANALYSIS_LLM_PROVIDER env var (default: gemini).
      - Unknown agents: falls back to anthropic_config or env defaults.
    """
    is_decision = agent_id in EXTENDED_THINKING_AGENTS

    if is_decision:
        # Decision agents always use Claude + Extended Thinking
        provider = "claude"
        model = (
            anthropic_config.model if anthropic_config
            else os.getenv("DECISION_LLM_MODEL", _DEFAULTS["claude"]["decision"])
        )
        return provider, model, True

    if agent_id in ANALYSIS_AGENTS:
        provider = os.getenv("ANALYSIS_LLM_PROVIDER", "gemini").lower()
        model = os.getenv("ANALYSIS_LLM_MODEL", _DEFAULTS[provider]["analysis"])
        return provider, model, False

    # Fallback: use whatever was passed via anthropic_config
    provider = "claude"
    model = (
        anthropic_config.model if anthropic_config
        else os.getenv("ANTHROPIC_MODEL", _DEFAULTS["claude"]["analysis"])
    )
    return provider, model, False


async def query_llm(
    system_prompt: str,
    user_message: str,
    anthropic_config=None,
    agent_id: str | None = None,
    rag_query: str | None = None,
) -> dict:
    """
    Universal LLM query function. Routes to the optimal provider and model
    based on agent type:

      - Analysis agents → Gemini 3 Flash (fast, cheap)
      - Decision agents → Claude Sonnet 4.6 + Extended Thinking (deep, accurate)

    All agents benefit from RAG expert knowledge injection if the knowledge
    base is populated (run knowledge_builder.py once to populate it).

    Returns:
        Parsed JSON dict from the model response.
        Falls back to {"direction": "NEUTRAL", "confidence": 0.3} on any error.
    """
    provider, model, use_thinking = _resolve_provider_and_model(agent_id, anthropic_config)

    # RAG: inject expert domain knowledge into the system prompt
    effective_prompt = system_prompt
    if agent_id:
        query = rag_query or user_message[:500]
        effective_prompt = _build_rag_system_prompt(system_prompt, agent_id, query)

    max_tokens = (
        anthropic_config.max_tokens if anthropic_config
        else int(os.getenv("LLM_MAX_TOKENS", "4096"))
    )

    logger.debug(
        f"LLM call: agent={agent_id} provider={provider} model={model} "
        f"thinking={use_thinking}"
    )

    try:
        client = _get_client(provider)
        raw_text = await client.complete(
            system_prompt=effective_prompt,
            user_message=user_message,
            model=model,
            max_tokens=max_tokens,
            use_thinking=use_thinking,
            thinking_budget=THINKING_BUDGET_TOKENS,
        )
    except Exception as e:
        logger.error(f"LLM call failed ({provider}/{model} for {agent_id}): {e}")
        return {"direction": "NEUTRAL", "confidence": 0.3, "error": str(e)}

    # Parse JSON from response
    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw_text[start:end])
    except json.JSONDecodeError:
        pass

    logger.warning(f"JSON parse failed for {agent_id} ({provider}). Raw: {raw_text[:200]}")
    return {"raw_response": raw_text, "direction": "NEUTRAL", "confidence": 0.3}


# ──────────────────────────────────────────────────────────────────────────────
# Backward-compatible alias (keeps existing import `from agents.llm_utils import query_claude`)
# ──────────────────────────────────────────────────────────────────────────────

async def query_claude(
    system_prompt: str,
    user_message: str,
    anthropic_config=None,
    agent_id: str | None = None,
    rag_query: str | None = None,
) -> dict:
    """Backward-compatible wrapper. New code should use query_llm() directly."""
    return await query_llm(
        system_prompt=system_prompt,
        user_message=user_message,
        anthropic_config=anthropic_config,
        agent_id=agent_id,
        rag_query=rag_query,
    )
