/**
 * Mock adapter: an in-browser stand-in for the FastAPI service. It emulates
 * replay mode (one recorded condition), the agent's event stream, the review
 * checks of docs/CONTRACT.md section 4 and the report assembly. State lives in
 * sessionStorage so it survives client navigation and reloads within a tab.
 */
import awaitingSeed from "@/mocks/briefing-awaiting-review.json";
import completedSeed from "@/mocks/briefing-completed.json";
import failedSeed from "@/mocks/briefing-failed.json";
import lookups from "@/mocks/lookups.json";
import { ApiError, isTerminalEvent, type BriefingApi, type EventSubscription } from "../api";
import { getCurrentUserId } from "../current-user";
import {
  CONTRACT_VERSION,
  NODE_ORDER,
  type AgentStep,
  type AuditEntry,
  type Briefing,
  type BriefingSummary,
  type ConditionSuggestion,
  type JobEvent,
  type JobEventStatus,
  type JobStep,
  type NodeName,
  type ReplayManifest,
  type Report,
  type User,
} from "../types";
import { researchConductedAt } from "../format";
import { assembleReport } from "./assemble";

const STORAGE_KEY = "health-briefing.mock-store.v3";
const TEMPLATE = awaitingSeed as unknown as Briefing;
const REPORT_TEMPLATE = (completedSeed as unknown as Briefing).report as Report;
const USERS = lookups.users as User[];
const MANIFESTS = lookups.replay_conditions as ReplayManifest[];

interface MockState {
  briefings: Record<string, Briefing>;
  events: Record<string, JobEvent[]>;
}

const clone = <T,>(v: T): T => structuredClone(v);
const now = () => new Date().toISOString();
const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function normalise(s: string): string {
  return s.trim().replace(/\s+/g, " ").toLowerCase();
}

function newId(): string {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return `brf_${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

/** Same rule as the API's write_report under the replay provider: flag a review that departed from the AI path. */
function replayDeviationNote(b: Briefing): string[] {
  const options = b.treatment_options.filter((o) => o.selected !== o.suggested).length;
  const conflicts = b.conflicts.filter((c) => {
    const r = c.resolution;
    const s = c.suggested_resolution;
    return !r || r.decision !== s.decision || (r.accepted_source_id ?? null) !== (s.accepted_source_id ?? null);
  }).length;
  if (!options && !conflicts) return [];
  return [
    "Replay note: this narrative was recorded for the AI-suggested selection and conflict resolutions. " +
      `The reviewer changed ${options} option selection(s) and ${conflicts} conflict decision(s), ` +
      "so the treatment options table and conflict log below, not this text, reflect the review.",
  ];
}

function seedEvents(b: Briefing): JobEvent[] {
  const out: JobEvent[] = [];
  const push = (ts: string | null, step: JobStep, status: JobEventStatus, message: string) =>
    out.push({ briefing_id: b.id, seq: out.length + 1, ts: ts ?? b.created_at, step, status, message, data: null });
  push(b.created_at, "run", "started", "Run started");
  for (const s of b.run.steps) {
    if (s.status === "pending") continue;
    push(s.started_at, s.name, "started", `${s.name} started`);
    if (s.name === "human_review") {
      push(s.started_at, s.name, "awaiting_review", "Waiting for human review");
      if (s.status === "completed") push(s.ended_at, s.name, "completed", `Review submitted by ${b.reviewed_by ?? "admin"}`);
      continue;
    }
    if (s.status === "completed" || s.status === "failed") push(s.ended_at, s.name, s.status, s.detail ?? s.name);
  }
  if (b.status === "completed") push(b.updated_at, "run", "completed", "Report generated");
  if (b.status === "failed") push(b.updated_at, "run", "failed", b.error ?? "Run failed");
  return out;
}

function seedState(): MockState {
  const seeds = [completedSeed, awaitingSeed, failedSeed] as unknown as Briefing[];
  const state: MockState = { briefings: {}, events: {} };
  for (const b of seeds) {
    state.briefings[b.id] = clone(b);
    state.events[b.id] = seedEvents(b);
  }
  return state;
}

function loadState(): MockState {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      const state = JSON.parse(raw) as MockState;
      // Same rule as the API's startup recovery: unfinished runs cannot resume.
      for (const b of Object.values(state.briefings)) {
        if (b.status === "researching" || b.status === "generating_report") {
          b.status = "failed";
          b.error = "Interrupted by page reload (mock mode)";
          b.run.steps = b.run.steps.map((s) => (s.status === "running" ? { ...s, status: "failed" } : s));
        }
      }
      return state;
    }
  } catch {
    // Fall through to the seed data.
  }
  return seedState();
}

export function createMockApi(): BriefingApi {
  const state = loadState();
  const listeners = new Map<string, Set<(e: JobEvent) => void>>();

  const persist = () => {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // Storage full or unavailable: keep the in-memory state.
    }
  };
  persist();

  const get = (id: string): Briefing => {
    const b = state.briefings[id];
    if (!b) throw new ApiError(404, `Briefing '${id}' not found`);
    return b;
  };

  const actingUser = (): User => {
    const id = getCurrentUserId();
    const user = USERS.find((u) => u.id === id);
    if (!user) throw new ApiError(401, `Unknown user '${id}'`);
    return user;
  };

  const emit = (id: string, step: JobStep, status: JobEventStatus, message: string, data: JobEvent["data"] = null) => {
    const list = (state.events[id] ??= []);
    const event: JobEvent = { briefing_id: id, seq: list.length + 1, ts: now(), step, status, message, data };
    list.push(event);
    const b = state.briefings[id];
    if (b) b.updated_at = event.ts;
    persist();
    listeners.get(id)?.forEach((fn) => fn(clone(event)));
  };

  const setStep = (b: Briefing, name: NodeName, patch: Partial<AgentStep>) => {
    b.run.steps = b.run.steps.map((s) => (s.name === name ? { ...s, ...patch } : s));
  };

  /** Runs one node: started -> body -> completed, unless the briefing was deleted. */
  const node = async (
    id: string,
    name: NodeName,
    body: (b: Briefing) => Promise<{ detail: string; data: JobEvent["data"] }>,
  ): Promise<boolean> => {
    let b = state.briefings[id];
    if (!b) return false;
    setStep(b, name, { status: "running", started_at: now() });
    emit(id, name, "started", `${name} started`);
    const { detail, data } = await body(b);
    b = state.briefings[id];
    if (!b) return false;
    setStep(b, name, { status: "completed", ended_at: now(), detail });
    emit(id, name, "completed", detail, data);
    return true;
  };

  const simulateResearch = async (id: string) => {
    const t = TEMPLATE;
    const steps: [NodeName, (b: Briefing) => Promise<{ detail: string; data: JobEvent["data"] }>][] = [
      [
        "normalize_condition",
        async (b) => {
          b.research_started_at = b.research_started_at ?? now();
          await sleep(500);
          b.condition = { ...t.condition, input: b.condition.input };
          return {
            detail: `${t.condition.label} (MeSH ${t.condition.mesh_id ?? "n/a"})`,
            data: { label: t.condition.label, mesh_id: t.condition.mesh_id },
          };
        },
      ],
      [
        "retrieve_sources",
        async (b) => {
          await sleep(500);
          const pubmed = t.sources.filter((s) => s.connector === "pubmed").length;
          emit(id, "retrieve_sources", "progress", `PubMed: ${pubmed} records`, { connector: "pubmed", count: pubmed });
          await sleep(400);
          const mp = t.sources.length - pubmed;
          emit(id, "retrieve_sources", "progress", `MedlinePlus: ${mp} topic`, { connector: "medlineplus", count: mp });
          const fetched = now();
          b.sources = t.sources.map((s) => ({ ...s, retrieved_at: fetched }));
          b.search_strategy = t.search_strategy;
          return {
            detail: `${b.sources.length} sources (${pubmed} PubMed, ${mp} MedlinePlus)`,
            data: { count: b.sources.length },
          };
        },
      ],
      [
        "extract_treatments",
        async (b) => {
          let mentions = 0;
          for (const s of b.sources) {
            await sleep(180);
            const n = t.treatment_options.filter((o) => o.evidence.some((e) => e.source_id === s.id)).length;
            mentions += n;
            emit(id, "extract_treatments", "progress", `${s.id}: ${n} treatments`, { source_id: s.id, treatments: n });
          }
          return { detail: `${b.sources.length} of ${b.sources.length} sources processed, ${mentions} treatment mentions`, data: null };
        },
      ],
      [
        "consolidate_options",
        async (b) => {
          await sleep(700);
          b.treatment_options = t.treatment_options.map((o) => ({ ...o, suggested: false, suggestion_reason: "", selected: false }));
          return { detail: `${b.treatment_options.length} treatment options`, data: { options: b.treatment_options.length } };
        },
      ],
      [
        "detect_conflicts",
        async (b) => {
          await sleep(600);
          b.conflicts = clone(t.conflicts);
          return { detail: `${b.conflicts.length} conflicts`, data: { conflicts: b.conflicts.length } };
        },
      ],
      [
        "suggest_relevance",
        async (b) => {
          await sleep(500);
          b.treatment_options = clone(t.treatment_options).map((o) => ({ ...o, selected: o.suggested }));
          const n = b.treatment_options.filter((o) => o.suggested).length;
          b.research_completed_at = now();
          return { detail: `${n} of ${b.treatment_options.length} options suggested`, data: { suggested: n } };
        },
      ],
    ];
    for (const [name, body] of steps) {
      if (!(await node(id, name, body))) return;
    }
    const b = state.briefings[id];
    if (!b) return;
    b.status = "awaiting_review";
    setStep(b, "human_review", { status: "running", started_at: now(), detail: "Awaiting human review" });
    emit(id, "human_review", "started", "human_review started");
    emit(id, "human_review", "awaiting_review", "Waiting for human review");
  };

  const simulateReport = async (id: string) => {
    const ok = await node(id, "write_report", async (b) => {
      await sleep(1200);
      const generatedAt = now();
      const entry: AuditEntry = {
        at: generatedAt,
        actor: "system",
        action: "report_generated",
        target_id: null,
        detail: "Report generated (replay)",
      };
      b.audit_log = [...b.audit_log, entry];
      b.report = assembleReport(
        b,
        {
          title: REPORT_TEMPLATE.title,
          top_level_description: REPORT_TEMPLATE.top_level_description,
          key_takeaways: [
            ...replayDeviationNote(b),
            ...REPORT_TEMPLATE.key_takeaways.filter((t) => !t.startsWith("Replay note:")),
          ],
        },
        generatedAt,
        "replay",
      );
      b.status = "completed";
      return { detail: "Report generated", data: null };
    });
    if (ok) emit(id, "run", "completed", "Report generated");
  };

  const summary = (b: Briefing): BriefingSummary => ({
    id: b.id,
    condition_label: b.condition.label,
    region: b.region,
    status: b.status,
    created_by: b.created_by,
    created_at: b.created_at,
    updated_at: b.updated_at,
    source_count: b.sources.length,
    research_conducted_at: researchConductedAt(b.sources),
    data_mode: b.run.data_mode,
    option_count: b.treatment_options.length,
    selected_option_count: b.treatment_options.filter((o) => o.selected).length,
    conflict_count: b.conflicts.length,
    open_conflict_count: b.conflicts.filter((c) => c.resolution === null).length,
    has_report: b.report !== null,
  });

  const api: BriefingApi = {
    async health() {
      return {
        status: "ok",
        contract_version: CONTRACT_VERSION,
        llm_provider: "replay",
        data_mode: "replay",
        model: "replay",
        model_lite: "replay",
        time: now(),
      };
    },
    async listUsers() {
      return clone(USERS);
    },
    async suggestConditions(q) {
      const term = normalise(q);
      if (term.length < 2) return [];
      const out: ConditionSuggestion[] = [];
      for (const m of MANIFESTS) {
        if ([m.label, m.slug, ...m.aliases].some((v) => normalise(v).includes(term))) {
          out.push({ label: m.label, code: null, source: "replay" });
        }
      }
      return out.slice(0, 10);
    },
    async listReplayConditions() {
      return clone(MANIFESTS).sort((a, b) => a.label.localeCompare(b.label));
    },
    async listBriefings(filters = {}) {
      actingUser();
      return Object.values(state.briefings)
        .filter((b) => !filters.created_by || b.created_by === filters.created_by)
        .filter((b) => !filters.status || b.status === filters.status)
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
        .map(summary);
    },
    async getBriefing(id) {
      return clone(get(id));
    },
    async createBriefing(req) {
      const user = actingUser();
      const input = req.condition.trim();
      if (input.length < 2 || input.length > 200) throw new ApiError(422, "condition: must be 2-200 characters");
      const term = normalise(input);
      const manifest = MANIFESTS.find((m) => [m.slug, m.label, ...m.aliases].some((v) => normalise(v) === term));
      if (!manifest) {
        throw new ApiError(
          400,
          `No replay fixture for '${input}'. Available conditions: ${MANIFESTS.map((m) => m.label).join(", ")}`,
        );
      }
      const created = now();
      const region = req.region ?? "US";
      const b: Briefing = {
        id: newId(),
        condition: { input, label: input, mesh_id: null, synonyms: [] },
        region,
        status: "researching",
        created_by: user.id,
        created_at: created,
        updated_at: created,
        research_started_at: null,
        research_completed_at: null,
        reviewed_by: null,
        reviewed_at: null,
        sources: [],
        search_strategy: null,
        treatment_options: [],
        conflicts: [],
        audit_log: [
          {
            at: created,
            actor: user.id,
            action: "briefing_created",
            target_id: null,
            detail: `Briefing created for '${input}' (${region})`,
          },
        ],
        report: null,
        run: {
          llm_provider: "replay",
          data_mode: "replay",
          model: "replay",
          model_lite: "replay",
          tokens_in: 0,
          tokens_out: 0,
          est_cost_usd: 0,
          model_versions: [],
          steps: NODE_ORDER.map((name) => ({ name, status: "pending", started_at: null, ended_at: null, detail: null })),
        },
        error: null,
      };
      state.briefings[b.id] = b;
      state.events[b.id] = [];
      emit(b.id, "run", "started", "Run started");
      void simulateResearch(b.id);
      return clone(b);
    },
    async submitReview(id, submission) {
      const b = get(id);
      const user = actingUser();
      if (user.role !== "admin" && b.created_by !== user.id) {
        throw new ApiError(403, "Only the creator or an admin can review this briefing");
      }
      if (b.status !== "awaiting_review") throw new ApiError(409, `Briefing is '${b.status}', not awaiting review`);
      if (submission.selected_option_ids.length === 0) throw new ApiError(400, "Select at least one treatment option");
      const optionIds = new Set(b.treatment_options.map((o) => o.id));
      const unknown = submission.selected_option_ids.find((o) => !optionIds.has(o));
      if (unknown) throw new ApiError(400, `Unknown option id '${unknown}'`);
      const byId = new Map(submission.conflict_resolutions.map((r) => [r.conflict_id, r]));
      if (byId.size !== submission.conflict_resolutions.length) throw new ApiError(400, "Duplicate conflict resolution");
      for (const r of submission.conflict_resolutions) {
        const c = b.conflicts.find((x) => x.id === r.conflict_id);
        if (!c) throw new ApiError(400, `Unknown conflict id '${r.conflict_id}'`);
        if (r.decision === "accept_source" && !c.positions.some((p) => p.source_id === r.accepted_source_id)) {
          throw new ApiError(400, `accepted_source_id is not a position of '${c.id}'`);
        }
        if (r.decision === "custom" && !(r.note ?? "").trim()) throw new ApiError(400, "A custom resolution needs a note");
        const sugg = c.suggested_resolution;
        const overrides =
          r.decision !== sugg.decision || (r.decision === "accept_source" && r.accepted_source_id !== sugg.accepted_source_id);
        if (overrides && !(r.note ?? "").trim()) {
          throw new ApiError(400, `A note is required when overriding the AI suggestion (${c.id})`);
        }
      }
      const missing = b.conflicts.find((c) => !byId.has(c.id));
      if (missing) throw new ApiError(400, `Conflict '${missing.id}' has no resolution`);

      const at = now();
      const selected = new Set(submission.selected_option_ids);
      b.treatment_options = b.treatment_options.map((o) => ({ ...o, selected: selected.has(o.id) }));
      b.conflicts = b.conflicts.map((c) => {
        const r = byId.get(c.id);
        return r
          ? {
              ...c,
              resolution: {
                decision: r.decision,
                accepted_source_id: r.decision === "accept_source" ? (r.accepted_source_id ?? null) : null,
                note: r.note ?? "",
                resolved_by: user.id,
                resolved_at: at,
              },
            }
          : c;
      });
      b.reviewed_by = user.id;
      b.reviewed_at = at;
      b.status = "generating_report";
      const audit: AuditEntry[] = [
        {
          at,
          actor: user.id,
          action: "review_submitted",
          target_id: null,
          detail: `${selected.size} of ${b.treatment_options.length} options selected; ${b.conflicts.length} conflicts resolved`,
        },
        ...b.treatment_options.map<AuditEntry>((o) => ({
          at,
          actor: user.id,
          action: o.selected ? "option_selected" : "option_excluded",
          target_id: o.id,
          detail: `${o.selected ? "Selected" : "Excluded"} '${o.name}' (AI: ${o.suggested ? "suggested" : "not suggested"})`,
        })),
        ...b.conflicts.map<AuditEntry>((c) => {
          const r = c.resolution;
          const followed = r?.decision === c.suggested_resolution.decision &&
            r.accepted_source_id === c.suggested_resolution.accepted_source_id;
          return {
            at,
            actor: user.id,
            action: "conflict_resolved",
            target_id: c.id,
            detail: `${r?.decision ?? "?"}${r?.accepted_source_id ? ` (${r.accepted_source_id})` : ""}; AI suggested ${c.suggested_resolution.decision} (${followed ? "followed" : "overridden"})`,
          };
        }),
      ];
      b.audit_log = [...b.audit_log, ...audit];
      setStep(b, "human_review", { status: "completed", ended_at: at, detail: `Reviewed by ${user.id}` });
      emit(id, "human_review", "completed", `Review submitted by ${user.id}`);
      void simulateReport(id);
      return clone(b);
    },
    async retryBriefing() {
      throw new ApiError(409, "Retry is only available with the real API (mock mode has no checkpoints)");
    },
    async deleteBriefing(id) {
      const b = get(id);
      const user = actingUser();
      if (user.role !== "admin" && b.created_by !== user.id) {
        throw new ApiError(403, "Only the creator or an admin can delete this briefing");
      }
      delete state.briefings[id];
      delete state.events[id];
      persist();
    },
    subscribeEvents(id: string, { afterSeq, onEvent, onEnd }: EventSubscription) {
      let active = true;
      const listener = (e: JobEvent) => {
        if (!active || e.seq <= afterSeq) return;
        onEvent(e);
        if (isTerminalEvent(e)) stop("done");
      };
      const stop = (reason?: "done" | "error") => {
        if (!active) return;
        active = false;
        listeners.get(id)?.delete(listener);
        if (reason) onEnd(reason);
      };
      queueMicrotask(() => {
        if (!active) return;
        const b = state.briefings[id];
        if (!b) return stop("error");
        for (const e of state.events[id] ?? []) if (e.seq > afterSeq) onEvent(clone(e));
        if (b.status === "awaiting_review" || b.status === "completed" || b.status === "failed") return stop("done");
        if (!listeners.has(id)) listeners.set(id, new Set());
        listeners.get(id)?.add(listener);
      });
      return () => stop();
    },
  };
  return api;
}
