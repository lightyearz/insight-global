"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, isRunning } from "@/lib/api";
import type { Briefing, JobEvent } from "@/lib/types";

export interface BriefingState {
  briefing: Briefing | null;
  events: JobEvent[];
  error: string | null;
  notFound: boolean;
  /** True while an SSE stream is open. */
  streaming: boolean;
  refresh: () => Promise<Briefing | null>;
  /** Replace the local copy (e.g. with the 202 response of POST /review). */
  replace: (b: Briefing) => void;
}

/**
 * Loads a briefing and follows its event stream while the agent is running.
 * The stream history (seq > 0) is also read once for finished briefings so
 * the research log can be shown.
 */
export function useBriefing(id: string): BriefingState {
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [historyRead, setHistoryRead] = useState(false);
  const [streamNonce, setStreamNonce] = useState(0);
  const lastSeq = useRef(0);

  const refresh = useCallback(async (): Promise<Briefing | null> => {
    try {
      const b = await api.getBriefing(id);
      setBriefing(b);
      setError(null);
      return b;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setNotFound(true);
      else setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    api.getBriefing(id).then(
      (b) => {
        if (!cancelled) setBriefing(b);
      },
      (err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) setNotFound(true);
        else setError(err instanceof Error ? err.message : String(err));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [id]);

  const running = briefing ? isRunning(briefing.status) : false;
  const wantStream = briefing !== null && (running || !historyRead);

  useEffect(() => {
    if (!wantStream) return;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let active = true;
    const unsubscribe = api.subscribeEvents(id, {
      afterSeq: lastSeq.current,
      onEvent: (e) => {
        if (!active) return;
        lastSeq.current = Math.max(lastSeq.current, e.seq);
        setStreaming(true);
        setEvents((prev) => (prev.some((p) => p.seq === e.seq) ? prev : [...prev, e]));
        if (e.status !== "progress") void refresh();
      },
      onEnd: (reason) => {
        if (!active) return;
        setStreaming(false);
        retry = setTimeout(
          () => {
            void refresh().then((b) => {
              if (!active) return;
              setHistoryRead(true);
              // Still running (lost connection, or a terminal event from history): reconnect.
              if (b && isRunning(b.status)) setStreamNonce((n) => n + 1);
            });
          },
          reason === "error" ? 1500 : 0,
        );
      },
    });
    return () => {
      active = false;
      if (retry) clearTimeout(retry);
      unsubscribe();
    };
  }, [id, wantStream, streamNonce, refresh]);

  const replace = useCallback((b: Briefing) => setBriefing(b), []);

  return { briefing, events, error, notFound, streaming, refresh, replace };
}
