import { formatPartialDate, keyed, partialDateToYear, sourceShortName } from "@/lib/format";
import { TIMELINE_KIND_LABEL } from "@/lib/labels";
import type { ReliabilityTier, Source, TimelineEvent, TimelineKind } from "@/lib/types";
import { TIER_DOT, TIER_NAME } from "./badges";
import { cx } from "./ui";

interface Props {
  events: TimelineEvent[];
  sources: ReadonlyMap<string, Source>;
  /** Source id -> citation number in the report's sources appendix. */
  citation: ReadonlyMap<string, number>;
}

/** Years shown on the chart before the research date; anything older goes into an "Earlier" bucket. */
const WINDOW_YEARS = 6;
const ROW_HEIGHT = 26;
const LANE_PAD = 8;
const AXIS_HEIGHT = 26;
/** Rough label width in % of the plot (the chart only renders at md+ widths, ~700-1100 px). */
const CHAR_PCT = 0.72;
const GAP_PCT = 1.2;

type LaneKind = Exclude<TimelineKind, "research_conducted">;

const LANES: { kind: LaneKind; label: string }[] = [
  { kind: "guideline_published", label: "Guidelines" },
  { kind: "evidence_published", label: "Evidence" },
  { kind: "treatment_milestone", label: "Milestones" },
];

const TIER_BORDER: Record<ReliabilityTier, string> = {
  1: "border-tier-1",
  2: "border-tier-2",
  3: "border-tier-3",
  4: "border-tier-4",
};

function tierOf(e: TimelineEvent, sources: ReadonlyMap<string, Source>): ReliabilityTier | null {
  const id = e.source_ids[0];
  return id ? (sources.get(id)?.reliability_tier ?? null) : null;
}

function precisionNote(e: TimelineEvent): string {
  return e.date_precision === "year" ? " (year only)" : e.date_precision === "month" ? " (month only)" : "";
}

function shortLabel(e: TimelineEvent, sources: ReadonlyMap<string, Source>): string {
  if (e.short_label) return e.short_label;
  const s = e.source_ids[0] ? sources.get(e.source_ids[0]) : undefined;
  return s ? `${sourceShortName(s, 14)} ${e.date.slice(0, 4)}` : e.date.slice(0, 4);
}

/** The marker glyph: shape encodes the kind, colour encodes the reliability tier. */
function Glyph({ kind, tier, className }: { kind: TimelineKind; tier: ReliabilityTier | null; className?: string }) {
  const fill = tier ? TIER_DOT[tier] : "bg-ink-2";
  if (kind === "guideline_published") {
    return <span aria-hidden="true" className={cx("block size-3 rotate-45 rounded-[2px] ring-2 ring-surface", fill, className)} />;
  }
  if (kind === "evidence_published") {
    return <span aria-hidden="true" className={cx("block size-3.5 rounded-full ring-2 ring-surface", fill, className)} />;
  }
  if (kind === "treatment_milestone") {
    return (
      <span
        aria-hidden="true"
        className={cx("block size-3 rounded-[2px] border-[2.5px] bg-surface", tier ? TIER_BORDER[tier] : "border-ink-2", className)}
      />
    );
  }
  return <span aria-hidden="true" className={cx("block h-3.5 w-1 rounded-sm bg-research", className)} />;
}

function SourceRefs({ e, sources, citation }: { e: TimelineEvent; sources: ReadonlyMap<string, Source>; citation: ReadonlyMap<string, number> }) {
  if (e.source_ids.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-x-2">
      {e.source_ids.map((id) => {
        const s = sources.get(id);
        const n = citation.get(id);
        return (
          <span key={id}>
            {n ? `[${n}] ` : ""}
            {s ? `${sourceShortName(s, 40)} (tier ${s.reliability_tier})` : id}
          </span>
        );
      })}
    </span>
  );
}

function Tooltip({ id, e, x, sources, citation }: { id: string; e: TimelineEvent; x: number; sources: ReadonlyMap<string, Source>; citation: ReadonlyMap<string, number> }) {
  const align = x < 18 ? "left-0" : x > 82 ? "right-0" : "left-1/2 -translate-x-1/2";
  return (
    <span
      role="tooltip"
      id={id}
      className={cx(
        "pointer-events-none invisible absolute top-full z-30 mt-1 w-72 rounded-md border border-line bg-surface p-2.5 text-left text-xs opacity-0 shadow-lg transition-opacity",
        "group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100",
        align,
      )}
    >
      <span className="block font-semibold text-ink">
        {formatPartialDate(e.date)}
        <span className="font-normal text-muted">{precisionNote(e)}</span>
        <span className="font-normal text-muted"> {"·"} {TIMELINE_KIND_LABEL[e.kind]}</span>
      </span>
      <span className="mt-1 block text-ink">{e.label}</span>
      {e.description ? <span className="mt-1 block text-ink-2">{e.description}</span> : null}
      {e.source_ids.length > 0 ? (
        <span className="mt-1.5 block border-t border-line pt-1.5 text-muted">
          <SourceRefs e={e} sources={sources} citation={citation} />
        </span>
      ) : null}
    </span>
  );
}

function Legend({ events, sources }: { events: TimelineEvent[]; sources: ReadonlyMap<string, Source> }) {
  const kinds = (Object.keys(TIMELINE_KIND_LABEL) as TimelineKind[]).filter((k) => events.some((e) => e.kind === k));
  const tiers = ([1, 2, 3, 4] as const).filter((t) => events.some((e) => tierOf(e, sources) === t));
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-ink-2">
      <ul className="flex flex-wrap gap-x-4 gap-y-1" aria-label="Marker shapes">
        {kinds.map((k) => (
          <li key={k} className="flex items-center gap-1.5">
            <Glyph kind={k} tier={null} />
            {TIMELINE_KIND_LABEL[k]}
          </li>
        ))}
      </ul>
      <ul className="flex flex-wrap gap-x-4 gap-y-1" aria-label="Marker colours">
        {tiers.map((t) => (
          <li key={t} className="flex items-center gap-1.5">
            <span aria-hidden="true" className={cx("size-2.5 rounded-full", TIER_DOT[t])} />
            Tier {t} ({TIER_NAME[t]})
          </li>
        ))}
      </ul>
    </div>
  );
}

function VerticalList({ events, sources, citation }: Props) {
  return (
    <ol className="relative ml-1.5 border-l border-line-strong" aria-label="Timeline events">
      {keyed(events, (e) => e.id).map(([key, e]) => (
        <li key={key} className="print-break-avoid relative pb-3 pl-5 last:pb-0">
          <span className="absolute -left-[7px] top-1 grid size-3.5 place-items-center bg-surface">
            <Glyph kind={e.kind} tier={tierOf(e, sources)} />
          </span>
          <p className="text-xs font-semibold tabular-nums text-ink">
            {formatPartialDate(e.date)}
            <span className="font-normal text-muted">
              {precisionNote(e)} {"·"} {TIMELINE_KIND_LABEL[e.kind]}
            </span>
          </p>
          <p className="text-sm text-ink">{e.label}</p>
          {e.description ? <p className="text-xs text-ink-2">{e.description}</p> : null}
          {e.source_ids.length > 0 ? (
            <p className="text-xs text-muted">
              <SourceRefs e={e} sources={sources} citation={citation} />
            </p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

interface Placed {
  e: TimelineEvent;
  x: number;
  row: number;
  labelLeft: boolean;
  text: string;
}

function layoutLane(events: TimelineEvent[], pos: (d: string) => number, sources: ReadonlyMap<string, Source>) {
  const rowEnds: number[] = [];
  const placed: Placed[] = events
    .map((e) => ({ e, x: pos(e.date) }))
    .sort((a, b) => a.x - b.x)
    .map(({ e, x }) => {
      const text = shortLabel(e, sources);
      const w = 2.2 + text.length * CHAR_PCT;
      const labelLeft = x + w > 100;
      const start = labelLeft ? x - w : x - 1;
      const end = labelLeft ? x + 1 : x + w;
      let row = rowEnds.findIndex((r) => start - r >= GAP_PCT);
      if (row === -1) {
        row = rowEnds.length;
        rowEnds.push(end);
      } else {
        rowEnds[row] = end;
      }
      return { e, x, row, labelLeft, text };
    });
  return { placed, rows: Math.max(1, rowEnds.length) };
}

export function Timeline({ events, sources, citation }: Props) {
  if (events.length === 0) return <p className="text-sm text-muted">No dated events.</p>;
  const research = events.find((e) => e.kind === "research_conducted");
  const dated = events.filter((e) => e.kind !== "research_conducted");
  const refYear = research ? partialDateToYear(research.date) : Math.max(...dated.map((e) => partialDateToYear(e.date)));
  const end = Math.floor(refYear) + 1;
  const start = Math.min(end - 1, Math.floor(refYear) - WINDOW_YEARS);
  const span = end - start;
  const pos = (d: string) => ((partialDateToYear(d) - start) / span) * 100;
  const ticks: number[] = [];
  for (let y = start; y < end; y += 1) ticks.push(y); // no label at the right edge (it would be clipped)
  const inWindow = (e: TimelineEvent) => partialDateToYear(e.date) >= start;
  const lanes = LANES.map((lane) => {
    const all = dated.filter((e) => e.kind === lane.kind);
    const earlier = all.filter((e) => !inWindow(e));
    return { ...lane, earlier, ...layoutLane(all.filter(inWindow), pos, sources) };
  }).filter((l) => l.placed.length > 0 || l.earlier.length > 0);

  return (
    <div className="flex flex-col gap-3">
      <Legend events={events} sources={sources} />

      {/* Swimlane chart (md and up, screen only): one row per kind, labelled markers. */}
      <div className="hidden md:block print:hidden">
        <div className="relative pt-6">
          {lanes.map((lane) => {
            const height = lane.rows * ROW_HEIGHT + LANE_PAD * 2;
            return (
              <div key={lane.kind} className="flex border-b border-line last:border-b-0">
                <div className="flex w-28 shrink-0 flex-col justify-center gap-0.5 pr-3 text-xs" style={{ height }}>
                  <span className="font-semibold text-ink-2">{lane.label}</span>
                  {lane.earlier.length > 0 ? (
                    <span
                      className="text-muted"
                      title={lane.earlier.map((e) => `${formatPartialDate(e.date)}: ${e.label}`).join("\n")}
                    >
                      {"←"} {lane.earlier.length} earlier
                    </span>
                  ) : null}
                </div>
                <ul aria-label={`${lane.label} markers`} className="relative flex-1" style={{ height }}>
                  {lane.placed.map(({ e, x, row, labelLeft, text }) => {
                    const top = LANE_PAD + row * ROW_HEIGHT;
                    const tipId = `tl-tip-${e.id}`;
                    return (
                      <li
                        key={e.id}
                        className="group absolute z-0 flex items-center hover:z-20 focus-within:z-20"
                        style={{ left: `${x}%`, top, height: ROW_HEIGHT }}
                      >
                        <button
                          type="button"
                          aria-label={`${formatPartialDate(e.date)}: ${TIMELINE_KIND_LABEL[e.kind]}, ${e.label}`}
                          aria-describedby={tipId}
                          className={cx(
                            "relative flex -translate-x-[9px] items-center gap-1 rounded px-0.5 hover:bg-subtle",
                            labelLeft && "flex-row-reverse translate-x-[calc(-100%+9px)]",
                          )}
                        >
                          <span className="grid size-[18px] shrink-0 place-items-center">
                            <Glyph kind={e.kind} tier={tierOf(e, sources)} />
                          </span>
                          <span className="whitespace-nowrap text-[11px] font-medium text-ink-2">{text}</span>
                        </button>
                        <Tooltip id={tipId} e={e} x={x} sources={sources} citation={citation} />
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}

          {/* axis */}
          <div className="flex">
            <div className="w-28 shrink-0" />
            <div className="relative flex-1 border-t border-line-strong" style={{ height: AXIS_HEIGHT }} aria-hidden="true">
              {ticks.map((y) => (
                <div key={y} className="absolute top-0" style={{ left: `${pos(`${y}-01-01`)}%` }}>
                  <span className="absolute top-0 h-1.5 w-px bg-line-strong" />
                  <span className="absolute top-2 -translate-x-1/2 text-[11px] tabular-nums text-muted">{y}</span>
                </div>
              ))}
            </div>
          </div>

          {/* research date: one dashed line across every lane */}
          {research ? (
            <div className="pointer-events-none absolute inset-y-0 left-28 right-0" aria-hidden="true">
              <div
                className="absolute bottom-0 top-0 border-l-2 border-dashed border-research"
                style={{ left: `${pos(research.date)}%` }}
              >
                <span className="absolute top-0 right-1 whitespace-nowrap rounded bg-research px-1.5 py-0.5 text-[11px] font-semibold text-white">
                  {research.short_label || "Research"} {formatPartialDate(research.date)}
                </span>
              </div>
            </div>
          ) : null}
        </div>
        <p className="mt-1 text-xs text-muted">
          Showing {start}–{end - 1}; older events are counted under {"“"}earlier{"”"} and listed below. Year-only dates sit
          mid-year. Hover over or tab to a marker for details.
        </p>
      </div>

      <details open className="group/list rounded-md border border-line px-3 py-2">
        <summary className="cursor-pointer text-xs font-semibold text-ink-2">
          Timeline as list ({events.length} events)
        </summary>
        <div className="mt-3">
          <VerticalList events={events} sources={sources} citation={citation} />
        </div>
      </details>
    </div>
  );
}
