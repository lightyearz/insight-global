/**
 * Typed data layer. Two adapters, picked at build time by NEXT_PUBLIC_API_MODE:
 * - "api" (default): relative /api/* calls (proxied to FastAPI by next.config rewrites), SSE via EventSource.
 * - "mock": in-browser store seeded from src/mocks/*.json that simulates the agent and the event stream.
 */
import { getCurrentUserId } from "./current-user";
import type {
  ApiError as ApiErrorBody,
  Briefing,
  BriefingStatus,
  BriefingSummary,
  ConditionSuggestion,
  CreateBriefingRequest,
  HealthResponse,
  JobEvent,
  ReplayManifest,
  ReviewSubmission,
  User,
} from "./types";

export type ApiMode = "api" | "mock";
export const API_MODE: ApiMode = process.env.NEXT_PUBLIC_API_MODE === "mock" ? "mock" : "api";

export interface BriefingFilters {
  created_by?: string;
  status?: BriefingStatus;
}

export type StreamEnd = "done" | "error";

export interface EventSubscription {
  /** Only events with seq > afterSeq are delivered. */
  afterSeq: number;
  onEvent: (event: JobEvent) => void;
  /** "done": the stream reached a terminal event. "error": connection lost (the caller should refetch). */
  onEnd: (reason: StreamEnd) => void;
}

export interface BriefingApi {
  health(): Promise<HealthResponse>;
  listUsers(): Promise<User[]>;
  suggestConditions(q: string, signal?: AbortSignal): Promise<ConditionSuggestion[]>;
  listReplayConditions(): Promise<ReplayManifest[]>;
  listBriefings(filters?: BriefingFilters): Promise<BriefingSummary[]>;
  getBriefing(id: string): Promise<Briefing>;
  createBriefing(req: CreateBriefingRequest): Promise<Briefing>;
  submitReview(id: string, submission: ReviewSubmission): Promise<Briefing>;
  /** Resume a failed run from its last checkpoint. */
  retryBriefing(id: string): Promise<Briefing>;
  deleteBriefing(id: string): Promise<void>;
  /** Returns an unsubscribe function. */
  subscribeEvents(id: string, sub: EventSubscription): () => void;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** True for the event that ends a stream (contract section 5). */
export function isTerminalEvent(e: JobEvent): boolean {
  return (
    e.status === "awaiting_review" || e.status === "failed" || (e.step === "run" && e.status === "completed")
  );
}

export function isRunning(status: BriefingStatus): boolean {
  return status === "researching" || status === "generating_report";
}

// ---------------------------------------------------------------------------
// HTTP adapter
// ---------------------------------------------------------------------------

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as ApiErrorBody).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => `${d.loc.filter((p) => p !== "body").join(".")}: ${d.msg}`).join("; ");
    }
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("X-User-Id", getCurrentUserId());
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, headers, cache: "no-store" });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "The API is unreachable. Check that the backend is running.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, `Request failed (HTTP ${res.status})`));
  return body as T;
}

function query(params: Record<string, string | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) qs.set(k, v);
  const s = qs.toString();
  return s ? `?${s}` : "";
}

const httpApi: BriefingApi = {
  health: () => request<HealthResponse>("/health"),
  listUsers: () => request<User[]>("/users"),
  suggestConditions: (q, signal) => request<ConditionSuggestion[]>(`/conditions/suggest${query({ q })}`, { signal }),
  listReplayConditions: () => request<ReplayManifest[]>("/replay/conditions"),
  listBriefings: (filters = {}) => request<BriefingSummary[]>(`/briefings${query({ ...filters })}`),
  getBriefing: (id) => request<Briefing>(`/briefings/${encodeURIComponent(id)}`),
  createBriefing: (req) => request<Briefing>("/briefings", { method: "POST", body: JSON.stringify(req) }),
  submitReview: (id, submission) =>
    request<Briefing>(`/briefings/${encodeURIComponent(id)}/review`, {
      method: "POST",
      body: JSON.stringify(submission),
    }),
  retryBriefing: (id) => request<Briefing>(`/briefings/${encodeURIComponent(id)}/retry`, { method: "POST" }),
  deleteBriefing: (id) => request<void>(`/briefings/${encodeURIComponent(id)}`, { method: "DELETE" }),
  subscribeEvents(id, { afterSeq, onEvent, onEnd }) {
    const source = new EventSource(`/api/briefings/${encodeURIComponent(id)}/events?after_seq=${afterSeq}`);
    let lastSeq = afterSeq;
    let closed = false;
    const close = (reason?: StreamEnd) => {
      if (closed) return;
      closed = true;
      source.close();
      if (reason) onEnd(reason);
    };
    source.onmessage = (msg: MessageEvent<string>) => {
      let event: JobEvent;
      try {
        event = JSON.parse(msg.data) as JobEvent;
      } catch {
        return;
      }
      if (event.seq <= lastSeq) return;
      lastSeq = event.seq;
      onEvent(event);
      // The server closes the stream after a terminal event; close first so
      // EventSource does not reconnect.
      if (isTerminalEvent(event)) close("done");
    };
    source.onerror = () => {
      // The server also closes when the briefing was already terminal before
      // any new event; let the caller refetch and decide.
      close("error");
    };
    return () => close();
  },
};

// ---------------------------------------------------------------------------
// Mock adapter (lazy-loaded so the fixtures never ship in "api" builds)
// ---------------------------------------------------------------------------

let mockApiPromise: Promise<BriefingApi> | null = null;

function loadMock(): Promise<BriefingApi> {
  mockApiPromise ??= import("./mock/mock-api").then((m) => m.createMockApi());
  return mockApiPromise;
}

const lazyMockApi: BriefingApi = {
  health: () => loadMock().then((m) => m.health()),
  listUsers: () => loadMock().then((m) => m.listUsers()),
  suggestConditions: (q, signal) => loadMock().then((m) => m.suggestConditions(q, signal)),
  listReplayConditions: () => loadMock().then((m) => m.listReplayConditions()),
  listBriefings: (filters) => loadMock().then((m) => m.listBriefings(filters)),
  getBriefing: (id) => loadMock().then((m) => m.getBriefing(id)),
  createBriefing: (req) => loadMock().then((m) => m.createBriefing(req)),
  submitReview: (id, s) => loadMock().then((m) => m.submitReview(id, s)),
  retryBriefing: (id) => loadMock().then((m) => m.retryBriefing(id)),
  deleteBriefing: (id) => loadMock().then((m) => m.deleteBriefing(id)),
  subscribeEvents(id, sub) {
    let unsubscribe: (() => void) | null = null;
    let cancelled = false;
    void loadMock().then((m) => {
      if (!cancelled) unsubscribe = m.subscribeEvents(id, sub);
    });
    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  },
};

export const api: BriefingApi = API_MODE === "mock" ? lazyMockApi : httpApi;
