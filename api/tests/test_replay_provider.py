import pytest

from app.agent.llm_outputs import (
    ConsolidateOptionsOutput,
    ExtractTreatmentsOutput,
    LLMError,
    LLMRequest,
    ReplayFixtureMissing,
    WriteReportOutput,
)
from app.connectors.replay import ReplayConnector
from app.llm.replay import ReplayLLMClient
from tests.conftest import TEST_FIXTURES


async def test_replay_loads_per_source_fixture():
    client = ReplayLLMClient(TEST_FIXTURES)
    req = LLMRequest(
        step="extract_treatments", system="s", prompt="p", item_key="pubmed:1000001", fixture_slug="test-condition"
    )
    res = await client.generate(req, ExtractTreatmentsOutput)
    assert res.model == "replay" and res.tokens_in == 0 and res.tokens_out == 0
    assert [t.name for t in res.parsed.treatments] == ["Alphamab", "Betacillin", "Structured exercise"]


async def test_replay_loads_step_fixture():
    client = ReplayLLMClient(TEST_FIXTURES)
    req = LLMRequest(step="consolidate_options", system="s", prompt="p", fixture_slug="test-condition")
    res = await client.generate(req, ConsolidateOptionsOutput)
    assert len(res.parsed.options) == 3


async def test_replay_missing_fixture_raises():
    client = ReplayLLMClient(TEST_FIXTURES)
    req = LLMRequest(
        step="extract_treatments", system="s", prompt="p", item_key="pubmed:999", fixture_slug="test-condition"
    )
    with pytest.raises(ReplayFixtureMissing, match=r"pubmed_999\.json"):
        await client.generate(req, ExtractTreatmentsOutput)


async def test_replay_invalid_fixture_raises(tmp_path):
    folder = tmp_path / "bad" / "llm"
    folder.mkdir(parents=True)
    (folder / "write_report.json").write_text('{"title": "x"}')
    client = ReplayLLMClient(tmp_path)
    req = LLMRequest(step="write_report", system="s", prompt="p", fixture_slug="bad")
    with pytest.raises(LLMError, match="invalid"):
        await client.generate(req, WriteReportOutput)


def test_replay_connector_matching_and_suggest():
    rc = ReplayConnector(TEST_FIXTURES)
    assert [m.slug for m in rc.manifests()] == ["test-condition"]
    assert rc.match("  TEST   condition ").slug == "test-condition"
    assert rc.match("tc").slug == "test-condition"
    assert rc.match("test-condition").slug == "test-condition"
    assert rc.match("diabetes") is None
    assert [s.label for s in rc.suggest("test")] == ["Test condition"]
    assert rc.condition("test-condition", "tc").input == "tc"
    assert len(rc.sources("test-condition")) == 3


def test_replay_connector_missing_dir(tmp_path):
    assert ReplayConnector(tmp_path / "nope").manifests() == []
