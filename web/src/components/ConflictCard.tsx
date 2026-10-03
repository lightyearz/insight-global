import { Bot, CheckCircle2, GitCompareArrows, Pencil, Scale, Wand2 } from "lucide-react";
import { ageLabel, effectiveDate, formatDateTime, formatPartialDate, keyed, partialDateToYear, sourceShortName } from "@/lib/format";
import { CONFLICT_TYPE_LABEL, decisionLabel, RULE_LABEL } from "@/lib/labels";
import { safeHref } from "@/lib/safe-href";
import type { Conflict, ConflictDecision, ConflictPosition, Source, TreatmentOption } from "@/lib/types";
import { GroundedFlag, TierBadge } from "./badges";
import { Badge, Button, cx } from "./ui";

/** A reviewer's in-progress decision. `decision` starts as null: nothing is pre-chosen for the human. */
export interface ConflictDraft {
  decision: ConflictDecision | null;
  accepted_source_id: string | null;
  note: string;
}

export const NOTE_MAX = 2000;

export function emptyDraft(): ConflictDraft {
  return { decision: null, accepted_source_id: null, note: "" };
}

/** True when the draft differs from the system's suggested resolution. */
export function overridesSuggestion(conflict: Conflict, d: Pick<ConflictDraft, "decision" | "accepted_source_id">): boolean {
  const s = conflict.suggested_resolution;
  if (d.decision === null) return false;
  return d.decision !== s.decision || (d.decision === "accept_source" && d.accepted_source_id !== s.accepted_source_id);
}

export function draftError(conflict: Conflict, d: ConflictDraft): string | null {
  if (d.decision === null) return "Choose a resolution.";
  if (d.decision === "accept_source" && !d.accepted_source_id) return "Choose which source to accept.";
  if (d.decision === "custom" && !d.note.trim()) return "A custom resolution needs a note.";
  if (overridesSuggestion(conflict, d) && !d.note.trim()) return "Add a note: you are overriding the suggestion.";
  if (d.note.length > NOTE_MAX) return `The note is limited to ${NOTE_MAX} characters.`;
  return null;
}

const LETTERS = "ABCDEFGH";

export function positionLetter(conflict: Conflict, sourceId: string | null): string {
  const i = conflict.positions.findIndex((p) => p.source_id === sourceId);
  return i >= 0 ? (LETTERS[i] ?? String(i + 1)) : "?";
}

/** Human summary of a decision, e.g. "Accept source B (American College of Physicians)". */
export function describeDecision(
  conflict: Conflict,
  decision: ConflictDecision,
  acceptedSourceId: string | null,
  sources: ReadonlyMap<string, Source>,
  maxLen = 40,
): string {
  if (decision !== "accept_source") return decisionLabel(decision, conflict.positions.length);
  const src = acceptedSourceId ? sources.get(acceptedSourceId) : undefined;
  // "BMJ (Clinical research ed.)" -> "BMJ": avoid nested parentheses in the label.
  const name = src ? sourceShortName(src, maxLen).replace(/\s*\([^)]*\)$/, "") : "";
  const year = src ? (effectiveDate(src) ?? "").slice(0, 4) : "";
  return `Accept source ${positionLetter(conflict, acceptedSourceId)}${src ? ` (${name}${year ? `, ${year}` : ""})` : ""}`;
}

/** Source id of the single most recent position (by effective date), if one is strictly newest. */
function newestSourceId(conflict: Conflict, sources: ReadonlyMap<string, Source>): string | null {
  let best: { id: string; y: number } | null = null;
  let tie = false;
  for (const p of conflict.positions) {
    const src = sources.get(p.source_id);
    const d = src ? effectiveDate(src) : p.published_at;
    if (!d) continue;
    const y = partialDateToYear(d);
    if (!best || y > best.y) {
      best = { id: p.source_id, y };
      tie = false;
    } else if (y === best.y) tie = true;
  }
  return best && !tie ? best.id : null;
}

function PositionCard({
  position,
  letter,
  sideCount,
  source,
  suggested,
  chosen,
  newest,
  referenceDate,
}: {
  position: ConflictPosition;
  letter: string;
  sideCount: number;
  source: Source | undefined;
  suggested: boolean;
  chosen: boolean;
  newest: boolean;
  referenceDate: string;
}) {
  const href = safeHref(source?.url);
  return (
    <div
      className={cx(
        "flex min-w-0 flex-col gap-2 rounded-md border p-3",
        chosen ? "border-accent bg-accent-soft/50" : "border-line bg-canvas",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-bold uppercase tracking-wide text-ink-2">
          Source {letter}
          {sideCount > 1 ? <span className="ml-1.5 font-semibold normal-case text-muted">· Position {position.side}</span> : null}
        </span>
        <div className="flex flex-wrap gap-1.5">
          {chosen ? (
            <Badge tone="accent">
              <CheckCircle2 aria-hidden="true" className="size-3.5" />
              Your choice
            </Badge>
          ) : null}
          {suggested ? (
            <Badge tone="info">
              <Scale aria-hidden="true" className="size-3.5" />
              Suggested
            </Badge>
          ) : null}
          {newest ? <Badge tone="neutral">Newer</Badge> : null}
          <TierBadge tier={position.reliability_tier} rationale={source?.tier_rationale} />
        </div>
      </div>
      <p className="text-sm font-medium text-ink">{position.statement}</p>
      <blockquote
        className={cx("border-l-2 pl-2 text-xs italic text-ink-2", position.grounded ? "border-line-strong" : "border-warn")}
      >
        {"“"}
        {position.quote}
        {"”"}
      </blockquote>
      <GroundedFlag grounded={position.grounded} />
      <div className="mt-auto border-t border-line pt-2 text-xs text-ink-2">
        {source ? (
          <>
            {href ? (
              <a href={href} target="_blank" rel="noopener noreferrer" className="font-medium text-accent hover:underline">
                {source.title}
              </a>
            ) : (
              <span className="font-medium text-ink">{source.title}</span>
            )}
            <p className="mt-0.5 text-muted">
              {source.issuing_body ? `${source.issuing_body} · ` : ""}
              {source.publisher}
              {source.region ? ` · ${source.region}${source.region_inferred ? " (region inferred by AI)" : ""}` : ""}
            </p>
          </>
        ) : (
          <p className="font-mono">{position.source_id}</p>
        )}
        <dl className="mt-1.5 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5">
          <dt className="text-muted">Published</dt>
          <dd>
            <span className="font-medium text-ink">{formatPartialDate(position.published_at)}</span>
            <span className="text-muted"> ({ageLabel(position.published_at, referenceDate)} at research date)</span>
          </dd>
          <dt className="text-muted">Last updated</dt>
          <dd className="text-ink">{formatPartialDate(source?.updated_at ?? null)}</dd>
          <dt className="text-muted">Retrieved</dt>
          <dd className="text-ink">{source ? formatDateTime(source.retrieved_at) : "-"}</dd>
          <dt className="text-muted">Tier rule</dt>
          <dd className="text-ink-2">{source?.tier_rationale.replace(/^Rule:\s*/, "") ?? "-"}</dd>
        </dl>
      </div>
    </div>
  );
}

interface Props {
  conflict: Conflict;
  sources: ReadonlyMap<string, Source>;
  options: ReadonlyMap<string, TreatmentOption>;
  referenceDate: string;
  /** Editable mode (awaiting review). Omit for read-only display of conflict.resolution. */
  edit?: {
    draft: ConflictDraft;
    confirmed: boolean;
    disabled: boolean;
    onChange: (d: ConflictDraft) => void;
    onConfirm: () => void;
    onEdit: () => void;
  };
}

export function conflictAnchor(conflictId: string): string {
  return `conflict-${conflictId}`;
}

export function ConflictCard({ conflict, sources, options, referenceDate, edit }: Props) {
  const sugg = conflict.suggested_resolution;
  const headingId = `${conflict.id}-topic`;
  const draft = edit?.draft;
  // Only a real human choice (draft or recorded resolution) highlights a source; the suggestion never does.
  const chosenSource = draft
    ? draft.decision === "accept_source"
      ? draft.accepted_source_id
      : null
    : conflict.resolution?.decision === "accept_source"
      ? conflict.resolution.accepted_source_id
      : null;
  const error = draft ? draftError(conflict, draft) : null;
  const overriding = draft ? overridesSuggestion(conflict, draft) : false;
  const radioName = `decision-${conflict.id}`;
  const sideCount = new Set(conflict.positions.map((p) => p.side)).size;
  const newest = newestSourceId(conflict, sources);

  const choices: { value: string; label: string; decision: ConflictDecision; source: string | null }[] = [
    ...conflict.positions.map((p) => ({
      value: `accept:${p.source_id}`,
      label: describeDecision(conflict, "accept_source", p.source_id, sources, 60),
      decision: "accept_source" as const,
      source: p.source_id,
    })),
    {
      value: "accept_both_with_context",
      label: decisionLabel("accept_both_with_context", conflict.positions.length),
      decision: "accept_both_with_context",
      source: null,
    },
    { value: "exclude_topic", label: "Exclude this topic from the report", decision: "exclude_topic", source: null },
    { value: "custom", label: "Custom resolution (note required)", decision: "custom", source: null },
  ];
  const isSuggested = (c: (typeof choices)[number]) =>
    c.decision === sugg.decision && (c.decision !== "accept_source" || c.source === sugg.accepted_source_id);
  const currentValue =
    draft && draft.decision !== null
      ? draft.decision === "accept_source"
        ? `accept:${draft.accepted_source_id ?? ""}`
        : draft.decision
      : "";
  const noteLabel =
    draft?.decision === "custom"
      ? "Note (required for a custom resolution)"
      : overriding
        ? "Note (required: you are overriding the suggestion)"
        : "Note (optional, recorded in the conflict log)";

  return (
    <article
      id={conflictAnchor(conflict.id)}
      aria-labelledby={headingId}
      className={cx(
        "print-break-avoid scroll-mt-4 rounded-lg border bg-surface target:ring-2 target:ring-accent",
        edit && !edit.confirmed ? "border-warn-line" : "border-line",
      )}
    >
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h3 id={headingId} className="flex items-start gap-2 text-sm font-semibold text-ink">
            <GitCompareArrows aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warn" />
            {conflict.topic}
          </h3>
          {conflict.treatment_option_ids.length > 0 ? (
            <p className="mt-0.5 pl-6 text-xs text-muted">
              Affects: {conflict.treatment_option_ids.map((id) => options.get(id)?.name ?? id).join(", ")}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge tone="warn">{CONFLICT_TYPE_LABEL[conflict.conflict_type]}</Badge>
          {edit ? (
            edit.confirmed ? (
              <Badge tone="ok">
                <CheckCircle2 aria-hidden="true" className="size-3.5" />
                Decided
              </Badge>
            ) : (
              <Badge tone="neutral">Decision needed</Badge>
            )
          ) : null}
        </div>
      </header>

      <div className="flex flex-col gap-3 px-4 py-3">
        {sideCount > 1 && sideCount < conflict.positions.length ? (
          <p className="text-xs text-muted">
            Sources with the same position number agree with each other; the suggestion compares the best source of
            each position.
          </p>
        ) : null}
        <div className={cx("grid gap-3", conflict.positions.length > 1 && "md:grid-cols-2", conflict.positions.length > 2 && "xl:grid-cols-3")}>
          {keyed(conflict.positions, (p) => p.source_id).map(([key, p]) => {
            const i = conflict.positions.indexOf(p);
            return (
            <PositionCard
              key={key}
              position={p}
              letter={LETTERS[i] ?? String(i + 1)}
              sideCount={sideCount}
              source={sources.get(p.source_id)}
              suggested={sugg.decision === "accept_source" && sugg.accepted_source_id === p.source_id}
              chosen={chosenSource === p.source_id}
              newest={newest === p.source_id}
              referenceDate={referenceDate}
            />
            );
          })}
        </div>

        <div className="rounded-md border border-info/30 bg-info-soft px-3 py-2 text-sm">
          <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-info">
            <Bot aria-hidden="true" className="size-3.5" />
            AI assessment (why the sources differ)
          </p>
          <p className="mt-1 text-ink-2">{conflict.ai_assessment}</p>
          <p className="mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs font-semibold uppercase tracking-wide text-info">
            <Scale aria-hidden="true" className="size-3.5" />
            Suggested resolution
            <Badge tone="info" className="normal-case tracking-normal">
              {RULE_LABEL[sugg.rule]}
            </Badge>
          </p>
          <p className="mt-1 text-ink-2">
            <span className="font-semibold text-ink">
              {describeDecision(conflict, sugg.decision, sugg.accepted_source_id, sources, 60)}.
            </span>{" "}
            {sugg.rationale}
          </p>
          <p className="mt-1 text-xs text-muted">
            The suggestion comes from fixed rules (tier, then date, then region), not from the AI. You decide.
          </p>
        </div>

        {edit && draft ? (
          edit.confirmed && draft.decision !== null ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-ok/30 bg-ok-soft px-3 py-2">
              <p className="text-sm text-ink">
                <span className="font-semibold">Your decision:</span>{" "}
                {describeDecision(conflict, draft.decision, draft.accepted_source_id, sources, 60)}
                {overriding ? <span className="text-ink-2"> (overrides the suggestion)</span> : null}
                {draft.note.trim() ? <span className="text-ink-2">{` — ${draft.note.trim()}`}</span> : null}
              </p>
              <Button variant="ghost" onClick={edit.onEdit} disabled={edit.disabled} className="no-print">
                <Pencil aria-hidden="true" className="size-3.5" />
                Change
              </Button>
            </div>
          ) : (
            <fieldset className="no-print rounded-md border border-line px-3 pb-3 pt-1" disabled={edit.disabled}>
              <legend className="px-1 text-sm font-semibold text-ink">Your decision</legend>
              <div className="flex flex-col gap-1">
                {choices.map((c) => (
                  <label
                    key={c.value}
                    className={cx(
                      "flex cursor-pointer flex-wrap items-center gap-2 rounded px-2 py-1 text-sm",
                      currentValue === c.value ? "bg-accent-soft text-ink" : "text-ink-2 hover:bg-subtle",
                    )}
                  >
                    <input
                      type="radio"
                      name={radioName}
                      value={c.value}
                      checked={currentValue === c.value}
                      onChange={() => edit.onChange({ ...draft, decision: c.decision, accepted_source_id: c.source })}
                      className="accent-accent"
                    />
                    <span>{c.label}</span>
                    {isSuggested(c) ? (
                      <Badge tone="info" className="ml-1">
                        Suggested
                      </Badge>
                    ) : null}
                  </label>
                ))}
              </div>
              <div className="mt-2">
                <Button
                  variant="ghost"
                  onClick={() =>
                    edit.onChange({ ...draft, decision: sugg.decision, accepted_source_id: sugg.accepted_source_id })
                  }
                >
                  <Wand2 aria-hidden="true" className="size-3.5" />
                  Use the suggestion
                </Button>
              </div>
              <label htmlFor={`${conflict.id}-note`} className="mt-2 block text-xs font-medium text-ink-2">
                {noteLabel}
              </label>
              <textarea
                id={`${conflict.id}-note`}
                value={draft.note}
                maxLength={NOTE_MAX}
                rows={2}
                onChange={(e) => edit.onChange({ ...draft, note: e.target.value })}
                aria-invalid={!draft.note.trim() && (draft.decision === "custom" || overriding) ? true : undefined}
                aria-describedby={error ? `${conflict.id}-error` : undefined}
                className="mt-1 w-full rounded-md border border-line-strong bg-surface px-2 py-1.5 text-sm"
              />
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <Button variant="primary" onClick={edit.onConfirm} disabled={!!error}>
                  <CheckCircle2 aria-hidden="true" className="size-4" />
                  Confirm decision
                </Button>
                {error ? (
                  <p
                    id={`${conflict.id}-error`}
                    className={cx("text-xs font-medium", draft.decision === null ? "text-muted" : "text-danger")}
                  >
                    {error}
                  </p>
                ) : null}
              </div>
            </fieldset>
          )
        ) : conflict.resolution ? (
          <div className="rounded-md border border-line bg-subtle px-3 py-2 text-sm">
            <p className="text-ink">
              <span className="font-semibold">Decision:</span>{" "}
              {describeDecision(conflict, conflict.resolution.decision, conflict.resolution.accepted_source_id, sources, 60)}
              {overridesSuggestion(conflict, conflict.resolution) ? (
                <span className="text-ink-2"> (overrode the suggestion)</span>
              ) : null}
            </p>
            {conflict.resolution.note ? <p className="mt-0.5 text-ink-2">{conflict.resolution.note}</p> : null}
            <p className="mt-0.5 text-xs text-muted">
              by {conflict.resolution.resolved_by}, {formatDateTime(conflict.resolution.resolved_at)}
            </p>
          </div>
        ) : null}
      </div>
    </article>
  );
}
