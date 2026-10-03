"""USD per 1M tokens (docs/CONTRACT.md section 9). Checked 2026-10-03; re-verify before quoting."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

logger = logging.getLogger(__name__)

PRICES_CHECKED_ON = date(2026, 10, 3)

# model id prefix -> list of (valid from date, input per 1M, output per 1M), oldest first.
# Output includes thinking tokens. Prefix matching covers versioned ids such as "gemini-3.8-flash-001"
# or "-preview" suffixes; the longest matching prefix wins.
PRICING_USD_PER_MTOK: dict[str, list[tuple[date, float, float]]] = {
    # Introductory price through 2026-12-31, then 1.50 / 7.50.
    "gemini-3.8-flash": [(date(2000, 1, 1), 0.75, 3.75), (date(2027, 1, 1), 1.50, 7.50)],
    "gemini-3.5-flash-lite": [(date(2000, 1, 1), 0.30, 2.50)],
}

_warned: set[str] = set()


def price_for(model: str, on: date | None = None) -> tuple[float, float] | None:
    on = on or datetime.now(UTC).date()
    matches = [p for p in PRICING_USD_PER_MTOK if model == p or model.startswith(p + "-") or model.startswith(p + "@")]
    if not matches:
        return None
    periods = PRICING_USD_PER_MTOK[max(matches, key=len)]
    current = [p for p in periods if p[0] <= on]
    _, price_in, price_out = (current or periods)[-1]
    return price_in, price_out


def estimate_cost_usd(model: str, tokens_in: int, tokens_out: int, on: date | None = None) -> float:
    if model in ("replay", ""):
        return 0.0
    prices = price_for(model, on)
    if prices is None:
        if model not in _warned:
            _warned.add(model)
            logger.warning("No pricing for model %r; cost reported as 0", model)
        return 0.0
    return (tokens_in * prices[0] + tokens_out * prices[1]) / 1_000_000
