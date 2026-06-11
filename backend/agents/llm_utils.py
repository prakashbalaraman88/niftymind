import asyncio
import json
import logging
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("niftymind.llm_utils")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemma-4-31b-it:free"

# Agents treat this as "no opinion" — keeps the pipeline flowing on LLM failure
_NEUTRAL_FALLBACK = {"direction": "NEUTRAL", "confidence": 0.3}

_MAX_ATTEMPTS = 3
_TIMEOUT_SECONDS = 45.0


def _extract_json(raw_text: str) -> dict | None:
    """Pull the first JSON object out of a model reply.

    Handles ```json fences and stray prose around the object. Returns None
    when nothing parseable is found.
    """
    if not raw_text:
        return None
    text = raw_text.strip()
    if text.startswith("```"):
        # Drop the opening fence (with optional language tag) and closing fence
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


async def query_llm(
    system_prompt: str,
    user_message: str,
    llm_config=None,
) -> dict:
    """Query the LLM via OpenRouter (OpenAI-compatible chat completions).

    Returns the parsed JSON object from the model's reply. On any failure
    (missing key, rate limit exhausted, malformed reply) returns a NEUTRAL
    low-confidence dict so agents degrade gracefully instead of erroring.
    """
    api_key = (getattr(llm_config, "api_key", "") or os.getenv("OPENROUTER_API_KEY", ""))
    model = (getattr(llm_config, "model", "") or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL))
    base_url = (getattr(llm_config, "base_url", "") or os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")

    if not api_key:
        logger.error("OPENROUTER_API_KEY not set — returning NEUTRAL fallback")
        return {**_NEUTRAL_FALLBACK, "raw_response": "missing OPENROUTER_API_KEY"}

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # Optional OpenRouter attribution headers
        "HTTP-Referer": "https://niftymind.app",
        "X-Title": "NiftyMind",
    }

    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions", json=payload, headers=headers
                )

            if resp.status_code == 429:
                # Free-tier rate limit (~20 req/min) — back off and retry
                wait = 3.0 * (attempt + 1)
                logger.warning(f"OpenRouter rate-limited (429), retrying in {wait:.0f}s")
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            data = resp.json()
            message = (data.get("choices") or [{}])[0].get("message", {})
            # Some free-tier providers put text in `reasoning` with empty `content`
            raw_text = message.get("content") or message.get("reasoning") or ""

            parsed = _extract_json(raw_text)
            if parsed is not None:
                return parsed

            # Malformed/empty reply — treat like a soft failure and retry
            logger.warning(
                f"Could not parse JSON from LLM response "
                f"(attempt {attempt + 1}/{_MAX_ATTEMPTS}): {raw_text[:120]!r}"
            )
            last_error = ValueError("unparseable LLM response")
            if attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            return {"raw_response": raw_text, **_NEUTRAL_FALLBACK}

        except Exception as e:
            last_error = e
            if attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(1.5 * (attempt + 1))

    logger.error(f"OpenRouter query failed after {_MAX_ATTEMPTS} attempts: {last_error}")
    return {**_NEUTRAL_FALLBACK, "raw_response": f"LLM error: {last_error}"}


# Backward-compatible alias
query_claude = query_llm
