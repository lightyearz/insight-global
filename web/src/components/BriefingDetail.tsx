"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { ArrowLeft, RotateCcw, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useCurrentUserId } from "@/lib/current-user";
import { formatDateTime } from "@/lib/format";
import { REGION_LABEL, STEP_LABEL } from "@/lib/labels";
import type { Briefing, BriefingStatus } from "@/lib/types";
import { useAsync } from "@/hooks/use-async";
import { useBriefing } from "@/hooks/use-briefing";
import { StatusBadge } from "./badges";
import { ReportView } from "./ReportView";
import { ResearchPanel } from "./ResearchPanel";
import { ReviewPanel } from "./ReviewPanel";
import { Stepper, type Stage, type StageKey } from "./Stepper";
import { Button, Callout, Card, Spinner } from "./ui";

function defaultStage(status: BriefingStatus): StageKey {
  if (status === "awaiting_review") return "review";
  if (status === "generating_report" || status === "completed") return "report";
  return "research";
}

function stagesFor(b: Briefing): Stage[] {
  const researchDone = b.research_completed_at !== null;
  const reviewed = b.reviewed_at !== null;
  return [
    {
      key: "research",
      label: "Research",
      description: "Agent retrieves and extracts",
      state: researchDone ? "done" : b.status === "failed" ? "failed" : "current",
    },
    {
      key: "review",
      label: "Review",
      description: "You select and resolve",
      state: reviewed ? "done" : b.status === "awaiting_review" ? "current" : "upcoming",
    },
    {
      key: "report",
      label: "Report",
      description: "Briefing with sources",
      state:
        b.status === "completed"
          ? "done"
          : b.status === "generating_report"
            ? "current"
            : b.status === "failed" && reviewed
              ? "failed"
              : "upcoming",
    },
  ];
}

export function BriefingDetail({ id }: { id: string }) {
  const router = useRouter();
  const { briefing, events, error, notFound, replace } = useBriefing(id);
  const userId = useCurrentUserId();
  const loadUsers = useCallback(() => api.listUsers(), []);
  const { data: users } = useAsync(loadUsers);
  const [picked, setPicked] = useState<StageKey | null>(null);
  const [seenStatus, setSeenStatus] = useState<BriefingStatus | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);

  // When the status moves on, jump to the matching stage (reset during render, not in an effect).
  if (briefing && briefing.status !== seenStatus) {
    setSeenStatus(briefing.status);
    setPicked(null);
  }

  if (notFound) {
    return (
      <Callout tone="warn" role="alert" title="Briefing not found">
        It may have been deleted.{" "}
        <Link href="/" className="font-medium text-accent underline">
          Back to briefings
        </Link>
      </Callout>
    );
  }
  if (!briefing) {
    return error ? (
      <Callout tone="danger" role="alert" title="Could not load the briefing">
        {error}
      </Callout>
    ) : (
      <Spinner label="Loading briefing" />
    );
  }

  const me = users?.find((u) => u.id === userId);
  const canDelete = !!me && (me.role === "admin" || me.id === briefing.created_by);
  const viewing = picked ?? defaultStage(briefing.status);
  const writeStep = briefing.run.steps.find((s) => s.name === "write_report");

  const onDelete = async () => {
    if (!window.confirm(`Delete the briefing for "${briefing.condition.label}"? This cannot be undone.`)) return;
    try {
      await api.deleteBriefing(briefing.id);
      router.push("/");
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : String(err));
    }
  };

  const onRetry = async () => {
    setRetrying(true);
    setDeleteError(null);
    try {
      replace(await api.retryBriefing(briefing.id));
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : String(err));
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="no-print flex flex-col gap-3">
        <Link href="/" className="inline-flex w-fit items-center gap-1 text-sm text-ink-2 hover:text-accent">
          <ArrowLeft aria-hidden="true" className="size-4" />
          All briefings
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold text-ink">{briefing.condition.label}</h1>
              <StatusBadge status={briefing.status} />
            </div>
            <p className="mt-1 text-sm text-muted">
              {REGION_LABEL[briefing.region]} {"·"} requested as {"“"}
              {briefing.condition.input}
              {"”"}
              {briefing.condition.mesh_id ? ` · MeSH ${briefing.condition.mesh_id}` : ""} {"·"} created by{" "}
              {briefing.created_by}, {formatDateTime(briefing.created_at)} {"·"}{" "}
              <span className="font-mono text-xs">{briefing.id}</span>
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {canDelete && briefing.status === "failed" ? (
              <Button
                onClick={() => void onRetry()}
                disabled={retrying}
                title="Resume the run from its last saved checkpoint (the step that failed)"
              >
                <RotateCcw aria-hidden="true" className="size-4" />
                {retrying ? "Retrying…" : "Retry from last step"}
              </Button>
            ) : null}
            {canDelete ? (
              <Button variant="danger" onClick={() => void onDelete()}>
                <Trash2 aria-hidden="true" className="size-4" />
                Delete
              </Button>
            ) : null}
          </div>
        </div>
        {deleteError ? (
          <Callout tone="danger" role="alert">
            {deleteError}
          </Callout>
        ) : null}
        <Stepper stages={stagesFor(briefing)} viewing={viewing} onSelect={setPicked} />
      </div>

      {viewing === "research" ? <ResearchPanel briefing={briefing} events={events} /> : null}

      {viewing === "review" ? (
        <ReviewPanel
          key={`${briefing.id}-${briefing.status}`}
          briefing={briefing}
          onSubmitted={(b) => {
            replace(b);
          }}
        />
      ) : null}

      {viewing === "report" ? (
        briefing.report ? (
          <ReportView report={briefing.report} />
        ) : briefing.status === "generating_report" ? (
          <Card className="flex flex-col items-start gap-2 p-6">
            <Spinner label="Writing the report" />
            <p className="text-sm text-muted">
              {STEP_LABEL.write_report}: {writeStep?.status === "running" ? "in progress" : (writeStep?.status ?? "pending")}.
              The report uses only the options you selected and your conflict decisions.
            </p>
          </Card>
        ) : briefing.status === "failed" ? (
          <Callout tone="danger" role="alert" title="Report generation failed">
            {briefing.error ?? "Unknown error"}
          </Callout>
        ) : (
          <Card className="p-6 text-sm text-muted">The report is written after the review is submitted.</Card>
        )
      ) : null}

    </div>
  );
}
