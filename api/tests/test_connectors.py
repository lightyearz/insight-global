from datetime import UTC, datetime

import pytest
import respx
from httpx import Response

from app.agent.nodes.retrieve_sources import select_sources
from app.connectors import clinical_tables
from app.connectors.clinical_tables import CLINICAL_TABLES_URL, suggest_conditions
from app.connectors.http import DisallowedHostError, HttpClient, UpstreamError, redact
from app.connectors.medlineplus import WSEARCH_URL, MedlinePlusConnector, parse_page_dates, parse_wsearch
from app.connectors.mesh import MESH_ESEARCH_URL, MESH_LOOKUP_URL, normalize_condition
from app.connectors.pubmed import EUTILS, PubMedConnector, parse_pubmed_xml
from app.schemas import Condition
from tests.conftest import make_settings

NOW = datetime(2026, 10, 3, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_suggestion_cache():
    clinical_tables._cache.clear()
    yield
    clinical_tables._cache.clear()


PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
 <PubmedArticle>
  <MedlineCitation><PMID Version="1">111</PMID>
   <Article>
    <Journal><JournalIssue><PubDate><Year>2025</Year><Month>Oct</Month></PubDate></JournalIssue>
     <Title>Hypertension (Dallas)</Title></Journal>
    <ArticleTitle>2025 Guideline for <i>High</i> Blood Pressure.</ArticleTitle>
    <Abstract>
     <AbstractText Label="AIM">Replace the 2017 guideline.</AbstractText>
     <AbstractText Label="METHODS">A search was conducted.</AbstractText>
    </Abstract>
    <AuthorList>
     <Author><CollectiveName>Writing Committee</CollectiveName></Author>
     <Author><LastName>Jones</LastName><ForeName>Daniel W</ForeName><Initials>DW</Initials></Author>
    </AuthorList>
    <PublicationTypeList><PublicationType>Journal Article</PublicationType>
     <PublicationType>Practice Guideline</PublicationType></PublicationTypeList>
    <ArticleDate DateType="Electronic"><Year>2025</Year><Month>08</Month><Day>14</Day></ArticleDate>
   </Article>
  </MedlineCitation>
  <PubmedData><ArticleIdList><ArticleId IdType="pubmed">111</ArticleId>
   <ArticleId IdType="doi">10.1/abc</ArticleId></ArticleIdList></PubmedData>
 </PubmedArticle>
 <PubmedArticle>
  <MedlineCitation><PMID Version="1">222</PMID>
   <Article>
    <Journal><JournalIssue><PubDate><MedlineDate>2021 Nov-Dec</MedlineDate></PubDate></JournalIssue>
     <Title>Reviews</Title></Journal>
    <ArticleTitle>A systematic review.</ArticleTitle>
    <Abstract><AbstractText>Unlabelled abstract.</AbstractText></Abstract>
    <PublicationTypeList><PublicationType>Systematic Review</PublicationType></PublicationTypeList>
   </Article>
  </MedlineCitation>
 </PubmedArticle>
 <PubmedArticle>
  <MedlineCitation><PMID Version="1">333</PMID>
   <Article><Journal><Title>No abstract</Title></Journal><ArticleTitle>Skip me</ArticleTitle></Article>
  </MedlineCitation>
 </PubmedArticle>
</PubmedArticleSet>"""


def test_parse_pubmed_xml():
    sources = parse_pubmed_xml(PUBMED_XML, retrieved_at=NOW)
    assert [s.id for s in sources] == ["pubmed:111", "pubmed:222"]
    g, r = sources
    assert g.title == "2025 Guideline for High Blood Pressure."
    assert g.publisher == "Hypertension (Dallas)"
    assert g.authors == ["Writing Committee", "Jones DW"]
    assert g.doi == "10.1/abc" and g.pmid == "111"
    assert g.published_at == "2025-08-14"  # electronic date preferred
    assert g.updated_at is None
    assert g.excerpt == "AIM: Replace the 2017 guideline.\n\nMETHODS: A search was conducted."
    assert (g.reliability_tier, g.source_type) == (1, "clinical_guideline")
    assert g.url == "https://pubmed.ncbi.nlm.nih.gov/111/"
    assert r.published_at == "2021-11" and r.reliability_tier == 2


WSEARCH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult><list num="1" start="0" per="1">
 <document rank="0" url="https://medlineplus.gov/diabetestype2.html">
  <content name="title">&lt;span class="qt3"&gt;Diabetes&lt;/span&gt; Type 2</content>
  <content name="organizationName">National Library of Medicine</content>
  <content name="FullSummary">What is it?&lt;p&gt;Type 2 &lt;span&gt;diabetes&lt;/span&gt; is a disease &amp;amp; more.&lt;/p&gt;&lt;p&gt;Second.&lt;/p&gt;</content>
 </document>
</list></nlmSearchResult>"""

PAGE = '<meta name="DC.Date.Modified" content="2026-01-21"/>\n<meta name="DC.Date.Created" content="2011-12-05"/>'


def test_parse_medlineplus():
    [s] = parse_wsearch(WSEARCH_XML, retrieved_at=NOW)
    assert s.id == "medlineplus:diabetestype2"
    assert s.title == "Diabetes Type 2"
    assert s.excerpt == "What is it?\n\nType 2 diabetes is a disease & more.\n\nSecond."
    assert s.region == "US" and s.reliability_tier == 3
    assert parse_page_dates(PAGE) == ("2011-12-05", "2026-01-21")
    assert parse_page_dates("<html></html>") == (None, None)


@respx.mock
async def test_medlineplus_connector_reads_page_dates():
    respx.get(WSEARCH_URL).mock(return_value=Response(200, text=WSEARCH_XML))
    respx.get("https://medlineplus.gov/diabetestype2.html").mock(return_value=Response(200, text=PAGE))
    http = HttpClient(5)
    try:
        [s] = await MedlinePlusConnector(http).search(Condition(input="t2d", label="Diabetes Mellitus, Type 2"))
    finally:
        await http.aclose()
    assert (s.published_at, s.updated_at) == ("2011-12-05", "2026-01-21")


@respx.mock
async def test_pubmed_connector_search_dedupes_and_sends_tool_params(tmp_path):
    settings = make_settings(tmp_path, ncbi_email="ops@example.org")
    es = respx.get(f"{EUTILS}/esearch.fcgi").mock(
        side_effect=[
            Response(200, json={"esearchresult": {"idlist": ["111", "222"]}}),
            Response(200, json={"esearchresult": {"idlist": ["222"]}}),
        ]
    )
    ef = respx.get(f"{EUTILS}/efetch.fcgi").mock(return_value=Response(200, text=PUBMED_XML))
    http = HttpClient(5)
    try:
        sources = await PubMedConnector(http, settings).search(
            Condition(input="x", label="Hypertension", mesh_id="D006973")
        )
    finally:
        await http.aclose()
    assert [s.id for s in sources] == ["pubmed:111", "pubmed:222"]
    first = es.calls[0].request.url.params
    assert first["tool"] == "health-briefing-poc" and first["email"] == "ops@example.org"
    assert '"Hypertension"[MeSH Major Topic]' in first["term"] and "Practice Guideline[pt]" in first["term"]
    assert "Systematic Review[pt]" in es.calls[1].request.url.params["term"]
    assert ef.calls[0].request.url.params["id"] == "111,222"
    assert "api_key" not in str(ef.calls[0].request.url)


@respx.mock
async def test_http_retries_on_503():
    route = respx.get("https://id.nlm.nih.gov/x").mock(side_effect=[Response(503), Response(200, text="ok")])
    http = HttpClient(5)
    try:
        resp = await http.get("https://id.nlm.nih.gov/x")
    finally:
        await http.aclose()
    assert resp.text == "ok" and route.call_count == 2


def test_redact():
    assert redact("https://x/?a=1&api_key=SECRET&b=2") == "https://x/?a=1&api_key=***&b=2"


def _mesh_lookup(req):
    label, match = req.url.params["label"].lower(), req.url.params["match"]
    table = {
        ("stroke", "exact"): [{"resource": "http://id.nlm.nih.gov/mesh/D020521", "label": "Stroke"}],
        ("diabetes mellitus, type 2", "exact"): [
            {"resource": "http://id.nlm.nih.gov/mesh/D003924", "label": "Diabetes Mellitus, Type 2"}
        ],
        ("rare thing", "contains"): [
            {"resource": "http://id.nlm.nih.gov/mesh/D1", "label": "Atypical Rare Thing Syndrome"},
            {"resource": "http://id.nlm.nih.gov/mesh/D2", "label": "Rare Thing"},
            {"resource": "http://id.nlm.nih.gov/mesh/D3", "label": "Rare Thing, Familial"},
        ],
    }
    return Response(200, json=table.get((label, match), []))


def _mesh_esearch(req):
    term = req.url.params["term"].lower()
    translation = {
        "type 2 diabetes": '"diabetes mellitus, type 2"[MeSH Terms] OR type 2 diabetes[Text Word]',
    }.get(term, f"{term}[All Fields]")
    return Response(200, json={"esearchresult": {"idlist": [], "querytranslation": translation}})


@respx.mock
async def test_mesh_normalisation_exact_entry_term_partial_and_none():
    respx.get(MESH_LOOKUP_URL).mock(side_effect=_mesh_lookup)
    respx.get(MESH_ESEARCH_URL).mock(side_effect=_mesh_esearch)
    http = HttpClient(5, host_rates={})
    try:
        stroke = await normalize_condition(http, "stroke")
        t2d = await normalize_condition(http, "type 2 diabetes")
        rare = await normalize_condition(http, "rare thing")
        none = await normalize_condition(http, "zzz unknown")
    finally:
        await http.aclose()
    # exact first: "stroke" must not become "Embolic Stroke" (alphabetical contains results)
    assert (stroke[0].label, stroke[0].mesh_id, stroke[1]) == ("Stroke", "D020521", "mesh_exact")
    # synonyms resolve through Entrez's query translation
    assert (t2d[0].label, t2d[0].mesh_id, t2d[1]) == ("Diabetes Mellitus, Type 2", "D003924", "mesh_entry_term")
    assert t2d[0].synonyms == ["type 2 diabetes"] and t2d[0].input == "type 2 diabetes"
    # partial: label starting with the query, then the shortest
    assert (rare[0].label, rare[1]) == ("Rare Thing", "mesh_partial")
    assert (none[0].label, none[0].mesh_id, none[1]) == ("Zzz Unknown", None, "none")


@respx.mock
async def test_clinical_tables_suggest():
    respx.get(CLINICAL_TABLES_URL).mock(
        return_value=Response(200, json=[2, ["1", "2"], None, [["Diabetes mellitus", "E11.9"], ["Retinopathy", ""]]])
    )
    http = HttpClient(5)
    try:
        out = await suggest_conditions(http, "diab")
    finally:
        await http.aclose()
    assert [(s.label, s.code, s.source) for s in out] == [
        ("Diabetes mellitus", "E11.9", "clinical_tables"),
        ("Retinopathy", None, "clinical_tables"),
    ]


@respx.mock
async def test_clinical_tables_failure_returns_empty():
    respx.get(CLINICAL_TABLES_URL).mock(return_value=Response(500))
    http = HttpClient(5)
    try:
        assert await suggest_conditions(http, "diab") == []
    finally:
        await http.aclose()


def test_select_sources_keeps_medlineplus():
    pm = parse_pubmed_xml(PUBMED_XML, retrieved_at=NOW)
    mp = parse_wsearch(WSEARCH_XML, retrieved_at=NOW)
    out = select_sources([*pm, pm[0], *mp], max_sources=2)
    assert [s.id for s in out] == ["pubmed:111", "medlineplus:diabetestype2"]
    copublished = pm[0].model_copy(update={"id": "pubmed:999", "title": "2025 guideline for high blood pressure"})
    assert [s.id for s in select_sources([pm[0], copublished, pm[1]], 10)] == ["pubmed:111", "pubmed:222"]


# --- security / robustness of the shared HTTP client ------------------------------------------


@respx.mock
async def test_disallowed_hosts_and_schemes_are_blocked():
    http = HttpClient(5)
    try:
        for url in ("https://169.254.169.254/latest", "http://medlineplus.gov/x.html", "https://evil.example/x"):
            with pytest.raises(DisallowedHostError):
                await http.get(url)
    finally:
        await http.aclose()


@respx.mock
async def test_redirect_to_disallowed_host_is_blocked():
    respx.get("https://medlineplus.gov/x.html").mock(
        return_value=Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data"})
    )
    http = HttpClient(5)
    try:
        with pytest.raises(UpstreamError):
            await http.get("https://medlineplus.gov/x.html")
    finally:
        await http.aclose()


@respx.mock
async def test_errors_never_contain_query_string_or_key(caplog, tmp_path):
    settings = make_settings(tmp_path, ncbi_api_key="SECRETKEY123")
    respx.get(f"{EUTILS}/esearch.fcgi").mock(return_value=Response(400))
    http = HttpClient(5, host_rates={})
    caplog.set_level("DEBUG")
    try:
        with pytest.raises(UpstreamError) as info:
            await PubMedConnector(http, settings).esearch("x", 1)
    finally:
        await http.aclose()
    assert str(info.value) == "HTTP 400 from eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    assert info.value.status_code == 400
    assert "SECRETKEY123" not in caplog.text
    from app.agent.nodes.retrieve_sources import failure_summary

    assert failure_summary(info.value) == "UpstreamError (HTTP 400)"


@respx.mock
async def test_retry_after_is_honoured(monkeypatch):
    waits: list[float] = []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    respx.get("https://id.nlm.nih.gov/y").mock(
        side_effect=[Response(429, headers={"Retry-After": "7"}), Response(200, text="ok")]
    )
    http = HttpClient(5, host_rates={})
    try:
        assert (await http.get("https://id.nlm.nih.gov/y")).text == "ok"
    finally:
        await http.aclose()
    assert 7.0 in waits


@respx.mock
async def test_body_size_is_capped():
    respx.get("https://id.nlm.nih.gov/big").mock(return_value=Response(200, content=b"x" * 2048))
    http = HttpClient(5, host_rates={}, max_body_bytes=1024)
    try:
        with pytest.raises(UpstreamError, match="exceeds"):
            await http.get("https://id.nlm.nih.gov/big")
    finally:
        await http.aclose()


def test_medlineplus_documents_with_unsafe_urls_are_skipped():
    bad = WSEARCH_XML.replace("https://medlineplus.gov/diabetestype2.html", "http://169.254.169.254/x.html")
    assert parse_wsearch(bad, retrieved_at=NOW) == []


def test_pubmed_query_term_is_sanitised(tmp_path):
    from app.connectors.pubmed import build_queries

    settings = make_settings(tmp_path)
    [(g, _), _] = build_queries(Condition(input="x", label='Foo" OR "bar[pt]', mesh_id=None), settings, NOW)
    assert g.startswith('("Foo OR bar pt"[Title/Abstract])')


@respx.mock
async def test_clinical_tables_results_are_cached():
    route = respx.get(CLINICAL_TABLES_URL).mock(return_value=Response(200, json=[1, ["1"], None, [["Asthma", "J45"]]]))
    http = HttpClient(5, host_rates={})
    try:
        a = await suggest_conditions(http, "asth")
        b = await suggest_conditions(http, "  ASTH ")
    finally:
        await http.aclose()
    assert a == b and route.call_count == 1
