"""Spending insight generation using the Claude Messages API.

Summarizes a list of expenses and asks Claude for a structured JSON
insight object about spending patterns. Never raises: any API, network,
or parsing failure is logged and a safe fallback object is returned instead.
"""

import json
import logging
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 256
SYSTEM_PROMPT = "Respond with JSON only. No prose, no code fences."
FALLBACK_INSIGHT = {
    "summary": "Insights are unavailable right now. Please try again later.",
    "bullets": [],
}


def _summarize_expenses(expenses: list[dict]) -> str:
    """Build a compact text summary of expenses for the prompt.

    Args:
        expenses: Expense dicts, each expected to carry amount_base_minor,
            category, and status.

    Returns:
        A newline-separated summary, one line per expense.
    """
    lines = []
    for expense in expenses:
        amount = expense.get("amount_base_minor")
        category = expense.get("category")
        status = expense.get("status")
        lines.append(f"amount_base_minor={amount}, category={category}, status={status}")
    return "\n".join(lines)


def _build_prompt(summary: str) -> str:
    """Build the user prompt asking for a strict JSON insight object."""
    return (
        "Here is a list of expenses (amounts are in minor units, e.g. paise):\n"
        f"{summary}\n\n"
        "Return a JSON object with exactly these keys:\n"
        '- "summary": a short string summarizing this spending\n'
        '- "bullets": an array of exactly three short strings, each a distinct insight\n'
        "Return JSON only, matching this shape exactly."
    )


def _parse_insight(text: str) -> dict | None:
    """Parse and validate a JSON insight object from model output.

    Returns:
        The parsed dict if it has a string "summary" and a "bullets" array
        of exactly three strings, otherwise None.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("summary"), str):
        return None
    bullets = data.get("bullets")
    if not isinstance(bullets, list) or len(bullets) != 3:
        return None
    if not all(isinstance(bullet, str) for bullet in bullets):
        return None
    return data


def generate_insight(expenses: list[dict]) -> dict:
    """Generate a structured spending insight for a set of expenses.

    Calls Claude once and, if the response isn't valid JSON in the
    expected shape, retries once before falling back to a safe default.

    Args:
        expenses: Expense dicts, each expected to carry amount_base_minor,
            category, and status.

    Returns:
        A dict with a "summary" string and a "bullets" list of exactly
        three strings, or a safe fallback object if generation fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key is not None:
        api_key = api_key.strip()
    summary = _summarize_expenses(expenses)
    prompt = _build_prompt(summary)
    client = anthropic.Anthropic(api_key=api_key)

    for attempt in range(2):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = next(block.text for block in response.content if block.type == "text")
        except Exception:
            logger.exception("Failed to call Claude for spending insight (attempt %d)", attempt + 1)
            continue

        insight = _parse_insight(text)
        if insight is not None:
            return insight
        logger.warning("Claude returned invalid insight JSON on attempt %d: %r", attempt + 1, text)

    return FALLBACK_INSIGHT
