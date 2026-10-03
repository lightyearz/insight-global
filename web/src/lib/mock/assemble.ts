/**
 * Deterministic report assembly for the mock adapter, following
 * docs/CONTRACT.md section 7.4 (the real API does this server side).
 */
import { CONFIDENCE_ORDER, LINE_ORDER, SOURCE_TYPE_LABEL } from "../labels";
import { researchConductedAt } from "../format";
import type { Briefing, Report, Source, TimelineEvent, TimelineKind, TreatmentOption } from "../types";
import { DISCLAIMER } from "../types";

const KIND_ORDER: Partial<Record<TimelineKind, number>> = {
  guideline_published: 0,
  evidence_published: 1,
  treatment_milestone: 2,
};

function slug(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function truncate(s: string, max: number): string {
  return s.length <= max ? s : `${s.slice(0, max - 1).trimEnd()}…`;
}

function citedSourceIds(o: TreatmentOption): Set<string> {
  return new Set([...o.evidence.map((e) => e.source_id), ...o.milestones.map((m) => m.source_id)]);
}

export function orderOptions(options: TreatmentOption[]): TreatmentOption[] {
  return [...options].sort(
    (a, b) =>
      LINE_ORDER.indexOf(a.line_of_therapy) - LINE_ORDER.indexOf(b.line_of_therapy) ||
      CONFIDENCE_ORDER.indexOf(a.confidence) - CONFIDENCE_ORDER.indexOf(b.confidence) ||
      a.name.localeCompare(b.name),
  );
}

export function buildTimeline(
  briefing: Briefing,
  selected: TreatmentOption[],
  reportSources: Source[],
  researchAt: string,
): TimelineEvent[] {
  const events: TimelineEvent[] = [];
  for (const s of reportSources) {
    if (!s.published_at) continue;
    const kind: TimelineKind = s.source_type === "clinical_guideline" ? "guideline_published" : "evidence_published";
    const who = s.issuing_body ?? s.publisher;
    const label = `${who}: ${truncate(s.title, 80)}`;
    const citing = selected.filter((o) => citedSourceIds(o).has(s.id)).map((o) => o.id);
    events.push({
      id: `tl-src-${slug(s.id)}`,
      date: s.published_at,
      date_precision: s.published_at.length >= 10 ? "day" : s.published_at.length >= 7 ? "month" : "year",
      kind,
      label,
      short_label: `${shortName(s)} ${s.published_at.slice(0, 4)}`,
      description: `Tier ${s.reliability_tier} ${SOURCE_TYPE_LABEL[s.source_type].toLowerCase()} published in ${s.publisher}.`,
      source_ids: [s.id],
      treatment_option_ids: citing,
    });
    if (s.updated_at && s.updated_at !== s.published_at) {
      events.push({
        id: `tl-upd-${slug(s.id)}`,
        date: s.updated_at,
        date_precision: s.updated_at.length >= 10 ? "day" : s.updated_at.length >= 7 ? "month" : "year",
        kind,
        label: `${label} (updated)`,
        short_label: `${shortName(s)} upd. ${s.updated_at.slice(0, 4)}`,
        description: `Last updated by ${who}.`,
        source_ids: [s.id],
        treatment_option_ids: citing,
      });
    }
  }
  for (const o of selected) {
    let n = 0;
    for (const m of o.milestones) {
      if (!m.grounded) continue;
      n += 1;
      events.push({
        id: `tl-ms-${o.id.replace(/^opt-/, "")}-${n}`,
        date: m.date,
        date_precision: m.date_precision,
        kind: "treatment_milestone",
        label: `${o.name}: ${m.label}`,
        short_label: truncate(o.name, 22),
        description: `Referenced in: “${m.quote}”`,
        source_ids: [m.source_id],
        treatment_option_ids: [o.id],
      });
    }
  }
  events.sort((a, b) =>
    a.date === b.date ? (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) : a.date < b.date ? -1 : 1,
  );
  const retrieved = briefing.sources.map((s) => s.retrieved_at).sort();
  events.push({
    id: "tl-research",
    date: researchAt.slice(0, 10),
    date_precision: "day",
    kind: "research_conducted",
    label:
      briefing.run.data_mode === "live"
        ? "Research conducted (evidence snapshot)"
        : "Evidence snapshot recorded (replay of an earlier retrieval)",
    short_label: "Research",
    description: `${briefing.sources.length} sources retrieved (${briefing.run.data_mode}) between ${retrieved[0] ?? researchAt} and ${retrieved[retrieved.length - 1] ?? researchAt}`,
    source_ids: [],
    treatment_option_ids: [],
  });
  return events;
}

/** Same rule as the API's timeline.short_name: acronym in parentheses, initials, else a short publisher name. */
function shortName(s: Source): string {
  const who = s.issuing_body ?? "";
  const acronym = /\(([A-Z][A-Za-z]{1,9})\)/.exec(who);
  if (acronym?.[1]) return acronym[1];
  if (who) {
    const initials = (who.match(/[A-Za-z]+/g) ?? []).filter((w) => /^[A-Z]/.test(w)).map((w) => w[0]).join("");
    return who.length <= 16 ? who : initials.length >= 2 && initials.length <= 6 ? initials : truncate(who, 16);
  }
  if (s.connector === "medlineplus") return "MedlinePlus";
  return truncate(s.publisher.replace(/\s*\(.*?\)/g, "").trim() || s.publisher, 16);
}

export interface ReportText {
  title: string;
  top_level_description: string;
  key_takeaways: string[];
}

export function assembleReport(briefing: Briefing, text: ReportText, generatedAt: string, model: string): Report {
  const selected = orderOptions(briefing.treatment_options.filter((o) => o.selected));
  const referenced = new Set<string>();
  selected.forEach((o) => citedSourceIds(o).forEach((id) => referenced.add(id)));
  briefing.conflicts.forEach((c) => c.positions.forEach((p) => referenced.add(p.source_id)));
  const reportSources = briefing.sources
    .filter((s) => referenced.has(s.id))
    .sort(
      (a, b) =>
        a.reliability_tier - b.reliability_tier || (b.published_at ?? "").localeCompare(a.published_at ?? ""),
    );
  const researchAt = researchConductedAt(briefing.sources) ?? generatedAt;
  const reviewer = briefing.reviewed_by ?? briefing.created_by;
  return {
    title: text.title,
    condition: briefing.condition,
    region: briefing.region,
    top_level_description: text.top_level_description,
    key_takeaways: text.key_takeaways,
    treatment_options: selected,
    excluded_options: orderOptions(briefing.treatment_options.filter((o) => !o.selected)).map((o) => ({
      id: o.id,
      name: o.name,
      category: o.category,
      line_of_therapy: o.line_of_therapy,
      recommendation_direction: o.recommendation_direction,
      suggested: o.suggested,
      suggestion_reason: o.suggestion_reason,
      excluded_by: reviewer,
      excluded_at: briefing.reviewed_at ?? generatedAt,
    })),
    timeline: buildTimeline(briefing, selected, reportSources, researchAt),
    conflict_log: briefing.conflicts,
    audit_log: briefing.audit_log,
    sources: reportSources,
    research_conducted_at: researchAt,
    research_started_at: briefing.research_started_at,
    research_completed_at: briefing.research_completed_at,
    search_strategy: briefing.search_strategy,
    reviewed_by: reviewer,
    reviewed_at: briefing.reviewed_at ?? generatedAt,
    generated_at: generatedAt,
    generated_by: reviewer,
    model,
    llm_provider: briefing.run.llm_provider,
    data_mode: briefing.run.data_mode,
    disclaimer: DISCLAIMER,
  };
}
