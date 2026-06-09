"""
Groq LLM Client  (100% FREE - no credit card needed)
====================================================
Central helper used by every custom module.
Groq is OpenAI-compatible: same SDK, different base_url + model names.

Free tier limits (2025-2026):
  llama-3.3-70b-versatile  : 1,000 req/day, 6,000 TPM   <- best quality
  llama-3.1-8b-instant     : 14,400 req/day, 30,000 TPM  <- high volume
  llama-4-scout-17b        : best TPM on free tier (30,000 TPM)

Get your free key: https://console.groq.com  (no CC needed)
"""

import time
import logging
from openai import OpenAI, RateLimitError, APIStatusError

logger = logging.getLogger("groq_client")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Model aliases
GROQ_QUALITY  = "llama-3.3-70b-versatile"   # use for: emails, tailoring, form answers
GROQ_FAST     = "llama-3.1-8b-instant"       # use for: keyword extraction, scoring


def get_client(api_key: str) -> OpenAI:
    """Return an OpenAI-compatible client pointing at Groq."""
    return OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)


def chat(
    api_key: str,
    messages: list,
    model: str = GROQ_QUALITY,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    retries: int = 3,
) -> str:
    """
    Single chat completion with automatic retry on rate-limit.
    Returns the assistant message content as a string.
    """
    client = get_client(api_key)
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""

        except RateLimitError:
            wait = (attempt + 1) * 20   # 20s, 40s, 60s
            logger.warning(f"Groq rate limit hit. Waiting {wait}s (attempt {attempt+1}/{retries})...")
            time.sleep(wait)

        except APIStatusError as e:
            if e.status_code == 429:
                wait = (attempt + 1) * 20
                logger.warning(f"Groq 429. Waiting {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"Groq API error {e.status_code}: {e.message}")
                raise

    raise RuntimeError(f"Groq call failed after {retries} retries (rate limit). Try again in a few minutes.")
