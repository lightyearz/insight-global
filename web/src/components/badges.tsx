import { AlertTriangle, CheckCircle2, CircleDashed, Clock, FileCheck2, Loader2, ThumbsDown, ThumbsUp, XCircle } from "lucide-react";
import { CONFIDENCE_LABEL, DIRECTION_LABEL, SOURCE_TYPE_LABEL, STATUS_LABEL } from "@/lib/labels";
import { formatPartialDate, sourceShortName } from "@/lib/format";
import { safeHref } from "@/lib/safe-href";
import type { BriefingStatus, Confidence, RecommendationDirection, ReliabilityTier, Source } from "@/lib/types";
import { Badge, cx } from "./ui";

const STATUS_TONE = {
  researching: "info",
  awaiting_review: "warn",
  generating_report: "info",
  completed: "ok",
  failed: "danger",
} as const;

const STATUS_ICON = {
  researching: Loader2,
  awaiting_review: Clock,
  generating_report: Loader2,
  completed: FileCheck2,
  failed: XCircle,
} as const;

export function StatusBadge({ status }: { status: BriefingStatus }) {
  const Icon = STATUS_ICON[status];
  const spinning = status === "researching" || status === "generating_report";
  return (
    <Badge tone={STATUS_TONE[status]}>
      <Icon aria-hidden="true" className={cx("size-3.5", spinning && "animate-spin")} />
      {STATUS_LABEL[status]}
    </Badge>
  );
}

export const TIER_NAME: Record<ReliabilityTier, string> = {
  1: "Guideline",
  2: "Systematic review",
  3: "Curated summary",
  4: "Other",
};

const TIER_CLASS: Record<ReliabilityTier, string> = {
  1: "bg-tier-1-soft text-tier-1 border-tier-1/40",
  2: "bg-tier-2-soft text-tier-2 border-tier-2/40",
  3: "bg-tier-3-soft text-tier-3 border-tier-3/40",
  4: "bg-tier-4-soft text-tier-4 border-tier-4/40",
};

export const TIER_DOT: Record<ReliabilityTier, string> = {
  1: "bg-tier-1",
  2: "bg-tier-2",
  3: "bg-tier-3",
  4: "bg-tier-4",
};

/** Tier badge; the rationale (when given) is exposed as a tooltip and to screen readers. */
export function TierBadge({
  tier,
  rationale,
  compact = false,
}: {
  tier: ReliabilityTier;
  rationale?: string;
  compact?: boolean;
}) {
  const label = compact ? `T${tier}` : `Tier ${tier} · ${TIER_NAME[tier]}`;
  const description = `Reliability tier ${tier} of 4 (${TIER_NAME[tier]})${rationale ? `: ${rationale}` : ""}`;
  return (
    <span
      title={description}
      className={cx(
        "inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 text-xs font-semibold",
        TIER_CLASS[tier],
      )}
    >
      <span aria-hidden="true">{label}</span>
      <span className="sr-only">{description}</span>
    </span>
  );
}

/**
 * Visible tier key (badges only carry a tooltip, which keyboard and touch users cannot reach).
 * Rendered wherever tier badges appear: research panel, review header, report sources.
 */
export function TierLegend({ className }: { className?: string }) {
  return (
    <p className={cx("flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted", className)}>
      <span className="font-medium text-ink-2">Reliability tiers:</span>
      {([1, 2, 3, 4] as const).map((t) => (
        <span key={t} className="inline-flex items-center gap-1">
          <span aria-hidden="true" className={cx("size-2 rounded-full", TIER_DOT[t])} />
          <span>
            <span className="font-semibold">T{t}</span> {TIER_NAME[t]}
          </span>
        </span>
      ))}
      <span>(T1 is the most reliable; each source states the rule that set its tier)</span>
    </p>
  );
}

const DIRECTION_TONE = {
  for: "ok",
  conditional: "info",
  mixed: "warn",
  against: "danger",
  not_stated: "neutral",
} as const;

/** What the cited sources recommend about an option (derived from evidence stances). */
export function DirectionBadge({ direction }: { direction: RecommendationDirection }) {
  const Icon = direction === "against" ? ThumbsDown : direction === "for" ? ThumbsUp : null;
  return (
    <Badge tone={DIRECTION_TONE[direction]}>
      {Icon ? <Icon aria-hidden="true" className="size-3.5" /> : null}
      {DIRECTION_LABEL[direction]}
    </Badge>
  );
}

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const tone = confidence === "high" ? "ok" : confidence === "medium" ? "accent" : "warn";
  const bars = confidence === "high" ? 3 : confidence === "medium" ? 2 : 1;
  return (
    <Badge tone={tone} title={CONFIDENCE_LABEL[confidence]}>
      <span aria-hidden="true" className="inline-flex items-end gap-px">
        {[1, 2, 3].map((n) => (
          <span
            key={n}
            className={cx("w-0.5 rounded-sm", n <= bars ? "bg-current" : "bg-current/25")}
            style={{ height: `${4 + n * 2}px` }}
          />
        ))}
      </span>
      {CONFIDENCE_LABEL[confidence]}
    </Badge>
  );
}

export function GroundedFlag({ grounded }: { grounded: boolean }) {
  return grounded ? (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-ok">
      <CheckCircle2 aria-hidden="true" className="size-3.5" />
      Quote verified in source
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-warn">
      <AlertTriangle aria-hidden="true" className="size-3.5" />
      Quote not found verbatim in source
    </span>
  );
}

/** Compact source chip: tier, short name, published date. Links to the source. */
export function SourceChip({ source, index }: { source: Source; index?: number }) {
  const published = formatPartialDate(source.published_at);
  const href = safeHref(source.url);
  const body = (
    <>
      {index !== undefined ? <span className="font-mono text-muted">[{index}]</span> : null}
      <TierBadge tier={source.reliability_tier} rationale={source.tier_rationale} compact />
      <span className="truncate">{sourceShortName(source, 36)}</span>
      <span className="whitespace-nowrap text-muted">{published}</span>
      <span className="sr-only">
        {`${source.title}. ${SOURCE_TYPE_LABEL[source.source_type]}, published ${published}${source.updated_at ? `, updated ${formatPartialDate(source.updated_at)}` : ""}.`}
      </span>
    </>
  );
  const className =
    "inline-flex max-w-full items-center gap-1.5 rounded border border-line bg-surface px-1.5 py-0.5 text-xs text-ink-2";
  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={source.title}
      className={cx(className, "hover:border-accent-line hover:bg-accent-soft")}
    >
      {body}
    </a>
  ) : (
    <span className={className}>{body}</span>
  );
}

export function UnknownSourceChip({ id }: { id: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-dashed border-line-strong px-1.5 py-0.5 text-xs text-muted">
      <CircleDashed aria-hidden="true" className="size-3" />
      {id}
    </span>
  );
}
