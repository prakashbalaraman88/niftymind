import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("niftymind.llm_utils")


async def query_claude(
    system_prompt: str,
    user_message: str,
    anthropic_config=None,
) -> dict:
    from anthropic import AsyncAnthropic

    api_key = anthropic_config.api_key if anthropic_config else os.getenv("ANTHROPIC_API_KEY", "")
    model = anthropic_config.model if anthropic_config else os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    max_tokens = anthropic_config.max_tokens if anthropic_config else 4096

    client = AsyncAnthropic(api_key=api_key)

    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
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
