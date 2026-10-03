"""PubMed via NCBI E-utilities (esearch JSON + efetch XML). docs/CONTRACT.md section 8."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree as SafeET

from app.agent.policy import pubmed_tier
from app.config import Settings
from app.connectors.http import HttpClient
from app.schemas import Condition, Source
from app.store import utcnow

logger = logging.getLogger(__name__)

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

_MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTHS = {m: i for i, m in enumerate(_MONTH_NAMES, 1)}
_SEASONS = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 12}


class PubMedConnector:
    def __init__(self, http: HttpClient, settings: Settings) -> None:
        self.http = http
        self.settings = settings
        if settings.ncbi_api_key.get_secret_value():
            # One limiter per host is shared with the MeSH entry-term search on the same host.
            http.set_rate(httpx.URL(EUTILS).host, 10)

    def _common_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"tool": self.settings.ncbi_tool}
        if self.settings.ncbi_email:
            params["email"] = self.settings.ncbi_email
        key = self.settings.ncbi_api_key.get_secret_value()
        if key:
            params["api_key"] = key
        return params

    def build_queries(self, condition: Condition, now: datetime | None = None) -> list[tuple[str, int]]:
        return build_queries(condition, self.settings, now)

    async def esearch(self, term: str, retmax: int) -> list[str]:
        params = {"db": "pubmed", "retmode": "json", "sort": "relevance", "retmax": retmax, "term": term}
        resp = await self.http.get(f"{EUTILS}/esearch.fcgi", params | self._common_params())
        ids = resp.json().get("esearchresult", {}).get("idlist", [])
        return [str(i) for i in ids if str(i).isdigit()]

    async def efetch(self, pmids: list[str]) -> list[Source]:
        if not pmids:
            return []
        params = {"db": "pubmed", "retmode": "xml", "id": ",".join(pmids)}
        resp = await self.http.get(f"{EUTILS}/efetch.fcgi", params | self._common_params())
        return parse_pubmed_xml(resp.text, retrieved_at=utcnow())

    async def search(self, condition: Condition) -> list[Source]:
        id_lists = await asyncio.gather(*(self.esearch(t, n) for t, n in self.build_queries(condition)))
        pmids: list[str] = []
        for ids in id_lists:
            pmids.extend(i for i in ids if i not in pmids)
        sources = await self.efetch(pmids)
        order = {p: i for i, p in enumerate(pmids)}
        return sorted(sources, key=lambda s: order.get(s.pmid or "", 1_000_000))


def query_term(label: str) -> str:
    """Strip characters that would break out of the quoted PubMed term (quotes, field tags)."""
    return " ".join(re.sub(r'["\[\]]', " ", label).split())


def build_queries(condition: Condition, settings: Settings, now: datetime | None = None) -> list[tuple[str, int]]:
    """(term, retmax) pairs: guidelines, then systematic reviews / meta-analyses, last ``pubmed_years``."""
    year = (now or utcnow()).year - settings.pubmed_years
    label = query_term(condition.label)
    # [MeSH Major Topic]: the article is *about* the condition (plain [MeSH Terms] also matches articles
    # where it is a minor index term, which pulled unrelated guidelines into early live runs).
    c = f'"{label}"[MeSH Major Topic]' if condition.mesh_id else f'"{label}"[Title/Abstract]'
    filters = f'("{year}"[dp] : "3000"[dp]) AND English[la] AND hasabstract'
    guidelines = f"({c}) AND (Practice Guideline[pt] OR Guideline[pt]) AND {filters}"
    reviews = (
        f"({c}) AND (Systematic Review[pt] OR Meta-Analysis[pt]) AND (therapy OR treatment OR management) AND {filters}"
    )
    return [(guidelines, settings.pubmed_guideline_max), (reviews, settings.pubmed_review_max)]


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------


def _text(el: Element | None) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _month(value: str) -> int | None:
    v = value.strip().lower()
    if v.isdigit():
        n = int(v)
        return n if 1 <= n <= 12 else None
    return _MONTHS.get(v[:3]) or _SEASONS.get(v)


def _partial_date(year: str, month: str = "", day: str = "") -> str | None:
    if not re.fullmatch(r"\d{4}", year.strip()):
        return None
    out = year.strip()
    m = _month(month) if month else None
    if m:
        out += f"-{m:02d}"
        if day.strip().isdigit() and 1 <= int(day) <= 31:
            out += f"-{int(day):02d}"
    return out


def _published_at(article: Element) -> str | None:
    for ad in article.findall("ArticleDate"):
        if ad.get("DateType") == "Electronic":
            d = _partial_date(_text(ad.find("Year")), _text(ad.find("Month")), _text(ad.find("Day")))
            if d:
                return d
    pub = article.find("Journal/JournalIssue/PubDate")
    if pub is None:
        return None
    if pub.find("Year") is not None:
        return _partial_date(_text(pub.find("Year")), _text(pub.find("Month")), _text(pub.find("Day")))
    medline = _text(pub.find("MedlineDate"))  # e.g. "2021 Nov-Dec" or "2020-2021"
    m = re.match(r"(\d{4})(?:\s+([A-Za-z]+))?", medline)
    if m:
        return _partial_date(m.group(1), m.group(2) or "")
    return None


def _authors(article: Element) -> list[str]:
    out: list[str] = []
    for a in article.findall("AuthorList/Author"):
        collective = _text(a.find("CollectiveName"))
        if collective:
            out.append(collective)
            continue
        last, initials = _text(a.find("LastName")), _text(a.find("Initials"))
        if last:
            out.append(f"{last} {initials}".strip())
    return out


def _excerpt(article: Element) -> str:
    parts: list[str] = []
    for at in article.findall("Abstract/AbstractText"):
        body = _text(at)
        if not body:
            continue
        label = at.get("Label")
        parts.append(f"{label}: {body}" if label else body)
    return "\n\n".join(parts)


def parse_pubmed_xml(xml_text: str, *, retrieved_at: datetime) -> list[Source]:
    root = SafeET.fromstring(xml_text)
    sources: list[Source] = []
    for art in root.findall("PubmedArticle"):
        citation = art.find("MedlineCitation")
        if citation is None:
            continue
        pmid = _text(citation.find("PMID"))
        article = citation.find("Article")
        if not pmid.isdigit() or article is None:
            continue
        excerpt = _excerpt(article)
        if not excerpt:
            continue
        pub_types = [_text(pt) for pt in article.findall("PublicationTypeList/PublicationType")]
        title = _text(article.find("ArticleTitle")) or f"PubMed {pmid}"
        tier, source_type, rationale = pubmed_tier(pub_types, title)
        doi = None
        for aid in art.findall("PubmedData/ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = _text(aid) or None
        try:
            sources.append(
                Source(
                    id=f"pubmed:{pmid}",
                    connector="pubmed",
                    title=title,
                    publisher=_text(article.find("Journal/Title")) or "PubMed",
                    issuing_body=None,
                    authors=_authors(article),
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    pmid=pmid,
                    doi=doi,
                    source_type=source_type,
                    reliability_tier=tier,
                    tier_rationale=rationale,
                    region=None,
                    published_at=_published_at(article),
                    # DateRevised is record maintenance, not a content revision.
                    updated_at=None,
                    retrieved_at=retrieved_at,
                    excerpt=excerpt,
                )
            )
        except ValueError as exc:
            logger.warning("Skipping PubMed %s: %s", pmid, exc)
    return sources
