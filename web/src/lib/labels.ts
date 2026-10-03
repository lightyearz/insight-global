import type {
  AuditAction,
  EvidenceStance,
  NormalisationMethod,
  RecommendationDirection,
  ResolutionRule,
  BriefingStatus,
  Confidence,
  ConflictDecision,
  ConflictType,
  LineOfTherapy,
  NodeName,
  Region,
  SourceType,
  TimelineKind,
  TreatmentCategory,
} from "./types";

export const REGIONS: readonly Region[] = ["US", "UK", "EU", "International"];

export const REGION_LABEL: Record<Region, string> = {
  US: "United States",
  UK: "United Kingdom",
  EU: "European Union",
  International: "International",
};

export const STATUS_LABEL: Record<BriefingStatus, string> = {
  researching: "Researching",
  awaiting_review: "Awaiting review",
  generating_report: "Generating report",
  completed: "Completed",
  failed: "Failed",
};

export const STEP_LABEL: Record<NodeName, string> = {
  normalize_condition: "Normalise condition (MeSH)",
  retrieve_sources: "Retrieve sources",
  extract_treatments: "Extract treatments",
  consolidate_options: "Consolidate options",
  detect_conflicts: "Detect conflicts",
  suggest_relevance: "Suggest relevance",
  human_review: "Human review",
  write_report: "Write report",
};

export const LINE_ORDER: readonly LineOfTherapy[] = ["first_line", "second_line", "add_on", "alternative", "unspecified"];

export const LINE_LABEL: Record<LineOfTherapy, string> = {
  first_line: "First line",
  second_line: "Second line",
  add_on: "Add-on",
  alternative: "Alternative",
  unspecified: "Line not specified",
};

export const CATEGORY_ORDER: readonly TreatmentCategory[] = [
  "pharmacologic",
  "lifestyle",
  "procedural",
  "device",
  "monitoring",
  "other",
];

export const CATEGORY_LABEL: Record<TreatmentCategory, string> = {
  pharmacologic: "Pharmacologic",
  procedural: "Procedural",
  lifestyle: "Lifestyle",
  device: "Device",
  monitoring: "Monitoring",
  other: "Other",
};

export const CONFIDENCE_ORDER: readonly Confidence[] = ["high", "medium", "low"];

export const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

export const CONFLICT_TYPE_LABEL: Record<ConflictType, string> = {
  contradiction: "Contradiction",
  outdated_guidance: "Outdated guidance",
  regional_variation: "Regional variation",
  population_difference: "Population difference",
};

export const DECISION_LABEL: Record<ConflictDecision, string> = {
  accept_source: "Accept one source",
  accept_both_with_context: "Accept both with context",
  exclude_topic: "Exclude topic from report",
  custom: "Custom resolution",
};

/** Decision label that reads correctly for conflicts with more than two positions. */
export function decisionLabel(decision: ConflictDecision, positionCount: number): string {
  if (decision === "accept_both_with_context" && positionCount > 2) return "Keep all positions with context";
  return DECISION_LABEL[decision];
}

export const RULE_LABEL: Record<ResolutionRule, string> = {
  higher_tier: "Rule: higher reliability tier wins",
  more_recent_same_tier: "Rule: same tier, newer source wins",
  region_tiebreak: "Rule: tie broken by briefing region",
  regional_match: "Rule: only source for the briefing region",
  regional_context: "Rule: regional context, keep positions",
  population_context: "Rule: different populations, keep positions",
  tie: "Rule: tie on tier and date, keep positions",
};

export const DIRECTION_ORDER: readonly RecommendationDirection[] = ["for", "conditional", "mixed", "against", "not_stated"];

export const DIRECTION_LABEL: Record<RecommendationDirection, string> = {
  for: "Recommended",
  conditional: "Conditional",
  mixed: "Mixed (for and against)",
  against: "Recommended against",
  not_stated: "No recommendation stated",
};

export const STANCE_LABEL: Record<EvidenceStance, string> = {
  recommended: "Recommends",
  recommended_against: "Recommends against",
  conditional: "Conditional",
  insufficient_evidence: "Insufficient evidence",
  described: "Describes",
};

export const NORMALISATION_LABEL: Record<NormalisationMethod, string> = {
  mesh_exact: "Exact MeSH heading match",
  mesh_entry_term: "MeSH entry term (synonym) resolved by NCBI",
  mesh_partial: "Closest partial MeSH match",
  none: "No MeSH match: searched the typed text in titles and abstracts",
  replay_fixture: "Recorded condition (replay fixture)",
};

export const SOURCE_TYPE_LABEL: Record<SourceType, string> = {
  clinical_guideline: "Clinical guideline",
  systematic_review: "Systematic review",
  consumer_health_summary: "Consumer health summary",
  other: "Other",
};

export const TIMELINE_KIND_LABEL: Record<TimelineKind, string> = {
  guideline_published: "Guideline published",
  evidence_published: "Evidence published",
  treatment_milestone: "Treatment milestone",
  research_conducted: "Research conducted",
};

export const AUDIT_ACTION_LABEL: Record<AuditAction, string> = {
  briefing_created: "Briefing created",
  review_submitted: "Review submitted",
  option_selected: "Option selected",
  option_excluded: "Option excluded",
  conflict_resolved: "Conflict resolved",
  report_generated: "Report generated",
};
