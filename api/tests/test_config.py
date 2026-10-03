import pytest
from pydantic import ValidationError

from tests.conftest import make_settings


def test_auto_resolves_to_replay_without_credentials(tmp_path):
    s = make_settings(tmp_path, LLM_PROVIDER="auto", DATA_MODE="auto")
    assert (s.llm_provider, s.data_mode, s.model_names) == ("replay", "replay", ("replay", "replay"))


def test_auto_prefers_vertex_then_api_key(tmp_path):
    v = make_settings(tmp_path, LLM_PROVIDER="auto", DATA_MODE="auto", google_cloud_project="proj", gemini_api_key="k")
    assert (v.llm_provider, v.data_mode) == ("vertex", "live")
    k = make_settings(tmp_path, LLM_PROVIDER="auto", DATA_MODE="auto", gemini_api_key="test-secret-value-123")
    assert k.llm_provider == "gemini_api"
    assert "test-secret-value-123" not in repr(k)  # secret not echoed


def test_replay_llm_with_live_data_is_rejected(tmp_path):
    with pytest.raises(ValidationError, match="cannot be combined"):
        make_settings(tmp_path, LLM_PROVIDER="replay", DATA_MODE="live")


def test_relative_paths_resolve_against_api_dir(tmp_path):
    s = make_settings(tmp_path, fixtures_dir="../fixtures/replay")
    assert s.fixtures_path.parts[-2:] == ("fixtures", "replay")
    assert s.fixtures_path.is_absolute()
