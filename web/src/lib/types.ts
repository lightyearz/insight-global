/**
 * Frozen API contract — exact TypeScript mirror of api/app/schemas.py.
 *
 * Wire rules (docs/CONTRACT.md):
 * - Response objects always contain every field; optional values are `null` (never omitted).
 * - Datetimes (`IsoDateTime`) are ISO 8601 UTC strings, e.g. "2026-10-03T15:17:59.192907Z".
 * - `PartialDate` is "YYYY", "YYYY-MM" or "YYYY-MM-DD".
 * - Field names are snake_case, exactly as in Python.
 * Change this file only together with schemas.py and docs/CONTRACT.md.
 */

export const CONTRACT_VERSION = "1.1.0";

export const DISCLAIMER =
  "This briefing is an AI-assisted summary of publicly available literature, " +
  "prepared for health-system strategy and planning. It is not medical advice, " +
  "is not a clinical guideline, and must not be used to make decisions about the " +
  "care of any individual patient. Verify all statements against the cited sources.";

export const DEFAULT_USER_ID = "admin";

// ---------------------------------------------------------------------------
// Scalars / enums
// ---------------------------------------------------------------------------

/** ISO 8601 datetime string in UTC. */
export type IsoDateTime = string;
/** "YYYY" | "YYYY-MM" | "YYYY-MM-DD". */
export type PartialDate = string;
/** "pubmed:<pmid>" | "medlineplus:<page slug>". */
export type SourceId = string;
/** "opt-<kebab-slug>". */
export type OptionId = string;
/** "conf-<kebab-slug>". */
export type ConflictId = string;

export type UserRole = "admin" | "analyst";
export type Region = "US" | "UK" | "EU" | "International";
export type Connector = "pubmed" | "medlineplus";
export type SourceType = "clinical_guideline" | "systematic_review" | "consumer_health_summary" | "other";
/** 1 = most reliable. */
export type ReliabilityTier = 1 | 2 | 3 | 4;
export type TreatmentCategory = "pharmacologic" | "procedural" | "lifestyle" | "device" | "monitoring" | "other";
export type LineOfTherapy = "first_line" | "second_line" | "add_on" | "alternative" | "unspecified";
export type Confidence = "high" | "medium" | "low";
/** What one piece of evidence says about the option (LLM-extracted, quote-checked). */
export type EvidenceStance = "recommended" | "recommended_against" | "conditional" | "insufficient_evidence" | "described";
/** Derived deterministically from the option's evidence stances. */
export type RecommendationDirection = "for" | "against" | "conditional" | "mixed" | "not_stated";
export type DatePrecision = "year" | "month" | "day";
export type ConflictType = "contradiction" | "outdated_guidance" | "regional_variation" | "population_difference";
export type ConflictDecision = "accept_source" | "accept_both_with_context" | "exclude_topic" | "custom";
/** The deterministic rule behind a suggested resolution. */
export type ResolutionRule =
  | "higher_tier"
  | "more_recent_same_tier"
  | "region_tiebreak"
  | "regional_match"
  | "regional_context"
  | "population_context"
  | "tie";
export type NormalisationMethod = "mesh_exact" | "mesh_entry_term" | "mesh_partial" | "none" | "replay_fixture";
export type TimelineKind = "guideline_published" | "evidence_published" | "treatment_milestone" | "research_conducted";
export type BriefingStatus = "researching" | "awaiting_review" | "generating_report" | "completed" | "failed";
export type StepStatus = "pending" | "running" | "completed" | "failed" | "skipped";
export type LLMProviderName = "vertex" | "gemini_api" | "replay";
export type DataMode = "live" | "replay";

export type NodeName =
  | "normalize_condition"
  | "retrieve_sources"
  | "extract_treatments"
  | "consolidate_options"
  | "detect_conflicts"
  | "suggest_relevance"
  | "human_review"
  | "write_report";

export const NODE_ORDER: readonly NodeName[] = [
  "normalize_condition",
  "retrieve_sources",
  "extract_treatments",
  "consolidate_options",
  "detect_conflicts",
  "suggest_relevance",
  "human_review",
  "write_report",
] as const;

export type JobStep = "run" | NodeName;
export type JobEventStatus = "started" | "progress" | "completed" | "failed" | "awaiting_review";
export type AuditAction =
  | "briefing_created"
  | "review_submitted"
  | "option_selected"
  | "option_excluded"
  | "conflict_resolved"
  | "report_generated";
export type ConditionSuggestionSource = "clinical_tables" | "mesh" | "replay";

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
}

// ---------------------------------------------------------------------------
// Condition & sources
// ---------------------------------------------------------------------------

export interface Condition {
  input: string;
  label: string;
  mesh_id: string | null;
  synonyms: string[];
}

export interface Source {
  id: SourceId;
  connector: Connector;
  title: string;
  publisher: string;
  issuing_body: string | null;
  authors: string[];
  url: string;
  pmid: string | null;
  doi: string | null;
  source_type: SourceType;
  reliability_tier: ReliabilityTier;
  tier_rationale: string;
  region: Region | null;
  /** True when `region` was inferred by the AI from the source text. */
  region_inferred: boolean;
  /** When the source was created/published; null only if the publisher exposes no date. */
  published_at: PartialDate | null;
  /** Last revised, if stated. */
  updated_at: PartialDate | null;
  /** When our research fetched it. */
  retrieved_at: IsoDateTime;
  excerpt: string;
}

// ---------------------------------------------------------------------------
// Treatment options
// ---------------------------------------------------------------------------

export interface Evidence {
  source_id: SourceId;
  /** Verbatim substring of the source excerpt (when grounded). */
  quote: string;
  statement: string;
  recommendation_strength: string | null;
  evidence_level: string | null;
  stance: EvidenceStance;
  grounded: boolean;
}

export interface TreatmentMilestone {
  date: PartialDate;
  date_precision: DatePrecision;
  label: string;
  source_id: SourceId;
  quote: string;
  grounded: boolean;
}

export interface TreatmentOption {
  id: OptionId;
  name: string;
  category: TreatmentCategory;
  drug_class: string | null;
  line_of_therapy: LineOfTherapy;
  population: string;
  summary: string;
  evidence: Evidence[];
  milestones: TreatmentMilestone[];
  recommendation_direction: RecommendationDirection;
  confidence: Confidence;
  suggested: boolean;
  suggestion_reason: string;
  /** Initialised to `suggested`; the human decision after review. */
  selected: boolean;
}

// ---------------------------------------------------------------------------
// Conflicts
// ---------------------------------------------------------------------------

export interface ConflictPosition {
  source_id: SourceId;
  /** Positions with the same side give the same answer. */
  side: number;
  statement: string;
  quote: string;
  published_at: PartialDate | null;
  reliability_tier: ReliabilityTier;
  grounded: boolean;
}

export interface SuggestedResolution {
  decision: ConflictDecision;
  accepted_source_id: SourceId | null;
  rule: ResolutionRule;
  rationale: string;
}

export interface ConflictResolution {
  decision: ConflictDecision;
  accepted_source_id: SourceId | null;
  note: string;
  resolved_by: string;
  resolved_at: IsoDateTime;
}

export interface Conflict {
  id: ConflictId;
  topic: string;
  conflict_type: ConflictType;
  treatment_option_ids: OptionId[];
  /** At least 2. */
  positions: ConflictPosition[];
  ai_assessment: string;
  suggested_resolution: SuggestedResolution;
  resolution: ConflictResolution | null;
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

export interface TimelineEvent {
  id: string;
  date: PartialDate;
  date_precision: DatePrecision;
  kind: TimelineKind;
  label: string;
  /** Compact chart label, e.g. "ACP 2024". */
  short_label: string;
  description: string;
  source_ids: SourceId[];
  treatment_option_ids: OptionId[];
}

export interface AuditEntry {
  at: IsoDateTime;
  /** User id, or "system". */
  actor: string;
  action: AuditAction;
  target_id: string | null;
  detail: string;
}

export interface SearchStrategy {
  condition_input: string;
  normalised_label: string;
  mesh_id: string | null;
  normalisation: NormalisationMethod;
  connectors: string[];
  pubmed_queries: string[];
  publication_types: string[];
  date_window: string;
  max_sources: number;
  sources_found: number;
  sources_selected: number;
  tier_rules: string[];
  data_mode: DataMode;
  note: string;
}

export interface ExcludedOption {
  id: OptionId;
  name: string;
  category: TreatmentCategory;
  line_of_therapy: LineOfTherapy;
  recommendation_direction: RecommendationDirection;
  suggested: boolean;
  suggestion_reason: string;
  excluded_by: string;
  excluded_at: IsoDateTime;
}

export interface Report {
  title: string;
  condition: Condition;
  region: Region;
  top_level_description: string;
  key_takeaways: string[];
  /** Selected options only. */
  treatment_options: TreatmentOption[];
  /** Considered but left out by the reviewer. */
  excluded_options: ExcludedOption[];
  /** Ascending by date; research_conducted last. */
  timeline: TimelineEvent[];
  /** Every conflict, each with a non-null resolution. */
  conflict_log: Conflict[];
  audit_log: AuditEntry[];
  /** Every source referenced anywhere in the report. */
  sources: Source[];
  research_conducted_at: IsoDateTime;
  research_started_at: IsoDateTime | null;
  research_completed_at: IsoDateTime | null;
  search_strategy: SearchStrategy | null;
  reviewed_by: string;
  reviewed_at: IsoDateTime;
  generated_at: IsoDateTime;
  generated_by: string;
  model: string;
  llm_provider: LLMProviderName;
  data_mode: DataMode;
  disclaimer: string;
}

// ---------------------------------------------------------------------------
// Run telemetry
// ---------------------------------------------------------------------------

export interface AgentStep {
  name: NodeName;
  status: StepStatus;
  started_at: IsoDateTime | null;
  ended_at: IsoDateTime | null;
  detail: string | null;
}

export interface RunInfo {
  llm_provider: LLMProviderName;
  data_mode: DataMode;
  model: string;
  model_lite: string;
  tokens_in: number;
  tokens_out: number;
  est_cost_usd: number;
  model_versions: string[];
  /** One per NodeName, in NODE_ORDER. */
  steps: AgentStep[];
}

// ---------------------------------------------------------------------------
// Briefing aggregate
// ---------------------------------------------------------------------------

export interface Briefing {
  id: string;
  condition: Condition;
  region: Region;
  status: BriefingStatus;
  created_by: string;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  research_started_at: IsoDateTime | null;
  research_completed_at: IsoDateTime | null;
  reviewed_by: string | null;
  reviewed_at: IsoDateTime | null;
  sources: Source[];
  search_strategy: SearchStrategy | null;
  treatment_options: TreatmentOption[];
  conflicts: Conflict[];
  audit_log: AuditEntry[];
  report: Report | null;
  run: RunInfo;
  error: string | null;
}

export interface BriefingSummary {
  id: string;
  condition_label: string;
  region: Region;
  status: BriefingStatus;
  created_by: string;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  source_count: number;
  option_count: number;
  selected_option_count: number;
  conflict_count: number;
  open_conflict_count: number;
  has_report: boolean;
  research_conducted_at: IsoDateTime | null;
  data_mode: DataMode;
}

// ---------------------------------------------------------------------------
// Requests (fields with server defaults are optional here)
// ---------------------------------------------------------------------------

export interface CreateBriefingRequest {
  condition: string;
  /** Default "US". */
  region?: Region;
}

export interface ConflictResolutionInput {
  conflict_id: ConflictId;
  decision: ConflictDecision;
  /** Required iff decision === "accept_source"; must be one of the conflict's position source_ids. */
  accepted_source_id?: SourceId | null;
  /** Required (non-blank) for "custom" and whenever the decision differs from the AI suggestion. Max 2000 chars. */
  note?: string;
}

export interface ReviewSubmission {
  /** At least one, at most 200. */
  selected_option_ids: OptionId[];
  /** Exactly one entry per conflict in the briefing. */
  conflict_resolutions: ConflictResolutionInput[];
}

// ---------------------------------------------------------------------------
// Events, lookups, health, errors
// ---------------------------------------------------------------------------

export interface JobEvent {
  briefing_id: string;
  seq: number;
  ts: IsoDateTime;
  step: JobStep;
  status: JobEventStatus;
  message: string;
  data: Record<string, unknown> | null;
}

export interface ConditionSuggestion {
  label: string;
  code: string | null;
  source: ConditionSuggestionSource;
}

export interface ReplayManifest {
  slug: string;
  label: string;
  aliases: string[];
  recorded_at: IsoDateTime;
  recorded_with: string;
  notes: string;
}

export interface HealthResponse {
  status: "ok";
  contract_version: string;
  llm_provider: LLMProviderName;
  data_mode: DataMode;
  model: string;
  model_lite: string;
  time: IsoDateTime;
}

export interface ValidationErrorItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/** 422 responses carry ValidationErrorItem[]; all other errors carry a string. */
export interface ApiError {
  detail: string | ValidationErrorItem[];
}
