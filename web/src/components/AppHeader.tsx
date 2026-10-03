"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback } from "react";
import { FileText, Plus, ShieldCheck, UserRound } from "lucide-react";
import { api, API_MODE } from "@/lib/api";
import { setCurrentUserId, useCurrentUserId } from "@/lib/current-user";
import { useAsync } from "@/hooks/use-async";
import { Badge, cx } from "./ui";

function ModeBadge() {
  const load = useCallback(() => api.health(), []);
  const { data } = useAsync(load);
  if (API_MODE === "mock") {
    return (
      <Badge tone="warn" title="NEXT_PUBLIC_API_MODE=mock: data comes from src/mocks, no backend is called">
        Mock data
      </Badge>
    );
  }
  if (!data) return null;
  const provider = data.llm_provider === "gemini_api" ? "Gemini API" : data.llm_provider === "vertex" ? "Vertex AI" : "Replay";
  return (
    <Badge
      tone={data.data_mode === "live" ? "ok" : "neutral"}
      title={`LLM provider: ${provider} (${data.model}, lite: ${data.model_lite}); data: ${data.data_mode}`}
    >
      {data.llm_provider === "replay" && data.data_mode === "replay"
        ? "Replay mode (recorded LLM + sources)"
        : `${provider} · ${data.data_mode === "live" ? "live sources" : "recorded sources"}`}
    </Badge>
  );
}

function UserSwitcher() {
  const userId = useCurrentUserId();
  const load = useCallback(() => api.listUsers(), []);
  const { data: users } = useAsync(load);
  const current = users?.find((u) => u.id === userId);
  const options = users ?? [{ id: userId, name: userId, email: "", role: "admin" as const }];
  return (
    <div className="flex items-center gap-2">
      {current?.role === "admin" ? (
        <Badge tone="accent" title="Admin: can review and delete any briefing">
          <ShieldCheck aria-hidden="true" className="size-3.5" />
          Admin
        </Badge>
      ) : current ? (
        <Badge tone="neutral" title="Analyst: can review and delete own briefings only">
          <UserRound aria-hidden="true" className="size-3.5" />
          Analyst
        </Badge>
      ) : null}
      <label htmlFor="acting-user" className="sr-only">
        Acting user (no sign-in in this demo)
      </label>
      <select
        id="acting-user"
        value={userId}
        onChange={(e) => setCurrentUserId(e.target.value)}
        className="rounded-md border border-line-strong bg-surface px-2 py-1 text-sm text-ink"
        title="Acting user (sent as X-User-Id; no sign-in in this demo)"
      >
        {options.map((u) => (
          <option key={u.id} value={u.id}>
            {u.name} ({u.id})
          </option>
        ))}
      </select>
    </div>
  );
}

const NAV = [
  { href: "/", label: "Briefings", icon: FileText },
  { href: "/briefings/new", label: "New briefing", icon: Plus },
];

export function AppHeader() {
  const pathname = usePathname();
  return (
    <header className="no-print border-b border-line bg-surface">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5 sm:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold text-ink">
          <span aria-hidden="true" className="grid size-7 place-items-center rounded bg-ink text-xs font-bold text-white">
            HB
          </span>
          Health Briefing
          <span className="text-xs font-normal text-muted">POC</span>
        </Link>
        <nav aria-label="Main" className="flex items-center gap-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm",
                  active ? "bg-subtle font-medium text-ink" : "text-ink-2 hover:bg-subtle",
                )}
              >
                <Icon aria-hidden="true" className="size-4" />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <ModeBadge />
          <UserSwitcher />
        </div>
      </div>
    </header>
  );
}
