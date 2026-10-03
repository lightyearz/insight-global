"""Condition normalisation to a MeSH descriptor (docs/CONTRACT.md section 7.1).

Order, most to least precise (MeSH ``contains``/``startswith`` results are alphabetical, so taking the
first hit picks e.g. "Embolic Stroke" for "stroke"):

1. MeSH lookup ``match=exact`` (case-insensitive): "stroke" -> Stroke.
2. NCBI Entrez ``esearch db=mesh``: its query translation maps entry terms/synonyms to the heading,
   "type 2 diabetes" -> "diabetes mellitus, type 2", "COPD" -> "pulmonary disease, chronic obstructive";
   the heading is then resolved with an exact lookup.
3. ``startswith`` then ``contains``: labels that start with the query first, then the shortest.
4. No match: the typed text is used as-is and PubMed searches ``[Title/Abstract]``.

The method used is returned so the report can show it ("Scope & method").
"""

from __future__ import annotations

import logging
import re

from app.connectors.http import HttpClient, UpstreamError
from app.schemas import Condition, NormalisationMethod

logger = logging.getLogger(__name__)

MESH_LOOKUP_URL = "https://id.nlm.nih.gov/mesh/lookup/descriptor"
MESH_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

_MESH_TERM_RE = re.compile(r'"([^"]+)"\[MeSH Terms\]')


def _descriptor_id(resource: str) -> str:
    return resource.rstrip("/").rsplit("/", 1)[-1]


async def _lookup(http: HttpClient, label: str, match: str, limit: int = 10) -> list[dict[str, str]]:
    try:
        resp = await http.get(MESH_LOOKUP_URL, {"label": label, "match": match, "limit": limit}, attempts=2)
        data = resp.json()
    except (UpstreamError, ValueError) as exc:
        logger.warning("MeSH lookup (%s) failed: %s", match, type(exc).__name__)
        return []
    if not isinstance(data, list):
        return []
    return [h for h in data if isinstance(h, dict) and h.get("label") and h.get("resource")]


async def _entry_term_heading(http: HttpClient, query: str) -> str | None:
    """Heading that Entrez maps the query to, e.g. 'diabetes mellitus, type 2'."""
    try:
        resp = await http.get(
            MESH_ESEARCH_URL, {"db": "mesh", "retmode": "json", "retmax": 1, "term": query}, attempts=2
        )
        translation = str(resp.json().get("esearchresult", {}).get("querytranslation", ""))
    except (UpstreamError, ValueError, AttributeError) as exc:
        logger.warning("MeSH entry-term search failed: %s", type(exc).__name__)
        return None
    m = _MESH_TERM_RE.search(translation)
    return m.group(1) if m else None


def best_partial(query: str, hits: list[dict[str, str]]) -> dict[str, str] | None:
    """Prefer labels starting with the query, then the shortest label (closest to the typed text)."""
    if not hits:
        return None
    q = query.lower()
    return min(hits, key=lambda h: (not h["label"].lower().startswith(q), len(h["label"]), h["label"]))


async def normalize_condition(http: HttpClient, text: str) -> tuple[Condition, NormalisationMethod]:
    query = " ".join(text.split())
    method: NormalisationMethod = "mesh_exact"
    hits = await _lookup(http, query, "exact")
    if not hits:
        method = "mesh_entry_term"
        heading = await _entry_term_heading(http, query)
        hits = await _lookup(http, heading, "exact") if heading else []
    best = hits[0] if hits else None
    if best is None:
        method = "mesh_partial"
        for match in ("startswith", "contains"):
            best = best_partial(query, await _lookup(http, query, match))
            if best is not None:
                break
    if best is None:
        label = query.title() if query.islower() else query
        return Condition(input=text, label=label, mesh_id=None, synonyms=[]), "none"
    synonyms = [query] if query.lower() != best["label"].lower() else []
    condition = Condition(input=text, label=best["label"], mesh_id=_descriptor_id(best["resource"]), synonyms=synonyms)
    return condition, method
