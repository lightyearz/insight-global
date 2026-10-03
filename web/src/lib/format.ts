import type { DatePrecision, IsoDateTime, PartialDate, Source } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Precision of a contract PartialDate ("YYYY" | "YYYY-MM" | "YYYY-MM-DD"). */
export function precisionOf(date: PartialDate): DatePrecision {
  if (date.length >= 10) return "day";
  if (date.length >= 7) return "month";
  return "year";
}

/** "2024-04-13" -> "13 Apr 2024", "2022-02" -> "Feb 2022", "2010" -> "2010". */
export function formatPartialDate(date: PartialDate | null | undefined): string {
  if (!date) return "Not stated";
  const [y, m, d] = date.split("-");
  const month = m ? MONTHS[Number(m) - 1] : undefined;
  if (d && month) return `${Number(d)} ${month} ${y}`;
  if (month) return `${month} ${y}`;
  return y ?? date;
}

/** Datetimes are always rendered in UTC so server and client output match. */
export function formatDateTime(iso: IsoDateTime | null | undefined): string {
  if (!iso) return "-";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  const hh = String(dt.getUTCHours()).padStart(2, "0");
  const mm = String(dt.getUTCMinutes()).padStart(2, "0");
  return `${dt.getUTCDate()} ${MONTHS[dt.getUTCMonth()]} ${dt.getUTCFullYear()}, ${hh}:${mm} UTC`;
}

export function formatDate(iso: IsoDateTime | null | undefined): string {
  if (!iso) return "-";
  return formatPartialDate(iso.slice(0, 10));
}

/** Decimal year of a partial date. Year-only dates sit mid-year, month-only mid-month. */
export function partialDateToYear(date: PartialDate): number {
  const [y, m, d] = date.split("-").map(Number);
  const year = y ?? 0;
  if (m === undefined) return year + 0.5;
  if (d === undefined) return year + (m - 1 + 0.5) / 12;
  return year + (m - 1) / 12 + (d - 1) / 365;
}

/** Age of a dated source relative to a reference time, e.g. "2.1 years old". */
export function ageLabel(date: PartialDate | null, reference: IsoDateTime): string {
  if (!date) return "age unknown";
  const ref = new Date(reference);
  const refYear = ref.getUTCFullYear() + ref.getUTCMonth() / 12 + (ref.getUTCDate() - 1) / 365;
  const years = refYear - partialDateToYear(date);
  if (years < 0.1) return "under a month old";
  if (years < 1) return `${Math.max(1, Math.round(years * 12))} months old`;
  return `${years.toFixed(1)} years old`;
}

export function formatDuration(startIso: IsoDateTime | null, endIso: IsoDateTime | null): string | null {
  if (!startIso || !endIso) return null;
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}

export function formatTokens(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

export function formatUsd(n: number): string {
  return `$${n.toFixed(n < 1 ? 4 : 2)}`;
}

/** Short human name for a source: issuing body, else publisher. */
export function sourceShortName(source: Source, max = 48): string {
  const name = source.issuing_body ?? source.publisher;
  return name.length > max ? `${name.slice(0, max - 1).trimEnd()}…` : name;
}

/** The later of updated_at / published_at (the contract's "effective date"). */
export function effectiveDate(source: Pick<Source, "published_at" | "updated_at">): PartialDate | null {
  return source.updated_at ?? source.published_at;
}

/** Latest retrieval time across sources: the evidence snapshot ("research conducted at"). */
export function researchConductedAt(sources: readonly Source[]): IsoDateTime | null {
  let latest: IsoDateTime | null = null;
  for (const s of sources) {
    if (latest === null || new Date(s.retrieved_at) > new Date(latest)) latest = s.retrieved_at;
  }
  return latest;
}

/** Stable, unique React keys from content (repeats get a "#n" suffix) without using array indexes. */
export function keyed<T>(items: readonly T[], key: (item: T) => string): [string, T][] {
  const seen = new Map<string, number>();
  return items.map((item) => {
    const base = key(item);
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    return [n === 1 ? base : `${base}#${n}`, item];
  });
}
