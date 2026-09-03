"""LLM usage metering (Section 4.5): log tokens + cost per user per feature."""
from sqlalchemy.orm import Session

from app.db.models import LlmUsage

# USD per 1M tokens: (input, output, cache_read). Update when pricing changes.
PRICES = {
    "claude-sonnet-4-6": (3.00, 15.00, 0.30),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0) -> float:
    inp, out, cached = PRICES.get(model, (0.0, 0.0, 0.0))
    return round((input_tokens * inp + output_tokens * out + cache_read * cached) / 1_000_000, 6)


def record_usage(
    db: Session,
    *,
    user_id: int | None,
    feature: str,
    model: str,
    usage,  # anthropic Usage object or None
    prompt_version: str = "",
) -> LlmUsage:
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    row = LlmUsage(
        user_id=user_id,
        feature=feature,
        model=model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cost_usd=estimate_cost(model, input_tokens, output_tokens, cache_read),
    )
    db.add(row)
    db.flush()
    return row
