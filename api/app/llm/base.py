"""LLM client factory (provider resolved by Settings, docs/CONTRACT.md section 9)."""

from __future__ import annotations

from app.agent.llm_outputs import LLMClient
from app.config import Settings


def build_llm_client(settings: Settings) -> LLMClient:
    provider = settings.llm_provider
    client: LLMClient
    if provider == "replay":
        from app.llm.replay import ReplayLLMClient

        return ReplayLLMClient(settings.fixtures_path)
    if provider == "vertex":
        from app.llm.vertex import build_vertex_client

        client = build_vertex_client(settings)
    else:
        from app.llm.gemini_api import build_gemini_api_client

        client = build_gemini_api_client(settings)
    if settings.record_fixtures and settings.data_mode == "live":
        # Recording replay fixtures only makes sense for live sources (replay sources already have outputs).
        from app.llm.recorder import RecordingLLMClient

        client = RecordingLLMClient(client, settings.recordings_path)
    return client
