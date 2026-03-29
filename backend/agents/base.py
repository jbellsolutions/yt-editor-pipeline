"""
Shared agent utilities for Claude API calls.
"""
import json
import re
import time
import logging
import anthropic

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def call_claude(
    prompt: str,
    system: str,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 2000,
    temperature: float = 0.3,
) -> str:
    """
    Single Claude API call with retry (3 retries, exponential backoff).
    Returns the text content of the response.
    """
    client = anthropic.Anthropic()
    last_error = None

    for attempt in range(4):  # initial + 3 retries
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            last_error = e
            if attempt < 3:
                wait = 2 ** attempt  # 1, 2, 4 seconds
                logger.warning(
                    f"Claude API attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                logger.error(f"Claude API failed after 4 attempts: {e}")

    raise last_error


def call_claude_json(
    prompt: str,
    system: str,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 2000,
    temperature: float = 0.3,
) -> dict:
    """
    Calls call_claude, parses JSON from response.
    Handles markdown code blocks (```json ... ```).
    Retries on parse failure (up to 2 extra attempts).
    """
    parse_errors = []

    for attempt in range(3):
        try:
            raw = call_claude(prompt, system, model, max_tokens, temperature)

            # Strip markdown code blocks if present
            text = raw.strip()
            pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                text = match.group(1).strip()

            return json.loads(text)
        except json.JSONDecodeError as e:
            parse_errors.append(str(e))
            logger.warning(
                f"JSON parse attempt {attempt + 1} failed: {e}. "
                f"Raw response preview: {raw[:200] if raw else empty}"
            )
            if attempt < 2:
                # Add hint to prompt for retry
                prompt = (
                    prompt
                    + "\n\nIMPORTANT: Respond with ONLY valid JSON. "
                    "No markdown, no explanation, just the JSON object."
                )

    raise ValueError(
        f"Failed to parse JSON after 3 attempts. Errors: {parse_errors}"
    )
