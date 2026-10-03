import { AlertTriangle, Bot, CalendarClock, GitCompareArrows, UserRoundPen } from "lucide-react";
import { formatPartialDate, keyed } from "@/lib/format";
import { CATEGORY_LABEL, LINE_LABEL, STANCE_LABEL } from "@/lib/labels";
import type { Source, TreatmentOption } from "@/lib/types";
import { ConfidenceBadge, DirectionBadge, GroundedFlag, SourceChip, UnknownSourceChip } from "./badges";
import { conflictAnchor } from "./ConflictCard";
import { Badge, cx } from "./ui";

/** A conflict that involves this option, as shown on the option card. */
export interface OptionConflictRef {
  id: string;
  topic: string;
  decided: boolean;
  excluded: boolean;
}

interface Props {
  option: TreatmentOption;
  sources: ReadonlyMap<string, Source>;
  selected: boolean;
  onToggle?: (id: string) => void;
  disabled?: boolean;
  conflicts?: OptionConflictRef[];
  /** Show the "you changed this" marker when the selection differs from the AI suggestion. */
  showOverride?: boolean;
}

const STANCE_TONE = {
  recommended: "text-ok",
  recommended_against: "text-danger",
  conditional: "text-info",
  insufficient_evidence: "text-warn",
  described: "text-muted",
} as const;

export function OptionCard({ option, sources, selected, onToggle, disabled, conflicts = [], showOverride = false }: Props) {
  const checkboxId = `select-${option.id}`;
  const summaryId = `${option.id}-summary`;
  const ungrounded = option.evidence.filter((e) => !e.grounded).length;
  return (
    <article
      aria-labelledby={`${option.id}-name`}
      className={cx(
        "print-break-avoid min-w-0 rounded-lg border bg-surface p-4 transition-colors",
        selected ? "border-accent shadow-[inset_3px_0_0_var(--color-accent)]" : "border-line",
      )}
    >
      <div className="flex gap-3">
        <input
          id={checkboxId}
          type="checkbox"
          checked={selected}
          disabled={disabled}
          onChange={() => onToggle?.(option.id)}
          aria-describedby={summaryId}
          className="mt-1 size-4 shrink-0 accent-accent"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <label id={`${option.id}-name`} htmlFor={checkboxId} className="cursor-pointer text-sm font-semibold text-ink">
                {option.name}
              </label>
              {option.drug_class ? <p className="text-xs text-muted">{option.drug_class}</p> : null}
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Badge>{CATEGORY_LABEL[option.category]}</Badge>
              <Badge>{LINE_LABEL[option.line_of_therapy]}</Badge>
              <DirectionBadge direction={option.recommendation_direction} />
              <ConfidenceBadge confidence={option.confidence} />
            </div>
          </div>

          {showOverride && selected !== option.suggested ? (
            <p className="mt-2 inline-flex items-center gap-1.5 rounded border border-accent-line bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent">
              <UserRoundPen aria-hidden="true" className="size-3.5" />
              You changed this (AI suggested {option.suggested ? "including" : "leaving it out"})
            </p>
          ) : null}

          {conflicts.length > 0 ? (
            <ul className="mt-2 flex flex-col gap-1">
              {conflicts.map((c) => (
                <li key={c.id}>
                  <a
                    href={`#${conflictAnchor(c.id)}`}
                    className={cx(
                      "inline-flex items-start gap-1.5 rounded border px-2 py-0.5 text-xs hover:underline",
                      c.excluded
                        ? "border-line bg-subtle text-ink-2"
                        : c.decided
                          ? "border-ok/30 bg-ok-soft text-ink-2"
                          : "border-warn-line bg-warn-soft text-warn",
                    )}
                  >
                    <GitCompareArrows aria-hidden="true" className="mt-px size-3.5 shrink-0" />
                    <span>
                      In conflict: {c.topic} —{" "}
                      <strong className="font-semibold">
                        {c.excluded ? "topic excluded from report" : c.decided ? "decided" : "decision pending"}
                      </strong>
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          ) : null}

          <p
            className={cx(
              "mt-2 flex items-start gap-1.5 rounded px-2 py-1 text-xs",
              option.suggested ? "bg-accent-soft text-ink-2" : "bg-subtle text-ink-2",
            )}
          >
            <Bot aria-hidden="true" className="mt-px size-3.5 shrink-0 text-muted" />
            <span>
              <strong className="font-semibold">{option.suggested ? "AI suggests including" : "AI suggests leaving out"}:</strong>{" "}
              {option.suggestion_reason || "No reason given"}
            </span>
          </p>

          <p id={summaryId} className="mt-2 text-sm text-ink-2">
            {option.summary}
          </p>
          <p className="mt-1 text-xs text-muted">
            <span className="font-medium text-ink-2">Population:</span> {option.population}
          </p>

          {ungrounded > 0 ? (
            <p className="mt-2 flex items-center gap-1.5 text-xs font-medium text-warn">
              <AlertTriangle aria-hidden="true" className="size-3.5" />
              {ungrounded} of {option.evidence.length} quotes could not be found verbatim in the source; confidence was
              lowered.
            </p>
          ) : null}

          <details className="group mt-3" open={option.evidence.length <= 2}>
            <summary className="cursor-pointer text-xs font-semibold text-ink-2">
              Evidence ({option.evidence.length})
            </summary>
            <ul className="mt-2 flex flex-col gap-2">
              {keyed(option.evidence, (e) => `${e.source_id}-${e.quote}`).map(([key, e]) => {
                const src = sources.get(e.source_id);
                return (
                  <li key={key} className="rounded-md border border-line bg-canvas px-3 py-2">
                    <blockquote
                      className={cx(
                        "border-l-2 pl-2 text-xs italic text-ink-2",
                        e.grounded ? "border-line-strong" : "border-warn",
                      )}
                    >
                      {"“"}
                      {e.quote}
                      {"”"}
                    </blockquote>
                    <p className="mt-1 text-xs text-ink">
                      <span className={cx("font-semibold", STANCE_TONE[e.stance])}>{STANCE_LABEL[e.stance]}:</span>{" "}
                      {e.statement}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      {src ? <SourceChip source={src} /> : <UnknownSourceChip id={e.source_id} />}
                      <GroundedFlag grounded={e.grounded} />
                      {e.recommendation_strength ? (
                        <span className="text-xs text-muted">Strength: {e.recommendation_strength}</span>
                      ) : null}
                      {e.evidence_level ? <span className="text-xs text-muted">Evidence: {e.evidence_level}</span> : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </details>

          {option.milestones.length > 0 ? (
            <div className="mt-2">
              <p className="text-xs font-semibold text-ink-2">Milestones</p>
              <ul className="mt-1 flex flex-col gap-1">
                {keyed(option.milestones, (m) => `${m.date}-${m.label}`).map(([key, m]) => (
                  <li key={key} className="flex flex-wrap items-center gap-1.5 text-xs text-ink-2">
                    <CalendarClock aria-hidden="true" className="size-3.5 text-milestone" />
                    <span className="font-medium tabular-nums">{formatPartialDate(m.date)}</span>
                    <span>{m.label}</span>
                    {!m.grounded ? <GroundedFlag grounded={false} /> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div>
    </article>
  );
}
