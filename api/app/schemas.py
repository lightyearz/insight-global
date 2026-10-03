"""Frozen API contract for the Health Briefing POC.

This module is the single source of truth for every object that crosses the
HTTP boundary or is persisted. ``web/src/lib/types.ts`` mirrors it field for
field (snake_case kept). Change both together, and update docs/CONTRACT.md.

Serialisation rules (see docs/CONTRACT.md, "Wire format"):
- Every field is always present in JSON responses. Optional values are ``null``,
  never omitted (do not use ``exclude_none``/``exclude_unset`` on responses).
- Datetimes are timezone-aware UTC and serialise as ISO 8601 (``...Z``).
- Partial dates (``PartialDate``) are strings ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD``.

Not medical advice: this system summarises public literature for strategy work.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTRACT_VERSION = "1.1.0"

DISCLAIMER = (
    "This briefing is an AI-assisted summary of publicly available literature, "
    "prepared for health-system strategy and planning. It is not medical advice, "
    "is not a clinical guideline, and must not be used to make decisions about the "
    "care of any individual patient. Verify all statements against the cited sources."
)

DEFAULT_USER_ID = "admin"

PARTIAL_DATE_PATTERN = r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$"
SOURCE_ID_PATTERN = r"^(pubmed|medlineplus):[A-Za-z0-9._-]+$"
OPTION_ID_PATTERN = r"^opt-[a-z0-9-]+$"
CONFLICT_ID_PATTERN = r"^conf-[a-z0-9-]+$"
TIMELINE_ID_PATTERN = r"^tl-[a-z0-9-]+$"
USER_ID_PATTERN = r"^[a-z0-9_-]{1,64}$"

# Source.url must be https on one of these hosts. The URL is rendered as a link and (MedlinePlus)
# fetched for page dates, so anything else (javascript:, data:, internal hosts) is rejected.
SOURCE_URL_HOSTS: frozenset[str] = frozenset({"pubmed.ncbi.nlm.nih.gov", "medlineplus.gov", "www.nlm.nih.gov"})


def is_allowed_source_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname in SOURCE_URL_HOSTS and not parts.username and parts.port is None

# ---------------------------------------------------------------------------
# Shared scalar types / enums
# ---------------------------------------------------------------------------

PartialDate = Annotated[str, Field(pattern=PARTIAL_DATE_PATTERN)]
SourceId = Annotated[str, Field(pattern=SOURCE_ID_PATTERN)]
OptionId = Annotated[str, Field(pattern=OPTION_ID_PATTERN)]
ConflictId = Annotated[str, Field(pattern=CONFLICT_ID_PATTERN)]
TimelineEventId = Annotated[str, Field(pattern=TIMELINE_ID_PATTERN)]
UserId = Annotated[str, Field(pattern=USER_ID_PATTERN)]

UserRole = Literal["admin", "analyst"]
Region = Literal["US", "UK", "EU", "International"]
Connector = Literal["pubmed", "medlineplus"]
SourceType = Literal["clinical_guideline", "systematic_review", "consumer_health_summary", "other"]
# 1 = most reliable. Assigned deterministically by connectors (docs/CONTRACT.md "Reliability tiers").
ReliabilityTier = Literal[1, 2, 3, 4]
TreatmentCategory = Literal["pharmacologic", "procedural", "lifestyle", "device", "monitoring", "other"]
LineOfTherapy = Literal["first_line", "second_line", "add_on", "alternative", "unspecified"]
Confidence = Literal["high", "medium", "low"]
# What one piece of evidence says about the option (extracted by the LLM, quote-checked).
EvidenceStance = Literal["recommended", "recommended_against", "conditional", "insufficient_evidence", "described"]
# Derived deterministically from the option's evidence stances (app.agent.policy.recommendation_direction).
RecommendationDirection = Literal["for", "against", "conditional", "mixed", "not_stated"]
DatePrecision = Literal["year", "month", "day"]
ConflictType = Literal["contradiction", "outdated_guidance", "regional_variation", "population_difference"]
ConflictDecision = Literal["accept_source", "accept_both_with_context", "exclude_topic", "custom"]
# Which deterministic rule produced the suggested resolution (app.agent.policy.suggest_resolution).
ResolutionRule = Literal[
    "higher_tier",
    "more_recent_same_tier",
    "region_tiebreak",
    "regional_match",
    "regional_context",
    "population_context",
    "tie",
]
NormalisationMethod = Literal["mesh_exact", "mesh_entry_term", "mesh_partial", "none", "replay_fixture"]
TimelineKind = Literal["guideline_published", "evidence_published", "treatment_milestone", "research_conducted"]
BriefingStatus = Literal["researching", "awaiting_review", "generating_report", "completed", "failed"]
StepStatus = Literal["pending", "running", "completed", "failed", "skipped"]
LLMProviderName = Literal["vertex", "gemini_api", "replay"]
DataMode = Literal["live", "replay"]

# LangGraph node names, in execution order. Also the AgentStep.name values.
NodeName = Literal[
    "normalize_condition",
    "retrieve_sources",
    "extract_treatments",
    "consolidate_options",
    "detect_conflicts",
    "suggest_relevance",
    "human_review",
    "write_report",
]
NODE_ORDER: tuple[NodeName, ...] = (
    "normalize_condition",
    "retrieve_sources",
    "extract_treatments",
    "consolidate_options",
    "detect_conflicts",
    "suggest_relevance",
    "human_review",
    "write_report",
)
# JobEvent.step is a node name, or "run" for run-level events.
JobStep = Literal[
    "run",
    "normalize_condition",
    "retrieve_sources",
    "extract_treatments",
    "consolidate_options",
    "detect_conflicts",
    "suggest_relevance",
    "human_review",
    "write_report",
]
JobEventStatus = Literal["started", "progress", "completed", "failed", "awaiting_review"]
AuditAction = Literal[
    "briefing_created",
    "review_submitted",
    "option_selected",
    "option_excluded",
    "conflict_resolved",
    "report_generated",
]
ConditionSuggestionSource = Literal["clinical_tables", "mesh", "replay"]


def date_precision_of(value: str) -> DatePrecision:
    """Precision of a PartialDate string: 'YYYY' -> year, 'YYYY-MM' -> month, else day."""
    if not re.fullmatch(PARTIAL_DATE_PATTERN, value):
        raise ValueError(f"not a partial ISO date: {value!r}")
    return {4: "year", 7: "month"}.get(len(value), "day")  # type: ignore[return-value]


class _Model(BaseModel):
    """Base for all contract models: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class User(_Model):
    id: UserId
    name: str
    email: str
    role: UserRole


# ---------------------------------------------------------------------------
# Condition & sources
# ---------------------------------------------------------------------------


class Condition(_Model):
    input: str = Field(description="Exactly what the user typed.")
    label: str = Field(description="Normalised display label, e.g. the MeSH preferred term.")
    mesh_id: str | None = Field(default=None, description="MeSH descriptor UI, e.g. 'D003924'.")
    synonyms: list[str] = Field(default_factory=list)


class Source(_Model):
    id: SourceId = Field(description="'pubmed:<pmid>' or 'medlineplus:<page slug>'.")
    connector: Connector
    title: str
    publisher: str = Field(description="Journal name (PubMed) or organisation (MedlinePlus).")
    issuing_body: str | None = Field(
        default=None, description="Guideline author organisation if known, e.g. 'American Diabetes Association'."
    )
    authors: list[str] = Field(default_factory=list, description="'Last FM' strings; collective names allowed.")
    url: str = Field(description="https link on an allowlisted NLM host (SOURCE_URL_HOSTS).")
    pmid: str | None = None
    doi: str | None = None
    source_type: SourceType
    reliability_tier: ReliabilityTier
    tier_rationale: str = Field(description="One sentence explaining the tier assignment.")
    region: Region | None = None
    region_inferred: bool = Field(
        default=False, description="True when `region` was inferred by the AI from the source text, not by a connector."
    )
    published_at: PartialDate | None = Field(
        description="When the source was created/published. null only if the publisher exposes no date."
    )
    updated_at: PartialDate | None = Field(default=None, description="Last revised, if the publisher states it.")
    retrieved_at: AwareDatetime = Field(description="When our research fetched this source (UTC).")
    excerpt: str = Field(description="The exact text the agent used (abstract or summary). Quotes must come from here.")

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        if not is_allowed_source_url(value):
            raise ValueError(f"source url must be https on one of {sorted(SOURCE_URL_HOSTS)}")
        return value


# ---------------------------------------------------------------------------
# Treatment options
# ---------------------------------------------------------------------------


class Evidence(_Model):
    source_id: SourceId
    quote: str = Field(description="MUST be a verbatim substring of the source's excerpt (see grounding rule).")
    statement: str = Field(description="Plain-language paraphrase of what the quote supports.")
    recommendation_strength: str | None = Field(default=None, description="As stated, e.g. 'Grade A', 'Class I'.")
    evidence_level: str | None = Field(default=None, description="As stated, e.g. 'Level B', 'high certainty'.")
    stance: EvidenceStance = Field(default="described", description="What this evidence says about the option.")
    grounded: bool = Field(description="True iff the quote passed the deterministic substring check.")


class TreatmentMilestone(_Model):
    """A dated event about a treatment, stated in a source (e.g. 'added as first-line in 2022')."""

    date: PartialDate
    date_precision: DatePrecision
    label: str
    source_id: SourceId
    quote: str
    grounded: bool


class TreatmentOption(_Model):
    id: OptionId = Field(description="'opt-<kebab-slug>', stable within a briefing.")
    name: str
    category: TreatmentCategory
    drug_class: str | None = None
    line_of_therapy: LineOfTherapy
    population: str = Field(description="Who it applies to, e.g. 'Adults with T2D and established ASCVD'.")
    summary: str
    evidence: list[Evidence] = Field(min_length=1)
    milestones: list[TreatmentMilestone] = Field(default_factory=list)
    recommendation_direction: RecommendationDirection = Field(
        default="not_stated", description="Derived from evidence stances: for / against / conditional / mixed."
    )
    confidence: Confidence
    suggested: bool = Field(description="AI pre-suggestion that this option belongs in the report.")
    suggestion_reason: str
    selected: bool = Field(
        description="Human decision. Initialised to `suggested` by suggest_relevance; set by review."
    )


# ---------------------------------------------------------------------------
# Conflicts (human-in-the-loop)
# ---------------------------------------------------------------------------


class ConflictPosition(_Model):
    source_id: SourceId
    side: int = Field(
        default=1, ge=1, le=10, description="Positions with the same side number give the same answer (agree)."
    )
    statement: str
    quote: str
    published_at: PartialDate | None = Field(description="Copied from the Source (effective date for policy).")
    reliability_tier: ReliabilityTier = Field(description="Copied from the Source.")
    grounded: bool = Field(description="Quote passed the substring check against the source excerpt.")


class SuggestedResolution(_Model):
    decision: ConflictDecision
    accepted_source_id: SourceId | None = None
    rule: ResolutionRule = Field(default="tie", description="The deterministic rule that produced this suggestion.")
    rationale: str


class ConflictResolution(_Model):
    decision: ConflictDecision
    accepted_source_id: SourceId | None = None
    note: str = ""
    resolved_by: UserId
    resolved_at: AwareDatetime


class Conflict(_Model):
    id: ConflictId
    topic: str
    conflict_type: ConflictType
    treatment_option_ids: list[OptionId] = Field(default_factory=list)
    positions: list[ConflictPosition] = Field(min_length=2)
    ai_assessment: str
    suggested_resolution: SuggestedResolution
    resolution: ConflictResolution | None = None


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TimelineEvent(_Model):
    id: TimelineEventId
    date: PartialDate
    date_precision: DatePrecision
    kind: TimelineKind
    label: str
    short_label: str = Field(default="", description="<= ~24 chars for chart labels, e.g. 'ACP 2024'.")
    description: str
    source_ids: list[SourceId] = Field(default_factory=list)
    treatment_option_ids: list[OptionId] = Field(default_factory=list)


class AuditEntry(_Model):
    at: AwareDatetime
    actor: UserId = Field(description="User id, or 'system' for automated entries.")
    action: AuditAction
    target_id: str | None = Field(default=None, description="Option id, conflict id, or null.")
    detail: str


class SearchStrategy(_Model):
    """How the research was done ("Scope & method" in the report). Set by retrieve_sources."""

    condition_input: str
    normalised_label: str
    mesh_id: str | None = None
    normalisation: NormalisationMethod
    connectors: list[str] = Field(description="Human-readable list of what was searched.")
    pubmed_queries: list[str] = Field(default_factory=list, description="Exact PubMed search terms.")
    publication_types: list[str] = Field(default_factory=list)
    date_window: str = Field(description="e.g. '2020 to present (publication date)'.")
    max_sources: int
    sources_found: int = Field(description="Before de-duplication and the max_sources cap.")
    sources_selected: int
    tier_rules: list[str]
    data_mode: DataMode
    note: str = ""


class ExcludedOption(_Model):
    """An option the reviewer considered and left out of the report."""

    id: OptionId
    name: str
    category: TreatmentCategory
    line_of_therapy: LineOfTherapy
    recommendation_direction: RecommendationDirection
    suggested: bool
    suggestion_reason: str
    excluded_by: UserId
    excluded_at: AwareDatetime


class Report(_Model):
    title: str
    condition: Condition
    region: Region
    top_level_description: str = Field(description="Executive summary, ~120-200 words.")
    key_takeaways: list[str]
    treatment_options: list[TreatmentOption] = Field(description="Selected options only.")
    excluded_options: list[ExcludedOption] = Field(default_factory=list, description="Considered but left out.")
    timeline: list[TimelineEvent] = Field(description="Sorted ascending by date; research_conducted last.")
    conflict_log: list[Conflict] = Field(description="All conflicts, each with a non-null resolution.")
    audit_log: list[AuditEntry]
    sources: list[Source] = Field(description="Every source referenced anywhere in the report.")
    research_conducted_at: AwareDatetime = Field(description="max(source.retrieved_at): the evidence snapshot time.")
    research_started_at: AwareDatetime | None = Field(default=None, description="When this briefing's run started.")
    research_completed_at: AwareDatetime | None = Field(default=None, description="When research steps finished.")
    search_strategy: SearchStrategy | None = None
    reviewed_by: UserId
    reviewed_at: AwareDatetime
    generated_at: AwareDatetime
    generated_by: UserId = Field(description="The reviewer who triggered generation.")
    model: str = Field(description="Model id used for write_report, or 'replay'.")
    llm_provider: LLMProviderName
    data_mode: DataMode
    disclaimer: str = DISCLAIMER


# ---------------------------------------------------------------------------
# Run telemetry
# ---------------------------------------------------------------------------


class AgentStep(_Model):
    name: NodeName
    status: StepStatus = "pending"
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    detail: str | None = None


class RunInfo(_Model):
    llm_provider: LLMProviderName
    data_mode: DataMode
    model: str
    model_lite: str
    tokens_in: int = 0
    tokens_out: int = Field(default=0, description="Includes thinking tokens (billed as output).")
    est_cost_usd: float = 0.0
    model_versions: list[str] = Field(default_factory=list, description="Model versions reported by the API.")
    steps: list[AgentStep] = Field(description="One entry per NodeName, in NODE_ORDER.")


# ---------------------------------------------------------------------------
# Briefing aggregate
# ---------------------------------------------------------------------------


class Briefing(_Model):
    id: str = Field(description="'brf_' + 12 lowercase hex chars.")
    condition: Condition
    region: Region
    status: BriefingStatus
    created_by: UserId
    created_at: AwareDatetime
    updated_at: AwareDatetime
    research_started_at: AwareDatetime | None = None
    research_completed_at: AwareDatetime | None = None
    reviewed_by: UserId | None = None
    reviewed_at: AwareDatetime | None = None
    sources: list[Source] = Field(default_factory=list)
    search_strategy: SearchStrategy | None = None
    treatment_options: list[TreatmentOption] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    audit_log: list[AuditEntry] = Field(default_factory=list)
    report: Report | None = None
    run: RunInfo
    error: str | None = None


class BriefingSummary(_Model):
    id: str
    condition_label: str
    region: Region
    status: BriefingStatus
    created_by: UserId
    created_at: AwareDatetime
    updated_at: AwareDatetime
    source_count: int
    option_count: int
    selected_option_count: int
    conflict_count: int
    open_conflict_count: int
    has_report: bool
    research_conducted_at: AwareDatetime | None = Field(default=None, description="Evidence snapshot, if any.")
    data_mode: DataMode = "replay"


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class CreateBriefingRequest(_Model):
    condition: str = Field(min_length=2, max_length=200)
    region: Region = "US"


class ConflictResolutionInput(_Model):
    conflict_id: ConflictId
    decision: ConflictDecision
    accepted_source_id: SourceId | None = None
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _check_decision_fields(self) -> ConflictResolutionInput:
        if self.decision == "accept_source" and not self.accepted_source_id:
            raise ValueError("accepted_source_id is required when decision is 'accept_source'")
        if self.decision != "accept_source" and self.accepted_source_id is not None:
            raise ValueError("accepted_source_id is only allowed when decision is 'accept_source'")
        if self.decision == "custom" and not self.note.strip():
            raise ValueError("note is required when decision is 'custom'")
        return self


class ReviewSubmission(_Model):
    selected_option_ids: list[OptionId] = Field(max_length=200)
    conflict_resolutions: list[ConflictResolutionInput] = Field(default_factory=list, max_length=50)


class ReviewDecision(_Model):
    """Internal: the value passed to LangGraph ``Command(resume=...)`` (as a dict).

    Built by the API from a validated ReviewSubmission plus the acting user.
    """

    selected_option_ids: list[OptionId]
    conflict_resolutions: dict[ConflictId, ConflictResolution]
    reviewed_by: UserId
    reviewed_at: AwareDatetime


# ---------------------------------------------------------------------------
# Events, lookups, health
# ---------------------------------------------------------------------------


class JobEvent(_Model):
    briefing_id: str
    seq: int = Field(ge=1, description="Strictly increasing per briefing, starting at 1.")
    ts: AwareDatetime
    step: JobStep
    status: JobEventStatus
    message: str
    data: dict[str, Any] | None = None


class ConditionSuggestion(_Model):
    label: str
    code: str | None = Field(default=None, description="ICD-10-CM code or MeSH UI when available.")
    source: ConditionSuggestionSource


class ReplayManifest(_Model):
    """fixtures/replay/<slug>/manifest.json; also returned by GET /api/replay/conditions."""

    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    label: str
    aliases: list[str] = Field(default_factory=list)
    recorded_at: AwareDatetime
    recorded_with: str = Field(description="'hand-authored' or the model id used to record.")
    notes: str = ""


class HealthResponse(_Model):
    status: Literal["ok"] = "ok"
    contract_version: str = CONTRACT_VERSION
    llm_provider: LLMProviderName
    data_mode: DataMode
    model: str
    model_lite: str
    time: AwareDatetime


class ErrorResponse(_Model):
    """Non-422 errors. 422 uses FastAPI's default list-shaped ``detail``."""

    detail: str
