"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { AlertTriangle, ArrowRight, Database } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { REGION_LABEL, REGIONS } from "@/lib/labels";
import type { Region } from "@/lib/types";
import { useAsync } from "@/hooks/use-async";
import { ConditionAutocomplete } from "./ConditionAutocomplete";
import { Button, Callout, Card } from "./ui";

function ReplayChips({ onPick }: { onPick: (label: string) => void }) {
  const loadHealth = useCallback(() => api.health(), []);
  const { data: health } = useAsync(loadHealth);
  const loadManifests = useCallback(() => api.listReplayConditions(), []);
  const { data: manifests } = useAsync(loadManifests);
  if (!health || health.data_mode !== "replay") return null;
  return (
    <div className="rounded-md border border-line bg-subtle px-3 py-3">
      <p className="flex items-center gap-1.5 text-sm font-medium text-ink">
        <Database aria-hidden="true" className="size-4 text-muted" />
        Replay mode: recorded conditions
      </p>
      <p className="mt-0.5 text-xs text-muted">
        The API runs without live sources or credentials, so only recorded conditions are available.
      </p>
      {manifests && manifests.length > 0 ? (
        <ul className="mt-2 flex flex-wrap gap-2" aria-label="Recorded conditions">
          {manifests.map((m) => (
            <li key={m.slug}>
              <button
                type="button"
                onClick={() => onPick(m.label)}
                title={`Recorded ${formatDate(m.recorded_at)} (${m.recorded_with})${m.notes ? `: ${m.notes}` : ""}`}
                className="rounded-full border border-accent-line bg-surface px-3 py-1 text-sm text-accent hover:bg-accent-soft"
              >
                {m.label}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-warn">No replay fixtures found.</p>
      )}
    </div>
  );
}

export function NewBriefingForm() {
  const router = useRouter();
  const [condition, setCondition] = useState("");
  const [region, setRegion] = useState<Region>("US");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const invalid = touched && condition.trim().length < 2;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (condition.trim().length < 2) return;
    setSubmitting(true);
    setError(null);
    try {
      const b = await api.createBriefing({ condition: condition.trim(), region });
      router.push(`/briefings/${b.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    <Card className="p-5">
      <form onSubmit={(e) => void onSubmit(e)} noValidate className="flex flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="condition" className="text-sm font-medium text-ink">
            Condition
          </label>
          <ConditionAutocomplete
            value={condition}
            onChange={setCondition}
            invalid={invalid}
            describedBy={invalid ? "condition-hint condition-error" : "condition-hint"}
          />
          <p id="condition-hint" className="text-xs text-muted">
            Start typing for suggestions. The agent normalises the name with MeSH.
          </p>
          {invalid ? (
            <p id="condition-error" className="text-xs font-medium text-danger">
              Enter at least 2 characters.
            </p>
          ) : null}
        </div>

        <ReplayChips onPick={setCondition} />

        <div className="flex flex-col gap-1.5">
          <label htmlFor="region" className="text-sm font-medium text-ink">
            Region
          </label>
          <select
            id="region"
            value={region}
            onChange={(e) => setRegion(e.target.value as Region)}
            aria-describedby="region-hint"
            className="w-full max-w-xs rounded-md border border-line-strong bg-surface px-2 py-2 text-sm"
          >
            {REGIONS.map((r) => (
              <option key={r} value={r}>
                {REGION_LABEL[r]}
              </option>
            ))}
          </select>
          <p id="region-hint" className="text-xs text-muted">
            Used to weigh regional guidance when two sources disagree.
          </p>
        </div>

        {error ? (
          <Callout tone="danger" role="alert" title="Could not start the briefing" icon={<AlertTriangle className="size-4" aria-hidden="true" />}>
            {error}
          </Callout>
        ) : null}

        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={submitting}>
            {submitting ? "Starting research…" : "Start research"}
            <ArrowRight aria-hidden="true" className="size-4" />
          </Button>
          <p className="text-xs text-muted">Research takes about a minute with live sources.</p>
        </div>
      </form>
    </Card>
  );
}
