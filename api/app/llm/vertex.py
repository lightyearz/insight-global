"""Vertex AI (Gemini Enterprise Agent Platform) via Application Default Credentials. No keys."""

from __future__ import annotations

from google import genai

from app.config import Settings
from app.llm.gemini import GeminiLLMClient


def build_vertex_client(settings: Settings) -> GeminiLLMClient:
    client = genai.Client(
        enterprise=True,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location or "global",
    )
    return GeminiLLMClient("vertex", client, settings)
