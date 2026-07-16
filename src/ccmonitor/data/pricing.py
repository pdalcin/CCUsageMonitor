"""Token -> USD cost estimation.

Prices are USD per **million tokens** (MTok). Cache reads and cache writes are
billed differently from fresh input tokens, so we price each bucket separately.

This is a best-effort *estimate* for the overlay's live cost readout, not billing
truth. Prices drift; keep this table as the single place to edit. Unknown models
return a cost of 0 and set ``known=False`` so the UI can show "?".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input: float          # per MTok, fresh input
    output: float         # per MTok, output
    cache_write: float    # per MTok, writing to cache (ephemeral)
    cache_read: float     # per MTok, reading from cache


# Keyed by a substring matched against the model id (longest match wins), so
# both "claude-opus-4-8" and dated variants resolve. Update as models/prices change.
_PRICES: dict[str, ModelPrice] = {
    "opus":   ModelPrice(input=15.0, output=75.0, cache_write=18.75, cache_read=1.50),
    "sonnet": ModelPrice(input=3.0,  output=15.0, cache_write=3.75,  cache_read=0.30),
    "haiku":  ModelPrice(input=0.80, output=4.0,  cache_write=1.0,   cache_read=0.08),
    # Fable pricing not yet published; treated as unknown until added.
}


def _match(model: str) -> ModelPrice | None:
    m = (model or "").lower()
    best_key = None
    for key in _PRICES:
        if key in m and (best_key is None or len(key) > len(best_key)):
            best_key = key
    return _PRICES[best_key] if best_key else None


@dataclass
class CostBreakdown:
    total: float
    known: bool
    model: str


def cost(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> CostBreakdown:
    """Estimate USD cost for one model's token usage."""
    price = _match(model)
    if price is None:
        return CostBreakdown(total=0.0, known=False, model=model)
    total = (
        input_tokens * price.input
        + output_tokens * price.output
        + cache_creation_tokens * price.cache_write
        + cache_read_tokens * price.cache_read
    ) / 1_000_000
    return CostBreakdown(total=total, known=True, model=model)
