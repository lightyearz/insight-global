"""NLM Clinical Tables conditions API, for autocomplete (docs/CONTRACT.md section 8)."""

from __future__ import annotations

import logging
import time

from app.connectors.http import HttpClient, UpstreamError
from app.schemas import ConditionSuggestion

logger = logging.getLogger(__name__)

CLINICAL_TABLES_URL = "https://clinicaltables.nlm.nih.gov/api/conditions/v3/search"


_CACHE_TTL_S = 600.0
_CACHE_MAX = 512
_cache: dict[tuple[str, int], tuple[float, list[ConditionSuggestion]]] = {}


async def suggest_conditions(http: HttpClient, q: str, limit: int = 10) -> list[ConditionSuggestion]:
    """Autocomplete, cached for 10 minutes per (query, limit): the UI asks on every debounced keystroke."""
    key = (" ".join(q.lower().split()), limit)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL_S:
        return list(hit[1])
    out = await _fetch_suggestions(http, q, limit)
    if out:  # failures are not cached
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic(), out)
    return list(out)


async def _fetch_suggestions(http: HttpClient, q: str, limit: int) -> list[ConditionSuggestion]:
    try:
        resp = await http.get(
            CLINICAL_TABLES_URL,
            {"terms": q, "maxList": limit, "df": "primary_name,icd10cm_codes"},
            attempts=2,
        )
        data = resp.json()
        rows = data[3] if isinstance(data, list) and len(data) > 3 and isinstance(data[3], list) else []
    except (UpstreamError, ValueError) as exc:
        logger.warning("Clinical Tables lookup failed: %s", type(exc).__name__)
        return []
    out: list[ConditionSuggestion] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, list) or not row or not row[0]:
            continue
        label = str(row[0])
        if label.lower() in seen:
            continue
        seen.add(label.lower())
        codes = str(row[1]) if len(row) > 1 and row[1] else ""
        code = codes.split(",")[0].strip() or None
        out.append(ConditionSuggestion(label=label, code=code, source="clinical_tables"))
    return out[:limit]
