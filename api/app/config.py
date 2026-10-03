"""Runtime settings (env / ``api/.env``). See docs/CONTRACT.md section 11.

Secrets (``GEMINI_API_KEY``, ``NCBI_API_KEY``) are ``SecretStr`` so they never
appear in reprs or logs. Relative paths are resolved against the ``api/`` folder,
not the current working directory.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.schemas import DataMode, LLMProviderName

API_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = API_DIR.parent


def _resolve(path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else (API_DIR / p).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(API_DIR / ".env"), env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # Mode selection
    llm_provider_setting: Literal["auto", "vertex", "gemini_api", "replay"] = Field(
        default="auto", validation_alias="LLM_PROVIDER"
    )
    data_mode_setting: Literal["auto", "live", "replay"] = Field(default="auto", validation_alias="DATA_MODE")

    # Vertex AI (ADC) / Gemini Developer API
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.8-flash"
    gemini_model_lite: str = "gemini-3.5-flash-lite"
    llm_timeout_s: float = 90
    llm_max_retries: int = 2
    llm_max_concurrency: int = 4
    # Thinking level for main-model steps (gemini-3.8-flash accepts low / medium / high; not minimal).
    gemini_thinking_level: Literal["low", "medium", "high"] = "low"
    # detect_conflicts is the hardest reasoning step; it can be given more thinking separately.
    gemini_thinking_level_conflicts: Literal["low", "medium", "high"] = "low"
    llm_max_output_tokens: int = 16384

    # NCBI / connectors
    ncbi_tool: str = "health-briefing-poc"
    ncbi_email: str = ""
    ncbi_api_key: SecretStr = SecretStr("")
    pubmed_guideline_max: int = 6
    pubmed_review_max: int = 6
    pubmed_years: int = 6
    max_sources: int = 12
    http_timeout_s: float = 20

    # Storage / fixtures
    data_dir: str = "./data"
    fixtures_dir: str = "../fixtures/replay"
    replay_step_delay_ms: int = 400
    # Live runs only: record sources + LLM outputs to DATA_DIR/recordings/<slug>.<briefing id>/ and, after the
    # report is written, promote the folder to FIXTURES_DIR/<slug>/ unless a fixture already exists there.
    record_fixtures: bool = False
    record_overwrite: bool = False

    # Abuse limits (no auth in this POC): concurrent runs and a token bucket on POST /api/briefings.
    max_active_runs: int = 4
    max_active_runs_per_user: int = 2
    create_rate_per_minute: float = 6
    create_burst: int = 3

    cors_origins: str = "http://localhost:3000"

    @model_validator(mode="after")
    def _check_modes(self) -> Settings:
        if self.llm_provider == "replay" and self.data_mode == "live":
            raise ValueError(
                "LLM_PROVIDER=replay cannot be combined with DATA_MODE=live: live sources have no recorded "
                "LLM outputs. Set GOOGLE_CLOUD_PROJECT or GEMINI_API_KEY, or use DATA_MODE=replay."
            )
        if self.llm_provider == "vertex" and not self.google_cloud_project:
            raise ValueError("LLM_PROVIDER=vertex requires GOOGLE_CLOUD_PROJECT")
        if self.llm_provider == "gemini_api" and not self.gemini_api_key.get_secret_value():
            raise ValueError("LLM_PROVIDER=gemini_api requires GEMINI_API_KEY")
        return self

    # ------------------------------------------------------------------ resolved values

    @property
    def llm_provider(self) -> LLMProviderName:
        if self.llm_provider_setting != "auto":
            return self.llm_provider_setting
        if self.google_cloud_project:
            return "vertex"
        if self.gemini_api_key.get_secret_value():
            return "gemini_api"
        return "replay"

    @property
    def data_mode(self) -> DataMode:
        if self.data_mode_setting != "auto":
            return self.data_mode_setting
        return "replay" if self.llm_provider == "replay" else "live"

    @property
    def data_path(self) -> Path:
        return _resolve(self.data_dir)

    @property
    def fixtures_path(self) -> Path:
        return _resolve(self.fixtures_dir)

    @property
    def recordings_path(self) -> Path:
        return self.data_path / "recordings"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def model_names(self) -> tuple[str, str]:
        """(main, lite) model ids as reported in RunInfo/HealthResponse."""
        if self.llm_provider == "replay":
            return ("replay", "replay")
        return (self.gemini_model, self.gemini_model_lite)


@lru_cache
def get_settings() -> Settings:
    return Settings()
