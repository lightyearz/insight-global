"use client";

import type { ReactNode } from "react";
import { AlertTriangle, ExternalLink, Printer } from "lucide-react";
import { formatDateTime, formatPartialDate, keyed } from "@/lib/format";
import {
  AUDIT_ACTION_LABEL,
  CATEGORY_LABEL,
  CONFLICT_TYPE_LABEL,
  DIRECTION_LABEL,
  LINE_LABEL,
  NORMALISATION_LABEL,
  REGION_LABEL,
  RULE_LABEL,
  SOURCE_TYPE_LABEL,
} from "@/lib/labels";
import { visibleSections, type ReportSectionId } from "@/lib/report-template";
import { safeHref } from "@/lib/safe-href";
import type { AuditEntry, Conflict, Report, Source, TreatmentOption } from "@/lib/types";
import { ConfidenceBadge, DirectionBadge, TierBadge, TierLegend } from "./badges";
import { describeDecision, overridesSuggestion, positionLetter } from "./ConflictCard";
import { Timeline } from "./Timeline";
import { Badge, Button, cx } from "./ui";

function citationsOf(o: TreatmentOption): string[] {
  const ids: string[] = [];
  for (const id of [...o.evidence.map((e) => e.source_id), ...o.milestones.map((m) => m.source_id)]) {
    if (!ids.includes(id)) ids.push(id);
  }
  return ids;
}

function Cite({ n }: { n: number | undefined }) {
  if (!n) return null;
  return (
    <a href={`#source-${n}`} className="font-mono text-xs text-accent hover:underline" aria-label={`Source ${n}`}>
      [{n}]
    </a>
  );
}

function ExternalLinkOrText({ url, className, children }: { url: string; className?: string; children: ReactNode }) {
  const href = safeHref(url);
  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
    </a>
  ) : (
    <span className={className}>{children}</span>
  );
}

function Section({ id, title, children, className }: { id: string; title: string; children: ReactNode; className?: string }) {
  return (
    <section aria-labelledby={id} className={cx("scroll-mt-16 border-t border-line pt-5", className)}>
      <h2 id={id} className="mb-3 text-base font-semibold text-ink">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-sm text-ink">{children}</dd>
    </div>
  );
}

/** Notes shown under an option: the conflict decisions that touch it. */
interface OptionNote {
  key: string;
  text: string;
  excluded: boolean;
}

function optionNotes(o: { id: string }, report: Report, sources: ReadonlyMap<string, Source>): OptionNote[] {
  const notes: OptionNote[] = [];
  report.conflict_log.forEach((c, i) => {
    if (!c.treatment_option_ids.includes(o.id) || !c.resolution) return;
    const r = c.resolution;
    if (r.decision === "exclude_topic") {
      notes.push({ key: c.id, excluded: true, text: `Linked to an excluded topic: “${c.topic}” (not discussed in the narrative).` });
    } else {
      notes.push({
        key: c.id,
        excluded: false,
        text: `Conflict ${i + 1} decision: ${describeDecision(c, r.decision, r.accepted_source_id, sources, Infinity)} — ${c.topic}`,
      });
    }
  });
  return notes;
}

function OptionNotes({ notes }: { notes: OptionNote[] }) {
  if (notes.length === 0) return null;
  return (
    <ul className="mt-1 flex flex-col gap-0.5">
      {notes.map((n) => (
        <li key={n.key} className={cx("text-xs font-normal", n.excluded ? "text-warn" : "text-muted")}>
          {n.excluded ? <AlertTriangle aria-hidden="true" className="mr-1 inline size-3 align-[-2px]" /> : "† "}
          {n.text}
        </li>
      ))}
    </ul>
  );
}

function AuditTable({ entries }: { entries: AuditEntry[] }) {
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full text-left text-xs md:min-w-[640px]">
        <thead className="border-b border-line-strong uppercase tracking-wide text-muted">
          <tr>
            <th scope="col" className="py-1.5 pr-3 font-semibold">When</th>
            <th scope="col" className="px-3 py-1.5 font-semibold">Who</th>
            <th scope="col" className="px-3 py-1.5 font-semibold">Action</th>
            <th scope="col" className="py-1.5 pl-3 font-semibold">Detail</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {keyed(entries, (a) => `${a.at}-${a.action}-${a.target_id ?? ""}`).map(([key, a]) => (
            <tr key={key}>
              <td className="py-1.5 pr-3 text-ink-2 md:whitespace-nowrap">{formatDateTime(a.at)}</td>
              <td className="px-3 py-1.5 text-ink-2">{a.actor}</td>
              <td className="px-3 py-1.5 text-ink md:whitespace-nowrap">{AUDIT_ACTION_LABEL[a.action]}</td>
              <td className="py-1.5 pl-3 text-ink-2">{a.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function suggestionText(c: Conflict, sources: ReadonlyMap<string, Source>): string {
  return describeDecision(c, c.suggested_resolution.decision, c.suggested_resolution.accepted_source_id, sources, Infinity);
}

export function ReportView({ report }: { report: Report }) {
  const sources = new Map<string, Source>(report.sources.map((s) => [s.id, s]));
  const citation = new Map<string, number>(report.sources.map((s, i) => [s.id, i + 1]));
  const provider =
    report.llm_provider === "gemini_api" ? "Gemini API" : report.llm_provider === "vertex" ? "Vertex AI" : "Replay";
  const replay = report.data_mode === "replay";
  const sections = visibleSections(report);
  const strategy = report.search_strategy;

  const renderers: Record<ReportSectionId, () => ReactNode> = {
    summary: () => <p className="max-w-4xl text-sm leading-relaxed text-ink-2">{report.top_level_description}</p>,
    takeaways: () => (
      <ul className="flex max-w-4xl list-disc flex-col gap-1.5 pl-5 text-sm text-ink-2 marker:text-muted">
        {keyed(report.key_takeaways, (t) => t).map(([key, t]) => (
          <li key={key}>{t}</li>
        ))}
      </ul>
    ),
    method: () =>
      strategy ? (
        <dl className="grid max-w-5xl gap-x-6 gap-y-2 text-sm sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)]">
          <dt className="text-muted">Condition</dt>
          <dd className="text-ink">
            “{strategy.condition_input}” {"→"} {strategy.normalised_label}
            {strategy.mesh_id ? ` (MeSH ${strategy.mesh_id})` : ""}
            <span className="block text-xs text-muted">{NORMALISATION_LABEL[strategy.normalisation]}</span>
          </dd>
          <dt className="text-muted">Sources searched</dt>
          <dd className="text-ink-2">
            <ul className="list-disc pl-4">
              {strategy.connectors.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </dd>
          <dt className="text-muted">PubMed queries</dt>
          <dd>
            <ul className="flex flex-col gap-1">
              {strategy.pubmed_queries.map((q) => (
                <li key={q} className="break-words rounded bg-subtle px-2 py-1 font-mono text-xs text-ink-2">
                  {q}
                </li>
              ))}
            </ul>
          </dd>
          <dt className="text-muted">Filters</dt>
          <dd className="text-ink-2">
            Publication types: {strategy.publication_types.join(", ")}. Date window: {strategy.date_window}.
          </dd>
          <dt className="text-muted">Sources</dt>
          <dd className="text-ink-2">
            {strategy.sources_found} found {"→"} {strategy.sources_selected} kept after de-duplication (cap{" "}
            {strategy.max_sources}) {"→"} {report.sources.length} cited in this report.
          </dd>
          <dt className="text-muted">Model</dt>
          <dd className="text-ink-2">
            <span className="font-mono text-xs">{report.model}</span> ({provider}); deterministic code checks every
            quote against its source, assigns tiers and computes conflict suggestions.
          </dd>
          <dt className="text-muted">Reliability tiers</dt>
          <dd className="text-ink-2">
            <ul className="list-disc pl-4">
              {strategy.tier_rules.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </dd>
          {strategy.note ? (
            <>
              <dt className="text-muted">Note</dt>
              <dd className="text-ink-2">{strategy.note}</dd>
            </>
          ) : null}
        </dl>
      ) : null,
    timeline: () => (
      <>
        <p className="mb-3 text-xs text-muted">
          When the cited guidelines and evidence were published or updated, treatment milestones they mention, and when
          the evidence was retrieved.
        </p>
        <Timeline events={report.timeline} sources={sources} citation={citation} />
      </>
    ),
    options: () => (
      <>
        {/* Table: md and up, and print. */}
        <div className="relative hidden overflow-x-auto md:block print:block">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead className="border-b border-line-strong text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="w-[34%] py-2 pr-3 font-semibold">Option</th>
                <th scope="col" className="px-3 py-2 font-semibold">Class</th>
                <th scope="col" className="px-3 py-2 font-semibold">Line</th>
                <th scope="col" className="px-3 py-2 font-semibold">Recommendation</th>
                <th scope="col" className="px-3 py-2 font-semibold">Population</th>
                <th scope="col" className="px-3 py-2 font-semibold">Confidence</th>
                <th scope="col" className="py-2 pl-3 font-semibold">Sources</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line align-top">
              {report.treatment_options.map((o) => (
                <tr key={o.id} className="print-break-avoid">
                  <th scope="row" className="py-2.5 pr-3 font-medium text-ink">
                    {o.name}
                    <p className="mt-0.5 text-xs font-normal text-ink-2">{o.summary}</p>
                    <OptionNotes notes={optionNotes(o, report, sources)} />
                  </th>
                  <td className="px-3 py-2.5 text-ink-2">{o.drug_class ?? CATEGORY_LABEL[o.category]}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-ink-2">{LINE_LABEL[o.line_of_therapy]}</td>
                  <td className="px-3 py-2.5">
                    <DirectionBadge direction={o.recommendation_direction} />
                  </td>
                  <td className="px-3 py-2.5 text-ink-2">{o.population}</td>
                  <td className="px-3 py-2.5">
                    <ConfidenceBadge confidence={o.confidence} />
                  </td>
                  <td className="py-2.5 pl-3">
                    <span className="flex flex-wrap gap-1">
                      {citationsOf(o).map((id) => (
                        <Cite key={id} n={citation.get(id)} />
                      ))}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {/* Stacked cards on small screens. */}
        <ul className="flex flex-col gap-3 md:hidden print:hidden" aria-label="Selected treatment options">
          {report.treatment_options.map((o) => (
            <li key={o.id} className="rounded-md border border-line px-3 py-2.5">
              <p className="text-sm font-semibold text-ink">{o.name}</p>
              <div className="mt-1 flex flex-wrap gap-1.5">
                <Badge>{LINE_LABEL[o.line_of_therapy]}</Badge>
                <DirectionBadge direction={o.recommendation_direction} />
                <ConfidenceBadge confidence={o.confidence} />
              </div>
              <p className="mt-1.5 text-xs text-ink-2">{o.summary}</p>
              <dl className="mt-1.5 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-xs">
                <dt className="text-muted">Class</dt>
                <dd className="text-ink-2">{o.drug_class ?? CATEGORY_LABEL[o.category]}</dd>
                <dt className="text-muted">Population</dt>
                <dd className="text-ink-2">{o.population}</dd>
                <dt className="text-muted">Sources</dt>
                <dd className="flex flex-wrap gap-1">
                  {citationsOf(o).map((id) => (
                    <Cite key={id} n={citation.get(id)} />
                  ))}
                </dd>
              </dl>
              <OptionNotes notes={optionNotes(o, report, sources)} />
            </li>
          ))}
        </ul>
      </>
    ),
    excluded: () => (
      <>
        <p className="mb-2 text-xs text-muted">
          Options the agent found that the reviewer left out of this briefing, with the AI{"’"}s suggestion for each.
        </p>
        <ul className="flex flex-col divide-y divide-line">
          {report.excluded_options.map((o) => (
            <li key={o.id} className="flex flex-col gap-1 py-2 text-sm sm:flex-row sm:items-start sm:gap-3">
              <div className="min-w-0 sm:w-64 sm:shrink-0">
                <p className="font-medium text-ink">{o.name}</p>
                <p className="text-xs text-muted">
                  {CATEGORY_LABEL[o.category]} {"·"} {LINE_LABEL[o.line_of_therapy]} {"·"}{" "}
                  {DIRECTION_LABEL[o.recommendation_direction]}
                </p>
              </div>
              <div className="min-w-0 flex-1 text-xs text-ink-2">
                <p>
                  <span className="font-semibold">AI {o.suggested ? "suggested including it" : "suggested leaving it out"}:</span>{" "}
                  {o.suggestion_reason || "No reason given"}
                </p>
                <p className="text-muted">
                  Excluded by {o.excluded_by}, {formatDateTime(o.excluded_at)}
                  {o.suggested ? " (overrode the AI suggestion)" : ""}
                  {optionNotes(o, report, sources).some((n) => n.excluded) ? " · linked to an excluded topic" : ""}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </>
    ),
    conflicts: () =>
      report.conflict_log.length === 0 ? (
        <p className="text-sm text-muted">No conflicts were detected between sources.</p>
      ) : (
        <ol className="flex flex-col gap-3">
          {report.conflict_log.map((c, ci) => {
            const r = c.resolution;
            return (
              <li key={c.id} className="print-break-avoid rounded-md border border-line px-4 py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <p className="text-sm font-semibold text-ink">
                    <span className="text-muted">{ci + 1}. </span>
                    {c.topic}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge tone="warn">{CONFLICT_TYPE_LABEL[c.conflict_type]}</Badge>
                    {r?.decision === "exclude_topic" ? <Badge tone="neutral">Excluded from narrative</Badge> : null}
                  </div>
                </div>
                <ul className="mt-2 flex flex-col gap-1 text-sm text-ink-2">
                  {keyed(c.positions, (p) => p.source_id).map(([key, p]) => (
                    <li key={key} className={cx(r?.accepted_source_id === p.source_id && "font-medium text-ink")}>
                      <span className="font-semibold">{positionLetter(c, p.source_id)}:</span> {p.statement}{" "}
                      <Cite n={citation.get(p.source_id)} />{" "}
                      <span className="text-xs text-muted">
                        (position {p.side}, tier {p.reliability_tier}, {formatPartialDate(p.published_at)})
                      </span>
                    </li>
                  ))}
                </ul>
                <dl className="mt-2 grid gap-x-6 gap-y-1 border-t border-line pt-2 text-sm sm:grid-cols-[auto_minmax(0,1fr)]">
                  <dt className="text-muted">Decision</dt>
                  <dd className="text-ink">
                    {r ? describeDecision(c, r.decision, r.accepted_source_id, sources, Infinity) : "Unresolved"}
                    {r ? (
                      <span className="text-xs text-muted">
                        {" "}
                        {overridesSuggestion(c, r) ? `(suggested: ${suggestionText(c, sources)})` : "(followed the suggestion)"}
                      </span>
                    ) : null}
                  </dd>
                  <dt className="text-muted">Suggestion basis</dt>
                  <dd className="text-xs text-ink-2">
                    {RULE_LABEL[c.suggested_resolution.rule]}. {c.suggested_resolution.rationale}
                  </dd>
                  {r?.note ? (
                    <>
                      <dt className="text-muted">Reviewer note</dt>
                      <dd className="text-ink-2">{r.note}</dd>
                    </>
                  ) : null}
                  <dt className="text-muted">Decided by</dt>
                  <dd className="text-ink-2">{r ? `${r.resolved_by}, ${formatDateTime(r.resolved_at)}` : "-"}</dd>
                </dl>
              </li>
            );
          })}
        </ol>
      ),
    sources: () => (
      <>
        <p className="mb-2 text-xs text-muted">
          Ordered by reliability tier, then newest first. Published = when the source was created; retrieved = when the
          evidence was fetched{replay ? " (recorded earlier; replayed for this briefing)" : " by this research run"}.
        </p>
        <TierLegend className="mb-3" />
        <ol className="flex flex-col divide-y divide-line">
          {report.sources.map((s, i) => (
            <li key={s.id} id={`source-${i + 1}`} className="print-break-avoid flex scroll-mt-16 gap-3 py-3 target:bg-accent-soft">
              <span className="w-8 shrink-0 text-right font-mono text-sm text-muted">[{i + 1}]</span>
              <div className="min-w-0 flex-1">
                <ExternalLinkOrText url={s.url} className="text-sm font-medium text-accent hover:underline">
                  {s.title}
                  <ExternalLink aria-hidden="true" className="ml-1 inline size-3" />
                </ExternalLinkOrText>
                <p className="mt-0.5 text-xs text-ink-2">
                  {s.issuing_body && s.issuing_body !== s.publisher ? `${s.issuing_body} · ` : ""}
                  {s.publisher}
                  {s.authors.length > 0 ? ` · ${s.authors.slice(0, 3).join(", ")}${s.authors.length > 3 ? " et al." : ""}` : ""}
                </p>
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <TierBadge tier={s.reliability_tier} rationale={s.tier_rationale} />
                  <Badge>{SOURCE_TYPE_LABEL[s.source_type]}</Badge>
                  {s.region ? <Badge>{s.region_inferred ? `${s.region} (AI-inferred)` : s.region}</Badge> : null}
                </div>
                <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs sm:grid-cols-4">
                  <div>
                    <dt className="text-muted">Published</dt>
                    <dd className="text-ink">{formatPartialDate(s.published_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Last updated</dt>
                    <dd className="text-ink">{s.updated_at ? formatPartialDate(s.updated_at) : "Not stated"}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Retrieved (researched)</dt>
                    <dd className="text-ink">{formatDateTime(s.retrieved_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Identifiers</dt>
                    <dd className="text-ink">
                      {s.pmid ? (
                        <a href={`https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(s.pmid)}/`} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                          PMID {s.pmid}
                        </a>
                      ) : null}
                      {s.pmid && s.doi ? " · " : null}
                      {s.doi ? (
                        <a href={`https://doi.org/${encodeURIComponent(s.doi).replace(/%2F/g, "/")}`} target="_blank" rel="noopener noreferrer" className="break-all text-accent hover:underline">
                          DOI {s.doi}
                        </a>
                      ) : null}
                      {!s.pmid && !s.doi ? <span className="break-all font-mono">{s.id}</span> : null}
                    </dd>
                  </div>
                </dl>
                <p className="mt-1 text-xs text-muted">Tier rule: {s.tier_rationale.replace(/^Rule:\s*/, "")}</p>
              </div>
            </li>
          ))}
        </ol>
      </>
    ),
    audit: () => (
      <>
        <details className="no-print rounded-md border border-line px-3 py-2">
          <summary className="cursor-pointer text-xs font-semibold text-ink-2">
            Show all {report.audit_log.length} entries (who decided what, and when)
          </summary>
          <div className="mt-2">
            <AuditTable entries={report.audit_log} />
          </div>
        </details>
        <div className="hidden print:block">
          <AuditTable entries={report.audit_log} />
        </div>
      </>
    ),
  };

  return (
    <article aria-labelledby="report-title" className="rounded-lg border border-line bg-surface px-4 py-6 sm:px-8 print:border-0 print:p-0">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted">Standard-of-care briefing</p>
            <h1 id="report-title" className="mt-1 text-2xl font-semibold text-ink">
              {report.title}
            </h1>
          </div>
          <Button onClick={() => window.print()} className="no-print">
            <Printer aria-hidden="true" className="size-4" />
            Print / save as PDF
          </Button>
        </div>

        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-md bg-subtle px-4 py-3 sm:grid-cols-3 lg:grid-cols-4">
          <Meta label="Condition">
            {report.condition.label}
            {report.condition.mesh_id ? <span className="text-muted"> (MeSH {report.condition.mesh_id})</span> : null}
          </Meta>
          <Meta label="Region">{REGION_LABEL[report.region]}</Meta>
          <Meta label="Research run">
            {report.research_started_at ? formatDateTime(report.research_started_at) : "-"}
            {report.research_completed_at ? ` – ${formatDateTime(report.research_completed_at).replace(/^.*?, /, "")}` : ""}
          </Meta>
          <Meta label={replay ? "Evidence snapshot recorded" : "Research conducted (evidence snapshot)"}>
            {formatDateTime(report.research_conducted_at)}
          </Meta>
          <Meta label="Reviewed">
            {report.reviewed_by}, {formatDateTime(report.reviewed_at)}
          </Meta>
          <Meta label="Generated">
            {formatDateTime(report.generated_at)} by {report.generated_by}
          </Meta>
          <Meta label="Model">
            <span className="font-mono text-xs">{report.model}</span> <span className="text-muted">({provider})</span>
          </Meta>
          <Meta label="Sources">
            {report.sources.length} cited {"·"} {replay ? "replay (recorded)" : "live retrieval"}
          </Meta>
        </dl>

        <div role="note" className="print-break-avoid flex gap-2.5 rounded-md border border-warn-line bg-warn-soft px-3 py-2.5 text-sm">
          <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warn" />
          <p className="text-ink-2">
            <strong className="font-semibold text-warn">Not medical advice. </strong>
            {report.disclaimer}
          </p>
        </div>
      </header>

      <nav
        aria-label="Report sections"
        className="no-print sticky top-0 z-10 -mx-4 mt-5 hidden border-b border-line bg-surface/95 px-4 py-2 backdrop-blur sm:-mx-8 sm:px-8 md:block"
      >
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {sections.map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`} className="text-ink-2 hover:text-accent hover:underline">
                {s.nav}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="mt-6 flex flex-col gap-6">
        {sections.map((s) => (
          <Section key={s.id} id={s.id} title={s.title(report)} className={s.id === "timeline" ? "print-break-avoid" : undefined}>
            {renderers[s.id]()}
          </Section>
        ))}
      </div>
    </article>
  );
}
