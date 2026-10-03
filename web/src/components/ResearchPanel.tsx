import { CheckCircle2, Circle, Loader2, MinusCircle, PauseCircle, XCircle } from "lucide-react";
import { formatDateTime, formatDuration, formatPartialDate, formatTokens, formatUsd, researchConductedAt } from "@/lib/format";
import { STEP_LABEL } from "@/lib/labels";
import type { AgentStep, Briefing, JobEvent, NodeName } from "@/lib/types";
import { safeHref } from "@/lib/safe-href";
import { TierBadge, TierLegend } from "./badges";
import { Callout, Card, SectionHeading, cx } from "./ui";

function StepIcon({ step }: { step: AgentStep }) {
  const cls = "size-5 shrink-0";
  if (step.name === "human_review" && step.status === "running") {
    return <PauseCircle aria-hidden="true" className={cx(cls, "text-warn")} />;
  }
  switch (step.status) {
    case "completed":
      return <CheckCircle2 aria-hidden="true" className={cx(cls, "text-ok")} />;
    case "running":
      return <Loader2 aria-hidden="true" className={cx(cls, "animate-spin text-accent")} />;
    case "failed":
      return <XCircle aria-hidden="true" className={cx(cls, "text-danger")} />;
    case "skipped":
      return <MinusCircle aria-hidden="true" className={cx(cls, "text-muted")} />;
    default:
      return <Circle aria-hidden="true" className={cx(cls, "text-line-strong")} />;
  }
}

const STATUS_TEXT: Record<AgentStep["status"], string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  skipped: "Skipped",
};

function progressFor(name: NodeName, events: JobEvent[]): string | null {
  const progress = events.filter((e) => e.step === name && e.status === "progress");
  if (progress.length === 0) return null;
  if (name === "retrieve_sources") {
    return progress
      .map((e) => {
        const d = e.data ?? {};
        return typeof d.connector === "string" && typeof d.count === "number" ? `${d.connector}: ${d.count}` : e.message;
      })
      .join(" · ");
  }
  if (name === "extract_treatments") return `${progress.length} sources processed`;
  return progress[progress.length - 1]?.message ?? null;
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums text-ink">{value}</dd>
    </div>
  );
}

export function ResearchPanel({ briefing, events }: { briefing: Briefing; events: JobEvent[] }) {
  const { run } = briefing;
  const latest = events[events.length - 1];
  const snapshot = researchConductedAt(briefing.sources);
  const suggested = briefing.treatment_options.filter((o) => o.suggested).length;
  const provider = run.llm_provider === "gemini_api" ? "Gemini API" : run.llm_provider === "vertex" ? "Vertex AI" : "Replay";

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex flex-col gap-5">
        {briefing.status === "failed" && briefing.error ? (
          <Callout tone="danger" role="alert" title="The research run failed">
            {briefing.error}
          </Callout>
        ) : null}

        <Card className="p-4">
          <SectionHeading>Agent steps</SectionHeading>
          <p aria-live="polite" className="sr-only">
            {latest ? `${STEP_LABEL[latest.step as NodeName] ?? "Run"}: ${latest.message}` : ""}
          </p>
          <ol className="flex flex-col">
            {run.steps.map((step, i) => {
              const duration = formatDuration(step.started_at, step.ended_at);
              const progress = step.status === "running" ? progressFor(step.name, events) : null;
              return (
                <li key={step.name} className="relative flex gap-3 pb-4 last:pb-0">
                  {i < run.steps.length - 1 ? (
                    <span aria-hidden="true" className="absolute left-[9px] top-6 h-[calc(100%-1.25rem)] w-px bg-line" />
                  ) : null}
                  <StepIcon step={step} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                      <p className="text-sm font-medium text-ink">
                        {STEP_LABEL[step.name]}
                        <span className="sr-only"> ({STATUS_TEXT[step.status]})</span>
                      </p>
                      <p className="text-xs tabular-nums text-muted">
                        {duration ??
                          (step.status === "running"
                            ? step.name === "human_review"
                              ? "waiting for you"
                              : "running…"
                            : STATUS_TEXT[step.status].toLowerCase())}
                      </p>
                    </div>
                    {step.detail || progress ? (
                      <p className="text-xs text-ink-2">{progress ?? step.detail}</p>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
        </Card>

        {briefing.sources.length > 0 ? (
          <Card className="p-4">
            <SectionHeading aside={<span className="text-xs text-muted">Retrieved = when the evidence was fetched</span>}>
              Retrieved sources ({briefing.sources.length})
            </SectionHeading>
            <TierLegend className="mb-2" />
            <ul className="divide-y divide-line">
              {briefing.sources.map((s) => (
                <li key={s.id} className="flex flex-col gap-1 py-2 sm:flex-row sm:items-start sm:gap-3">
                  <TierBadge tier={s.reliability_tier} rationale={s.tier_rationale} compact />
                  <div className="min-w-0 flex-1">
                    {safeHref(s.url) ? (
                      <a href={safeHref(s.url)} target="_blank" rel="noopener noreferrer" className="text-sm text-accent hover:underline">
                        {s.title}
                      </a>
                    ) : (
                      <span className="text-sm text-ink">{s.title}</span>
                    )}
                    <p className="text-xs text-muted">
                      {s.issuing_body ?? s.publisher} {"·"} published {formatPartialDate(s.published_at)}
                      {s.updated_at ? ` · updated ${formatPartialDate(s.updated_at)}` : ""} {"·"} retrieved{" "}
                      {formatDateTime(s.retrieved_at)}
                    </p>
                    <p className="text-xs text-muted">{s.tier_rationale}</p>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}

        {events.length > 0 ? (
          <details className="rounded-lg border border-line bg-surface p-4">
            <summary className="cursor-pointer text-sm font-semibold text-ink">Event log ({events.length})</summary>
            <ol className="mt-3 max-h-80 overflow-auto font-mono text-xs">
              {events.map((e) => (
                <li key={e.seq} className="flex gap-3 border-b border-line py-1 last:border-0">
                  <span className="w-8 shrink-0 text-right text-muted">{e.seq}</span>
                  <span className="w-20 shrink-0 text-muted">{e.ts.slice(11, 19)}</span>
                  <span className="w-40 shrink-0 truncate text-ink-2">{e.step}</span>
                  <span
                    className={cx(
                      "w-28 shrink-0",
                      e.status === "failed" ? "text-danger" : e.status === "awaiting_review" ? "text-warn" : "text-ink-2",
                    )}
                  >
                    {e.status}
                  </span>
                  <span className="min-w-0 break-words text-ink">{e.message}</span>
                </li>
              ))}
            </ol>
          </details>
        ) : null}
      </div>

      <aside className="flex flex-col gap-5">
        <Card className="p-4">
          <SectionHeading>Findings</SectionHeading>
          <dl className="grid grid-cols-2 gap-2">
            <Stat label="Sources found" value={briefing.sources.length} />
            <Stat label="Treatment options" value={briefing.treatment_options.length} />
            <Stat label="Suggested" value={suggested} />
            <Stat label="Conflicts" value={briefing.conflicts.length} />
          </dl>
        </Card>
        <Card className="p-4">
          <SectionHeading>Run details</SectionHeading>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
            <dt className="text-muted">Provider</dt>
            <dd className="text-ink">{provider}</dd>
            <dt className="text-muted">Sources</dt>
            <dd className="text-ink">{run.data_mode === "live" ? "Live (PubMed, MedlinePlus)" : "Replay (recorded)"}</dd>
            <dt className="text-muted">Model</dt>
            <dd className="break-words font-mono text-xs leading-5 text-ink">{run.model}</dd>
            <dt className="text-muted">Lite model</dt>
            <dd className="break-words font-mono text-xs leading-5 text-ink">{run.model_lite}</dd>
            <dt className="text-muted">Tokens</dt>
            <dd className="tabular-nums text-ink">
              {formatTokens(run.tokens_in)} in {"·"} {formatTokens(run.tokens_out)} out
            </dd>
            <dt className="text-muted">Est. cost</dt>
            <dd className="tabular-nums text-ink">{formatUsd(run.est_cost_usd)}</dd>
            <dt className="text-muted">Started</dt>
            <dd className="text-ink">{formatDateTime(briefing.research_started_at)}</dd>
            <dt className="text-muted">Completed</dt>
            <dd className="text-ink">{formatDateTime(briefing.research_completed_at)}</dd>
            <dt className="text-muted">Snapshot</dt>
            <dd className="text-ink">
              {formatDateTime(snapshot)}
              {run.data_mode === "replay" ? <span className="block text-xs text-muted">recorded earlier (replay)</span> : null}
            </dd>
            {run.model_versions.length > 0 ? (
              <>
                <dt className="text-muted">Model versions</dt>
                <dd className="break-words font-mono text-xs leading-5 text-ink">{run.model_versions.join(", ")}</dd>
              </>
            ) : null}
          </dl>
        </Card>
      </aside>
    </div>
  );
}
