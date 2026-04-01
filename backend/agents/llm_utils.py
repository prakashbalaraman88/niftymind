import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("niftymind.llm_utils")


async def query_llm(
    system_prompt: str,
    user_message: str,
    llm_config=None,
) -> dict:
    """Query Gemini API with system prompt and user message. Returns parsed JSON dict."""
    from google import genai
    from google.genai import types

    api_key = llm_config.api_key if llm_config else os.getenv("GEMINI_API_KEY", "")
    model = llm_config.model if llm_config else os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    client = genai.Client(api_key=api_key)

    response = await client.aio.models.generate_content(
        model=model,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
        ),
    )

    raw_text = response.text

    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw_text[start:end])
    except json.JSONDecodeError:
        pass

    logger.warning("Could not parse JSON from Gemini response, returning raw text")
    return {"raw_response": raw_text, "direction": "NEUTRAL", "confidence": 0.3}


# Backward-compatible alias
query_claude = query_llm
