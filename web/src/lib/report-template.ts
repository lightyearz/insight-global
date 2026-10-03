/**
 * The briefing report template: which sections appear, in which order, with which titles.
 *
 * ReportView renders sections from this list (one renderer per id) and builds the table of contents
 * from it, so later agents (epidemiology, pipeline, cost, ...) add a section here plus a renderer.
 * `required` sections always render (with an empty-state message); optional ones are skipped when empty.
 */
import type { Report } from "./types";

export type ReportSectionId =
  | "summary"
  | "takeaways"
  | "method"
  | "timeline"
  | "options"
  | "excluded"
  | "conflicts"
  | "sources"
  | "audit";

export interface ReportSectionSpec {
  id: ReportSectionId;
  /** Short label for the table of contents. */
  nav: string;
  title: (report: Report) => string;
  required: boolean;
  /** Optional sections render only when this returns true. */
  present?: (report: Report) => boolean;
}

export const REPORT_SECTIONS: readonly ReportSectionSpec[] = [
  { id: "summary", nav: "Summary", title: () => "Executive summary", required: true },
  { id: "takeaways", nav: "Takeaways", title: () => "Key takeaways", required: true },
  {
    id: "method",
    nav: "Method",
    title: () => "Scope & method",
    required: false,
    present: (r) => r.search_strategy !== null,
  },
  { id: "timeline", nav: "Timeline", title: () => "Timeline", required: true },
  {
    id: "options",
    nav: "Options",
    title: (r) => `Treatment options (${r.treatment_options.length} selected)`,
    required: true,
  },
  {
    id: "excluded",
    nav: "Excluded",
    title: (r) => `Considered but excluded (${r.excluded_options.length})`,
    required: false,
    present: (r) => r.excluded_options.length > 0,
  },
  {
    id: "conflicts",
    nav: "Conflicts",
    title: (r) => `Conflict resolution log (${r.conflict_log.length})`,
    required: true,
  },
  { id: "sources", nav: "Sources", title: (r) => `Sources (${r.sources.length})`, required: true },
  { id: "audit", nav: "Audit log", title: () => "Audit log", required: true },
];

export function visibleSections(report: Report): ReportSectionSpec[] {
  return REPORT_SECTIONS.filter((s) => s.required || (s.present?.(report) ?? true));
}
