"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { AlertTriangle, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useCurrentUserId } from "@/lib/current-user";
import { formatDateTime } from "@/lib/format";
import { STATUS_LABEL } from "@/lib/labels";
import type { BriefingStatus, BriefingSummary, User } from "@/lib/types";
import { useAsync } from "@/hooks/use-async";
import { StatusBadge } from "./badges";
import { Button, ButtonLink, Callout, Card, Spinner } from "./ui";

const STATUSES: BriefingStatus[] = ["researching", "awaiting_review", "generating_report", "completed", "failed"];

function canManage(user: User | undefined, row: BriefingSummary): boolean {
  return !!user && (user.role === "admin" || user.id === row.created_by);
}

export function BriefingsTable() {
  const userId = useCurrentUserId();
  const [createdBy, setCreatedBy] = useState("");
  const [status, setStatus] = useState<BriefingStatus | "">("");
  const [actionError, setActionError] = useState<string | null>(null);

  const loadUsers = useCallback(() => api.listUsers(), []);
  const { data: users } = useAsync(loadUsers);
  const loadRows = useCallback(
    () => api.listBriefings({ created_by: createdBy || undefined, status: status || undefined }),
    [createdBy, status],
  );
  const { data: rows, error, loading, reload } = useAsync(loadRows);
  const me = users?.find((u) => u.id === userId);

  const onDelete = async (row: BriefingSummary) => {
    if (!window.confirm(`Delete the briefing for "${row.condition_label}"? This cannot be undone.`)) return;
    setActionError(null);
    try {
      await api.deleteBriefing(row.id);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 border-b border-line px-4 py-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="filter-user" className="text-xs font-medium text-muted">
            Created by
          </label>
          <select
            id="filter-user"
            value={createdBy}
            onChange={(e) => setCreatedBy(e.target.value)}
            className="rounded-md border border-line-strong bg-surface px-2 py-1 text-sm"
          >
            <option value="">All users</option>
            {(users ?? []).map((u) => (
              <option key={u.id} value={u.id}>
                {u.name} ({u.id})
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="filter-status" className="text-xs font-medium text-muted">
            Status
          </label>
          <select
            id="filter-status"
            value={status}
            onChange={(e) => setStatus(e.target.value as BriefingStatus | "")}
            className="rounded-md border border-line-strong bg-surface px-2 py-1 text-sm"
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </div>
        <Button variant="ghost" onClick={reload} className="ml-auto" aria-label="Refresh list">
          <RefreshCw aria-hidden="true" className="size-4" />
          Refresh
        </Button>
      </div>

      {actionError ? (
        <Callout tone="danger" role="alert" className="m-4" icon={<AlertTriangle className="size-4" aria-hidden="true" />}>
          {actionError}
        </Callout>
      ) : null}

      {loading && !rows ? (
        <div className="px-4 py-10">
          <Spinner label="Loading briefings" />
        </div>
      ) : error ? (
        <Callout tone="danger" role="alert" className="m-4" title="Could not load briefings">
          {error}{" "}
          <button type="button" onClick={reload} className="font-medium text-accent underline">
            Try again
          </button>
        </Callout>
      ) : rows && rows.length === 0 ? (
        <div className="flex flex-col items-center gap-3 px-4 py-12 text-center">
          <p className="text-sm text-muted">
            {createdBy || status ? "No briefings match these filters." : "No briefings yet."}
          </p>
          <ButtonLink href="/briefings/new" variant="primary">
            <Plus aria-hidden="true" className="size-4" />
            New briefing
          </ButtonLink>
        </div>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[880px] text-left text-sm">
            <caption className="sr-only">Briefings, newest first</caption>
            <thead className="bg-subtle text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-4 py-2 font-semibold">Condition</th>
                <th scope="col" className="px-3 py-2 font-semibold">Region</th>
                <th scope="col" className="px-3 py-2 font-semibold">Status</th>
                <th scope="col" className="px-3 py-2 font-semibold">Created by</th>
                <th scope="col" className="px-3 py-2 font-semibold">Created</th>
                <th scope="col" className="px-3 py-2 font-semibold">
                  Evidence snapshot
                  <span className="block font-normal normal-case tracking-normal">when sources were retrieved</span>
                </th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Selected / found</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Conflicts</th>
                <th scope="col" className="px-4 py-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(rows ?? []).map((r) => (
                <tr key={r.id} className="hover:bg-subtle/60">
                  <td className="px-4 py-2.5">
                    <Link href={`/briefings/${r.id}`} className="font-medium text-accent hover:underline">
                      {r.condition_label}
                    </Link>
                    <div className="font-mono text-xs text-muted">{r.id}</div>
                  </td>
                  <td className="px-3 py-2.5">{r.region}</td>
                  <td className="px-3 py-2.5">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-3 py-2.5">{r.created_by}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-ink-2">{formatDateTime(r.created_at)}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-ink-2">
                    {r.research_conducted_at ? (
                      <>
                        {formatDateTime(r.research_conducted_at)}
                        {r.data_mode === "replay" ? <span className="block text-xs text-muted">recorded (replay)</span> : null}
                      </>
                    ) : (
                      <span className="text-muted">-</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {r.option_count === 0 ? "-" : `${r.selected_option_count} / ${r.option_count}`}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {r.conflict_count === 0 ? (
                      "-"
                    ) : r.open_conflict_count > 0 ? (
                      <span className="font-medium text-warn">{r.open_conflict_count} open</span>
                    ) : (
                      `${r.conflict_count} resolved`
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {canManage(me, r) ? (
                      <Button
                        variant="ghost"
                        onClick={() => void onDelete(r)}
                        aria-label={`Delete briefing ${r.condition_label} (${r.id})`}
                        title="Delete"
                        className="px-2"
                      >
                        <Trash2 aria-hidden="true" className="size-4" />
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
