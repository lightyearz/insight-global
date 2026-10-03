"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, FileText, Lock, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import { useCurrentUserId } from "@/lib/current-user";
import { researchConductedAt } from "@/lib/format";
import {
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  DIRECTION_LABEL,
  DIRECTION_ORDER,
  LINE_LABEL,
  LINE_ORDER,
} from "@/lib/labels";
import type { Briefing, Conflict, ReviewSubmission, TreatmentOption } from "@/lib/types";
import { DISCLAIMER } from "@/lib/types";
import { useAsync } from "@/hooks/use-async";
import { TierLegend } from "./badges";
import { ConflictCard, draftError, emptyDraft, overridesSuggestion, type ConflictDraft } from "./ConflictCard";
import { OptionCard, type OptionConflictRef } from "./OptionCard";
import { Button, Callout, cx, SectionHeading } from "./ui";

type GroupBy = "category" | "line" | "recommendation";
type Filter = "all" | "suggested" | "changed" | "conflict";

const GROUP_LABEL: Record<GroupBy, string> = {
  category: "Category",
  line: "Line of therapy",
  recommendation: "Recommendation",
};

const FILTER_LABEL: Record<Filter, string> = {
  all: "All",
  suggested: "AI-suggested",
  changed: "Changed by me",
  conflict: "In conflict",
};

function groupOptions(options: TreatmentOption[], by: GroupBy): { key: string; label: string; items: TreatmentOption[] }[] {
  const groups =
    by === "line"
      ? LINE_ORDER.map((k) => ({ key: k, label: LINE_LABEL[k], items: options.filter((o) => o.line_of_therapy === k) }))
      : by === "recommendation"
        ? DIRECTION_ORDER.map((k) => ({
            key: k,
            label: DIRECTION_LABEL[k],
            items: options.filter((o) => o.recommendation_direction === k),
          }))
        : CATEGORY_ORDER.map((k) => ({ key: k, label: CATEGORY_LABEL[k], items: options.filter((o) => o.category === k) }));
  return groups.filter((g) => g.items.length > 0);
}

// ---------------------------------------------------------------------------
// Draft persistence: a reload must not lose a half-finished review. Per-viewer convenience only, so
// sessionStorage (wrapped: it can throw in private windows); the server state stays authoritative.
// ---------------------------------------------------------------------------

interface StoredDraft {
  selected: string[];
  drafts: Record<string, ConflictDraft>;
  confirmed: Record<string, boolean>;
  keptExcluded: Record<string, boolean>;
}

const storageKey = (id: string) => `health-briefing.review-draft.${id}`;

function loadStored(id: string): StoredDraft | null {
  try {
    const raw = window.sessionStorage.getItem(storageKey(id));
    return raw ? (JSON.parse(raw) as StoredDraft) : null;
  } catch {
    return null;
  }
}

function saveStored(id: string, value: StoredDraft | null): void {
  try {
    if (value) window.sessionStorage.setItem(storageKey(id), JSON.stringify(value));
    else window.sessionStorage.removeItem(storageKey(id));
  } catch {
    // storage unavailable: the review still works, it just is not restored after a reload
  }
}

interface Props {
  briefing: Briefing;
  onSubmitted: (b: Briefing) => void;
}

export function ReviewPanel({ briefing, onSubmitted }: Props) {
  const userId = useCurrentUserId();
  const loadUsers = useCallback(() => api.listUsers(), []);
  const { data: users } = useAsync(loadUsers);
  const me = users?.find((u) => u.id === userId);
  const awaiting = briefing.status === "awaiting_review";
  const permitted = !!me && (me.role === "admin" || me.id === briefing.created_by);
  const editable = awaiting && permitted;

  const sources = useMemo(() => new Map(briefing.sources.map((s) => [s.id, s])), [briefing.sources]);
  const optionMap = useMemo(() => new Map(briefing.treatment_options.map((o) => [o.id, o])), [briefing.treatment_options]);
  const referenceDate = researchConductedAt(briefing.sources) ?? briefing.updated_at;

  // Rendered client-side only (the briefing is fetched in the browser), so sessionStorage is safe here.
  const [stored] = useState<StoredDraft | null>(() => (awaiting ? loadStored(briefing.id) : null));
  const knownOptions = new Set(briefing.treatment_options.map((o) => o.id));
  const [selected, setSelected] = useState<Set<string>>(() =>
    stored
      ? new Set(stored.selected.filter((id) => knownOptions.has(id)))
      : new Set(briefing.treatment_options.filter((o) => o.selected).map((o) => o.id)),
  );
  const [drafts, setDrafts] = useState<Record<string, ConflictDraft>>(() =>
    Object.fromEntries(briefing.conflicts.map((c) => [c.id, stored?.drafts[c.id] ?? emptyDraft()])),
  );
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>(() => stored?.confirmed ?? {});
  const [keptExcluded, setKeptExcluded] = useState<Record<string, boolean>>(() => stored?.keptExcluded ?? {});
  const [groupBy, setGroupBy] = useState<GroupBy>("category");
  const [filter, setFilter] = useState<Filter>("all");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!awaiting) return;
    saveStored(briefing.id, { selected: [...selected], drafts, confirmed, keptExcluded });
  }, [awaiting, briefing.id, selected, drafts, confirmed, keptExcluded]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const isSelected = (o: TreatmentOption) => (awaiting ? selected.has(o.id) : o.selected);
  const selectedCount = awaiting ? selected.size : briefing.treatment_options.filter((o) => o.selected).length;
  const decidedCount = briefing.conflicts.filter((c) => (awaiting ? confirmed[c.id] : c.resolution !== null)).length;
  const openConflicts = briefing.conflicts.length - decidedCount;
  const optionOverrides = briefing.treatment_options.filter((o) => isSelected(o) !== o.suggested).length;
  const conflictOverrides = briefing.conflicts.filter((c) => {
    const d = awaiting ? (confirmed[c.id] ? drafts[c.id] : undefined) : c.resolution;
    return d ? overridesSuggestion(c, d) : false;
  }).length;

  const decisionOf = (c: Conflict) => (awaiting ? (confirmed[c.id] ? drafts[c.id]?.decision : null) : c.resolution?.decision);
  const conflictsByOption = useMemo(() => {
    const map = new Map<string, Conflict[]>();
    for (const c of briefing.conflicts) {
      for (const id of c.treatment_option_ids) map.set(id, [...(map.get(id) ?? []), c]);
    }
    return map;
  }, [briefing.conflicts]);
  const conflictRefs = (o: TreatmentOption): OptionConflictRef[] =>
    (conflictsByOption.get(o.id) ?? []).map((c) => {
      const decision = decisionOf(c);
      return { id: c.id, topic: c.topic, decided: !!decision, excluded: decision === "exclude_topic" };
    });

  const blockers: string[] = [];
  if (selectedCount === 0) blockers.push("Select at least one treatment option.");
  if (openConflicts > 0) {
    blockers.push(`Confirm a decision for ${openConflicts} ${openConflicts === 1 ? "conflict" : "conflicts"}.`);
  }

  const submit = async () => {
    if (blockers.length > 0) return;
    const submission: ReviewSubmission = {
      selected_option_ids: briefing.treatment_options.filter((o) => selected.has(o.id)).map((o) => o.id),
      conflict_resolutions: briefing.conflicts.map((c) => {
        const d = drafts[c.id] ?? emptyDraft();
        return {
          conflict_id: c.id,
          decision: d.decision ?? c.suggested_resolution.decision,
          accepted_source_id: d.decision === "accept_source" ? d.accepted_source_id : null,
          note: d.note.trim(),
        };
      }),
    };
    setSubmitting(true);
    setSubmitError(null);
    try {
      const updated = await api.submitReview(briefing.id, submission);
      saveStored(briefing.id, null);
      onSubmitted(updated);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  const visible = briefing.treatment_options.filter((o) => {
    if (filter === "suggested") return o.suggested;
    if (filter === "changed") return isSelected(o) !== o.suggested;
    if (filter === "conflict") return (conflictsByOption.get(o.id) ?? []).length > 0;
    return true;
  });
  const groups = groupOptions(visible, groupBy);
  const suggestedIds = briefing.treatment_options.filter((o) => o.suggested).map((o) => o.id);

  return (
    <div className="flex flex-col gap-6 pb-24">
      {!awaiting ? (
        <Callout tone="neutral" role="note" icon={<Lock className="size-4" aria-hidden="true" />} title="Review is closed">
          {briefing.reviewed_by
            ? `Reviewed by ${briefing.reviewed_by}. These are the recorded decisions.`
            : "This briefing is not awaiting review."}
        </Callout>
      ) : me && !permitted ? (
        <Callout tone="warn" role="note" icon={<Lock className="size-4" aria-hidden="true" />} title="Read-only">
          Only {briefing.created_by} (the creator) or an admin can review this briefing. Switch user in the header to act
          as an admin.
        </Callout>
      ) : (
        <Callout tone="accent" role="note" title="Your review decides what goes into the report">
          <p>
            The AI has pre-selected the options it considers relevant. For each conflict, read both positions and choose
            a resolution yourself; a rule-based suggestion is marked but nothing is pre-chosen. Overriding a suggestion
            needs a short note, which is kept in the audit log.
          </p>
          <p className="mt-1.5 flex items-start gap-1.5 text-xs">
            <ShieldAlert aria-hidden="true" className="mt-px size-3.5 shrink-0 text-warn" />
            <span>
              <strong className="font-semibold">Not medical advice.</strong> {DISCLAIMER}
            </span>
          </p>
        </Callout>
      )}

      <TierLegend />

      {briefing.conflicts.length > 0 ? (
        <section aria-labelledby="conflicts-heading">
          <SectionHeading
            id="conflicts-heading"
            aside={
              <span
                aria-live="polite"
                className={cx("text-sm font-medium", openConflicts > 0 ? "text-warn" : "text-ok")}
              >
                {decidedCount} of {briefing.conflicts.length} decided
              </span>
            }
          >
            Conflicting sources ({briefing.conflicts.length})
          </SectionHeading>
          <div className="flex flex-col gap-4">
            {briefing.conflicts.map((c) => {
              const draft = drafts[c.id];
              const excludedNow = awaiting && confirmed[c.id] && draft?.decision === "exclude_topic";
              const affected = excludedNow
                ? c.treatment_option_ids.filter((id) => selected.has(id)).map((id) => optionMap.get(id)?.name ?? id)
                : [];
              return (
                <div key={c.id} className="flex flex-col gap-2">
                  <ConflictCard
                    conflict={c}
                    sources={sources}
                    options={optionMap}
                    referenceDate={referenceDate}
                    edit={
                      awaiting && draft
                        ? {
                            draft,
                            confirmed: !!confirmed[c.id],
                            disabled: !editable || submitting,
                            onChange: (d) => setDrafts((prev) => ({ ...prev, [c.id]: d })),
                            onConfirm: () => {
                              if (!draftError(c, draft)) setConfirmed((prev) => ({ ...prev, [c.id]: true }));
                            },
                            onEdit: () => setConfirmed((prev) => ({ ...prev, [c.id]: false })),
                          }
                        : undefined
                    }
                  />
                  {excludedNow && affected.length > 0 && !keptExcluded[c.id] ? (
                    <Callout tone="warn" role="status" icon={<AlertTriangle className="size-4" aria-hidden="true" />}>
                      <p>
                        You excluded this topic from the report narrative, but {affected.length} affected{" "}
                        {affected.length === 1 ? "option is" : "options are"} still selected: {affected.join(", ")}. They
                        will appear in the options table, labelled as linked to an excluded topic.
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Button
                          disabled={!editable}
                          onClick={() =>
                            setSelected((prev) => {
                              const next = new Set(prev);
                              c.treatment_option_ids.forEach((id) => next.delete(id));
                              return next;
                            })
                          }
                        >
                          Deselect them
                        </Button>
                        <Button variant="ghost" onClick={() => setKeptExcluded((prev) => ({ ...prev, [c.id]: true }))}>
                          Keep them selected
                        </Button>
                      </div>
                    </Callout>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>
      ) : (
        <Callout tone="ok" role="note" title="No conflicts detected">
          The retrieved sources did not disagree on any treatment topic.
        </Callout>
      )}

      <section aria-labelledby="options-heading">
        <SectionHeading id="options-heading">
          Treatment options ({selectedCount} of {briefing.treatment_options.length} selected)
        </SectionHeading>
        <div className="no-print mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          <div role="group" aria-label="Group options by" className="flex items-center gap-1.5 text-xs text-muted">
            <span>Group by</span>
            <span className="inline-flex rounded-md border border-line-strong p-0.5">
              {(Object.keys(GROUP_LABEL) as GroupBy[]).map((g) => (
                <button
                  key={g}
                  type="button"
                  aria-pressed={groupBy === g}
                  onClick={() => setGroupBy(g)}
                  className={cx(
                    "rounded px-2 py-0.5 text-xs font-medium",
                    groupBy === g ? "bg-ink text-white" : "text-ink-2 hover:bg-subtle",
                  )}
                >
                  {GROUP_LABEL[g]}
                </button>
              ))}
            </span>
          </div>
          <div role="group" aria-label="Show options" className="flex items-center gap-1.5 text-xs text-muted">
            <span>Show</span>
            <span className="inline-flex rounded-md border border-line-strong p-0.5">
              {(Object.keys(FILTER_LABEL) as Filter[]).map((f) => (
                <button
                  key={f}
                  type="button"
                  aria-pressed={filter === f}
                  onClick={() => setFilter(f)}
                  className={cx(
                    "rounded px-2 py-0.5 text-xs font-medium",
                    filter === f ? "bg-ink text-white" : "text-ink-2 hover:bg-subtle",
                  )}
                >
                  {FILTER_LABEL[f]}
                </button>
              ))}
            </span>
          </div>
          {awaiting ? (
            <div className="flex flex-wrap items-center gap-1">
              <Button
                variant="ghost"
                disabled={!editable}
                onClick={() => setSelected(new Set(briefing.treatment_options.map((o) => o.id)))}
              >
                Select all
              </Button>
              <Button variant="ghost" disabled={!editable} onClick={() => setSelected(new Set())}>
                Select none
              </Button>
              <Button variant="ghost" disabled={!editable} onClick={() => setSelected(new Set(suggestedIds))}>
                Reset to AI suggestions
              </Button>
            </div>
          ) : null}
        </div>
        {groups.length === 0 ? <p className="text-sm text-muted">No options match this filter.</p> : null}
        <div className="flex flex-col gap-5">
          {groups.map((g) => (
            <div key={g.key} role="group" aria-labelledby={`group-${g.key}`}>
              <h3 id={`group-${g.key}`} className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                {g.label} ({g.items.length})
              </h3>
              <div className="flex flex-col gap-3">
                {g.items.map((o) => (
                  <OptionCard
                    key={o.id}
                    option={o}
                    sources={sources}
                    selected={isSelected(o)}
                    onToggle={toggle}
                    disabled={!editable || submitting}
                    conflicts={conflictRefs(o)}
                    showOverride
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {awaiting ? (
        <div className="no-print sticky bottom-0 z-10 -mx-4 border-t border-line bg-surface/95 px-4 py-3 shadow-[0_-4px_12px_rgba(18,24,38,0.06)] backdrop-blur sm:-mx-6 sm:px-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm" id="generate-status" aria-live="polite">
              <p className="text-ink">
                <span className="font-semibold">{selectedCount}</span> of {briefing.treatment_options.length} options
                selected {"·"} <span className="font-semibold">{decidedCount}</span> of {briefing.conflicts.length}{" "}
                conflicts decided {"·"} <span className="font-semibold">{optionOverrides + conflictOverrides}</span>{" "}
                {optionOverrides + conflictOverrides === 1 ? "change" : "changes"} from the suggestions
              </p>
              {editable && blockers.length > 0 ? (
                <p className="flex items-center gap-1 text-xs font-medium text-warn">
                  <AlertTriangle aria-hidden="true" className="size-3.5" />
                  {blockers.join(" ")}
                </p>
              ) : null}
              {submitError ? (
                <p role="alert" className="text-xs font-medium text-danger">
                  {submitError}
                </p>
              ) : null}
            </div>
            <Button
              variant="primary"
              onClick={() => void submit()}
              disabled={!editable || blockers.length > 0 || submitting}
              aria-describedby="generate-status"
            >
              <FileText aria-hidden="true" className="size-4" />
              {submitting ? "Submitting…" : "Generate report"}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
