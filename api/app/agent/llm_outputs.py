"""Frozen contract for LLM structured outputs and the LLM client interface.

Each ``*Output`` model below is BOTH:
  1. the ``response_json_schema`` sent to Gemini (via :func:`gemini_json_schema`), and
  2. the exact JSON shape of the matching replay fixture file
     (``fixtures/replay/<slug>/llm/<step>.json`` or
     ``fixtures/replay/<slug>/llm/extract_treatments/<source_id_to_filename(id)>.json``).

Design rules for these models (Gemini JSON-Schema subset, google-genai 2.28):
  - no defaults, no ``pattern``/``minLength``/``const``: every field is required,
    optional values are expressed as ``X | None`` (anyOf with null);
  - enums are ``Literal`` strings; list sizes use ``min_length``/``max_length`` (minItems/maxItems).
Values the model cannot be trusted with (ids of sources, dates, tiers, grounding,
suggested resolutions) are filled in deterministically by the agent code, never by the LLM.
Two extracted values are hints only: ``issuing_body`` is kept only if the name appears in the source
text, and ``region`` is stored with ``Source.region_inferred = True`` (see extract_treatments).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import (
    Confidence,
    ConflictType,
    DatePrecision,
    EvidenceStance,
    LineOfTherapy,
    LLMProviderName,
    Region,
    TreatmentCategory,
)

# Steps that call the LLM. These are also the replay fixture keys.
LLMStep = Literal[
    "extract_treatments",
    "consolidate_options",
    "detect_conflicts",
    "suggest_relevance",
    "write_report",
]
ModelTier = Literal["main", "lite"]

# Which configured model each step uses: "main" = GEMINI_MODEL, "lite" = GEMINI_MODEL_LITE.
MODEL_TIER_BY_STEP: dict[LLMStep, ModelTier] = {
    "extract_treatments": "lite",
    "consolidate_options": "main",
    "detect_conflicts": "main",
    "suggest_relevance": "lite",
    "write_report": "main",
}


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# extract_treatments — one call per Source (item_key = source.id)
# ---------------------------------------------------------------------------


class ExtractedEvidence(_Out):
    quote: str = Field(description="Verbatim span copied character-for-character from the source text. 1-3 sentences.")
    statement: str = Field(description="Plain-language paraphrase of what the quote says about the treatment.")
    recommendation_strength: str | None = Field(description="Recommendation strength exactly as stated, else null.")
    evidence_level: str | None = Field(description="Evidence level/certainty exactly as stated, else null.")
    stance: EvidenceStance = Field(
        description="What the quote says about this treatment: recommended, recommended_against, conditional "
        "(weak/conditional or only for a subgroup), insufficient_evidence, or described (no recommendation)."
    )


class ExtractedMilestone(_Out):
    date: str = Field(description="'YYYY', 'YYYY-MM' or 'YYYY-MM-DD', only if the text states it.")
    date_precision: DatePrecision
    label: str = Field(description="Short label, e.g. 'Recommended as first-line therapy'.")
    quote: str = Field(description="Verbatim span from the source text that states the date/event.")


class ExtractedTreatment(_Out):
    name: str = Field(description="Generic/common name, e.g. 'Metformin', 'SGLT2 inhibitors', 'Bariatric surgery'.")
    category: TreatmentCategory
    drug_class: str | None
    line_of_therapy: LineOfTherapy
    population: str = Field(description="Who it applies to, as stated in the source.")
    summary: str = Field(description="1-2 sentences on the role of this treatment according to this source.")
    evidence: list[ExtractedEvidence] = Field(min_length=1, max_length=4)
    milestones: list[ExtractedMilestone] = Field(max_length=3)


class ExtractTreatmentsOutput(_Out):
    is_relevant: bool = Field(description="False if the source does not discuss treatment of the condition.")
    issuing_body: str | None = Field(description="Organisation that issued the guideline, if stated in the text.")
    region: Region | None = Field(description="Jurisdiction the guidance targets, if clear from the text.")
    treatments: list[ExtractedTreatment] = Field(max_length=12)
    notes: str | None


# ---------------------------------------------------------------------------
# consolidate_options — one call per briefing
# Input: every ExtractedTreatment, addressed by ref "<source_id>#<index>"
# (index = position in that source's ExtractTreatmentsOutput.treatments).
# ---------------------------------------------------------------------------


class ConsolidatedOption(_Out):
    id: str = Field(description="'opt-' + lowercase kebab slug of the name, e.g. 'opt-metformin'. Unique.")
    name: str
    category: TreatmentCategory
    drug_class: str | None
    line_of_therapy: LineOfTherapy
    population: str
    summary: str = Field(description="2-3 sentences synthesising all merged refs.")
    member_refs: list[str] = Field(min_length=1, description="Refs '<source_id>#<index>' merged into this option.")
    confidence: Confidence = Field(description="Proposed; the agent may only lower it (grounding/tier caps).")


class ConsolidateOptionsOutput(_Out):
    options: list[ConsolidatedOption] = Field(max_length=25)


# ---------------------------------------------------------------------------
# detect_conflicts — one call per briefing
# ---------------------------------------------------------------------------


class DetectedConflictPosition(_Out):
    source_id: str = Field(description="Must be one of the provided source ids.")
    side: int = Field(
        description="1-based answer number: sources giving the SAME answer share a side; each conflict has >= 2 sides."
    )
    statement: str
    quote: str = Field(description="Verbatim span from that source's text.")


class DetectedConflict(_Out):
    id: str = Field(description="'conf-' + lowercase kebab slug of the topic, unique.")
    topic: str = Field(description="Short question-style topic, e.g. 'First-line agent for patients with ASCVD'.")
    conflict_type: ConflictType
    treatment_option_ids: list[str] = Field(description="Ids of affected consolidated options.")
    positions: list[DetectedConflictPosition] = Field(min_length=2, max_length=4)
    ai_assessment: str = Field(description="2-4 sentences: why they differ (date, population, region, method).")


class DetectConflictsOutput(_Out):
    conflicts: list[DetectedConflict] = Field(max_length=10)


# ---------------------------------------------------------------------------
# suggest_relevance — one call per briefing
# ---------------------------------------------------------------------------


class RelevanceSuggestion(_Out):
    option_id: str
    suggested: bool
    reason: str = Field(description="One sentence aimed at a health-system strategy reader.")


class SuggestRelevanceOutput(_Out):
    suggestions: list[RelevanceSuggestion]


# ---------------------------------------------------------------------------
# write_report — one call per briefing, ONLY selected options + resolved conflicts
# ---------------------------------------------------------------------------


class WriteReportOutput(_Out):
    title: str = Field(description="e.g. 'Standard of care: Type 2 diabetes mellitus (US)'.")
    top_level_description: str = Field(description="Executive summary, 120-200 words, no advice to individuals.")
    key_takeaways: list[str] = Field(min_length=3, max_length=6)


LLM_OUTPUT_MODELS: dict[LLMStep, type[BaseModel]] = {
    "extract_treatments": ExtractTreatmentsOutput,
    "consolidate_options": ConsolidateOptionsOutput,
    "detect_conflicts": DetectConflictsOutput,
    "suggest_relevance": SuggestRelevanceOutput,
    "write_report": WriteReportOutput,
}

# ---------------------------------------------------------------------------
# LLM client interface (implemented by app/llm/{vertex,gemini_api,replay}.py)
# ---------------------------------------------------------------------------

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMRequest:
    step: LLMStep
    system: str
    prompt: str
    item_key: str | None = None
    """extract_treatments: the Source.id. All other steps: None."""
    fixture_slug: str | None = None
    """Replay fixture folder for this briefing (set when DATA_MODE=replay)."""


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    parsed: T
    model: str
    """Model id actually used, or 'replay'."""
    tokens_in: int = 0
    tokens_out: int = 0
    """Candidates + thinking tokens."""
    model_version: str | None = None
    """Exact model version reported by the API (provenance), if any."""


class LLMClient(Protocol):
    provider: LLMProviderName

    async def generate(self, request: LLMRequest, output_model: type[T]) -> LLMResult[T]:
        """Return ``output_model`` parsed from structured output.

        Gemini providers: ``client.aio.models.generate_content(model=..., contents=prompt,
        config=GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
        response_json_schema=gemini_json_schema(output_model), ...))`` then
        ``output_model.model_validate_json(response.text)``.
        Replay provider: load the fixture file for (fixture_slug, step, item_key) and validate it.
        Raise :class:`LLMError` on failure (after retries).
        """
        ...


class LLMError(RuntimeError):
    """LLM call failed. Carries the usage of the failed attempts so cost accounting stays complete."""

    def __init__(self, message: str, *, model: str = "", tokens_in: int = 0, tokens_out: int = 0) -> None:
        super().__init__(message)
        self.model = model
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out


class ReplayFixtureMissing(LLMError):
    pass


# ---------------------------------------------------------------------------
# Contract helpers (deterministic, shared by agent, replay provider and tests)
# ---------------------------------------------------------------------------

_UNSUPPORTED_SCHEMA_KEYS = {"default", "pattern", "minLength", "maxLength", "examples", "const"}


def gemini_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON Schema reduced to the subset Gemini accepts.

    Drops unsupported keywords and any non-``$`` sibling of ``$ref``.
    """

    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return {k: v for k, v in node.items() if k.startswith("$")}
            return {k: clean(v) for k, v in node.items() if k not in _UNSUPPORTED_SCHEMA_KEYS}
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    return clean(model.model_json_schema())


def source_id_to_filename(source_id: str) -> str:
    """'pubmed:38078589' -> 'pubmed_38078589'. Used for replay fixture file names (add '.json')."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", source_id)


_QUOTE_TRANSLATION = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "′": "'",
        "“": '"', "”": '"', "„": '"', "″": '"',
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
        " ": " ", " ": " ", " ": " ",
    }
)


def normalize_for_grounding(text: str) -> str:
    """NFKC, drop format characters (soft hyphen, zero-width space), unify quotes/dashes/spaces and >=/<=,
    collapse whitespace, strip. Case is preserved."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Cf").translate(_QUOTE_TRANSLATION)
    text = text.replace("≥", ">=").replace("≤", "<=")
    return re.sub(r"\s+", " ", text).strip()


MIN_QUOTE_WORDS = 5
MIN_QUOTE_CHARS = 30


def is_grounded(quote: str, excerpt: str) -> bool:
    """THE grounding rule: the normalised quote is a substring of the normalised excerpt and is substantive
    (at least MIN_QUOTE_WORDS words or MIN_QUOTE_CHARS characters, so "Metformin is" never passes).

    Grounding proves where a quote came from. It does NOT prove that the paraphrased ``statement`` is
    supported by the quote (that would need an entailment check; see docs/DECISIONS.md).
    """
    q = normalize_for_grounding(quote)
    if len(q.split()) < MIN_QUOTE_WORDS and len(q) < MIN_QUOTE_CHARS:
        return False
    return q in normalize_for_grounding(excerpt)
