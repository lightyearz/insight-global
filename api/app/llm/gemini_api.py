"""Gemini Developer API. The key is read from settings at runtime and never logged or returned."""

from __future__ import annotations

from google import genai

from app.config import Settings
from app.llm.gemini import GeminiLLMClient


def build_gemini_api_client(settings: Settings) -> GeminiLLMClient:
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    return GeminiLLMClient("gemini_api", client, settings)
