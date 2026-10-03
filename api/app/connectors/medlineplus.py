"""MedlinePlus Health Topics web service + topic-page Dublin Core dates. docs/CONTRACT.md section 8."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from urllib.parse import urlparse

from defusedxml import ElementTree as SafeET

from app.agent.policy import medlineplus_tier
from app.connectors.http import HttpClient, UpstreamError
from app.schemas import PARTIAL_DATE_PATTERN, Condition, Source, is_allowed_source_url
from app.store import utcnow

logger = logging.getLogger(__name__)

WSEARCH_URL = "https://wsearch.nlm.nih.gov/ws/query"


def strip_html(fragment: str) -> str:
    text = re.sub(r"(?i)</p\s*>|<p(\s[^>]*)?>", "\n\n", fragment)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li(\s[^>]*)?>", "\n- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_wsearch(xml_text: str, *, retrieved_at: datetime) -> list[Source]:
    root = SafeET.fromstring(xml_text)
    out: list[Source] = []
    for doc in root.findall("list/document"):
        url = (doc.get("url") or "").strip()
        if not is_allowed_source_url(url):
            # The URL comes from upstream XML and is fetched later for page dates: never trust it.
            logger.warning("Skipping MedlinePlus document with a non-allowlisted URL")
            continue
        fields: dict[str, str] = {}
        for c in doc.findall("content"):
            name = c.get("name") or ""
            if name and name not in fields:
                fields[name] = c.text or ""
        stem = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")
        excerpt = strip_html(fields.get("FullSummary", ""))
        if not stem or not excerpt:
            continue
        tier, source_type, rationale = medlineplus_tier()
        out.append(
            Source(
                id=f"medlineplus:{re.sub(r'[^A-Za-z0-9._-]', '-', stem)}",
                connector="medlineplus",
                title=strip_html(fields.get("title", "")) or stem,
                publisher=strip_html(fields.get("organizationName", "")) or "National Library of Medicine",
                issuing_body=None,
                authors=[],
                url=url,
                pmid=None,
                doi=None,
                source_type=source_type,
                reliability_tier=tier,
                tier_rationale=rationale,
                region="US",
                published_at=None,
                updated_at=None,
                retrieved_at=retrieved_at,
                excerpt=excerpt,
            )
        )
    return out


_META_RE = r'<meta\s+name="{name}"\s+content="([^"]*)"'


def parse_page_dates(page_html: str) -> tuple[str | None, str | None]:
    """(created, modified) from DC.Date.Created / DC.Date.Modified meta tags."""

    def grab(name: str) -> str | None:
        m = re.search(_META_RE.format(name=re.escape(name)), page_html, flags=re.IGNORECASE)
        value = (m.group(1).strip() if m else "")[:10]
        return value if value and re.fullmatch(PARTIAL_DATE_PATTERN, value) else None

    return grab("DC.Date.Created"), grab("DC.Date.Modified")


class MedlinePlusConnector:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    async def search(self, condition: Condition) -> list[Source]:
        resp = await self.http.get(WSEARCH_URL, {"db": "healthTopics", "term": condition.label, "retmax": 1})
        sources = parse_wsearch(resp.text, retrieved_at=utcnow())
        for s in sources:
            try:
                page = await self.http.get(s.url, attempts=2)
                created, modified = parse_page_dates(page.text)
                s.published_at = created
                s.updated_at = modified if modified != created else None
            except UpstreamError as exc:
                logger.warning("MedlinePlus page dates unavailable for %s: %s", s.id, type(exc).__name__)
        return sources
