# Data-Dense Dashboards

## Contents

- [Start from the questions](#start-from-the-questions)
- [Layout](#layout)
- [KPI tiles](#kpi-tiles)
- [Tables](#tables)
- [Filters and time range](#filters-and-time-range)
- [Charts](#charts)
- [Numbers, dates and units](#numbers-dates-and-units)
- [Loading, empty, stale and error states](#loading-empty-stale-and-error-states)
- [Responsive behaviour](#responsive-behaviour)
- [Dashboard review checklist](#dashboard-review-checklist)

## Start from the questions

Before laying anything out, write down the three to five questions the dashboard must answer for its main user ("Is anything failing right now?", "Is cost trending above budget?"). Every tile, chart and table must answer one of them. Anything that answers none goes to a secondary page or is cut.

Order the page by urgency: status and exceptions first, trends second, detail tables last.

## Layout

- 12-column grid on desktop, gap `gap-4` (dense) or `gap-6` (comfortable). Full width is fine for dashboards; keep page gutters.
- Top row: KPI tiles (3-5). Middle: one or two primary charts. Bottom: the detail table that drills into the charts.
- Group related widgets inside one panel with a shared title instead of many small borders; borders and shadows on every widget create noise.
- Panel anatomy: title (what), subtitle or timestamp (scope and freshness), body, optional footer link ("View all"). Titles state the metric, not a label like "Chart 1".
- Keep global controls (time range, environment, segment) in one sticky bar at the top so their scope is obvious. A control inside a panel affects only that panel.

## KPI tiles

```tsx
<div className="rounded-lg border border-border bg-surface p-4">
  <p className="text-sm text-text-muted">Error rate (24h)</p>
  <p className="mt-1 text-3xl font-semibold tabular-nums text-text">0.42%</p>
  <p className="mt-1 inline-flex items-center gap-1 text-sm text-success">
    <ArrowDownRight className="size-4" aria-hidden="true" />
    <span>0.08 pts vs previous 24h</span>
  </p>
</div>
```

- One number per tile, with its unit, its period and a comparison (vs previous period, vs target). A number without context is not a KPI.
- Delta colour reflects **good or bad**, not up or down: lower error rate is good (success colour) even though the arrow points down. Always include the arrow and the signed text, not colour alone.
- Optional sparkline (no axes, 24-32px tall) for shape; the precise value lives in the number.
- Do not show more decimals than the decision needs. 0.42% is useful; 0.41837% is noise.

## Tables

Tables are where data-dense UIs succeed or fail.

```tsx
<div className="overflow-x-auto rounded-lg border border-border">
  <table className="w-full border-collapse text-sm">
    <caption className="sr-only">Services by error rate, last 24 hours</caption>
    <thead className="sticky top-0 bg-surface-muted text-left text-text-muted">
      <tr>
        <th scope="col" className="px-3 py-2 font-medium">Service</th>
        <th scope="col" className="px-3 py-2 text-right font-medium" aria-sort="descending">
          <button type="button" className="inline-flex items-center gap-1">Errors <ArrowDown className="size-3.5" aria-hidden="true" /></button>
        </th>
        <th scope="col" className="px-3 py-2 font-medium">Status</th>
      </tr>
    </thead>
    <tbody className="divide-y divide-border bg-surface">
      {rows.map((r) => (
        <tr key={r.id} className="hover:bg-surface-muted">
          <th scope="row" className="max-w-64 truncate px-3 py-2 text-left font-normal text-text" title={r.name}>{r.name}</th>
          <td className="px-3 py-2 text-right tabular-nums text-text">{fmt.format(r.errors)}</td>
          <td className="px-3 py-2"><StatusBadge level={r.level} label={r.statusLabel} /></td>
        </tr>
      ))}
    </tbody>
  </table>
</div>
```

Rules:

- **Alignment:** text left, numbers right (with `tabular-nums`), headers aligned with their column's content. Centre only short fixed-width content (icons, toggles).
- **Density:** offer comfortable (row ~44-48px) and compact (row ~32-36px) if users scan large tables; default to comfortable on touch devices. Density changes padding and font size together, never only one.
- **Dividers over zebra stripes** for most tables; zebra helps only for very wide tables read across many columns.
- **Sticky header** on long tables; sticky first column on wide ones.
- **Sorting:** clickable header is a `<button>` inside the `<th>`; reflect state with `aria-sort` and an arrow icon. Default sort answers the main question (worst first).
- **Truncation:** truncate long text with an ellipsis, expose the full value via `title` and in the detail view. Never truncate numbers or IDs users need to copy; let those wrap or widen.
- **Row actions:** one primary action per row visible; the rest in an overflow menu. Bulk actions appear in a toolbar when rows are selected, with a count ("3 selected").
- **Many rows:** paginate (with total count) when users jump to specific pages; virtualise when they scroll and scan. Keep column widths stable across pages.
- **Semantics:** real `<table>` markup with `<th scope>`, a caption (visible or `sr-only`), and no `div` grids pretending to be tables.

## Filters and time range

- Filter bar above the content it filters. Applied filters show as removable chips plus a "Clear all".
- Time range: presets (Last 1h, 24h, 7d, 30d) plus custom. Show the resolved absolute range and timezone near the title ("1 Mar 09:00 - 2 Mar 09:00 UTC").
- Persist filter state in the URL query string so views are shareable and survive reload.
- Apply simple filters immediately; batch complex ones behind an "Apply" button so each change does not trigger a heavy query.

## Charts

Choose the chart from the question:

| Question | Chart |
|---|---|
| How does a value change over time? | Line (continuous) or column (discrete periods) |
| How do categories compare? | Horizontal bar, sorted |
| What is the part-to-whole split? | Stacked bar or a single 100% bar; pie only for 2-3 parts |
| How are values distributed? | Histogram or box plot |
| Is there a relationship between two measures? | Scatter |
| Where are hot spots across two dimensions? | Heatmap with a sequential scale |

Rules:

- **One message per chart**, stated in the title ("Errors spiked after the 14:00 deploy" in a report; the metric name on a live dashboard).
- **Bars start at zero.** Line charts may use a tight y-range, but label the axis clearly.
- **Few series.** Up to about five categorical colours; beyond that, highlight the one or two that matter in colour and render the rest in a neutral grey, or use small multiples.
- **Label directly** at line ends or on bars instead of a distant legend when possible.
- **Colour has a job:** categorical palette for unrelated series, sequential (light to dark, one hue) for magnitude, diverging (two hues around a meaningful midpoint) for above/below a target. Status colours only for status.
- **Not colour alone:** distinguish series by label, marker shape or dash pattern as well; check the palette under a colour-vision-deficiency simulator.
- **Gridlines** light (`--color-border`), few, horizontal only for most charts. No 3D, no shadows, no gradients in plot areas.
- **Tooltips** show exact values with units and the timestamp; they supplement, never replace, visible labels. Make them reachable by keyboard focus, not hover only.
- **Accessibility:** give each chart an accessible name and a text summary (`aria-describedby`) of the key takeaway, and offer the underlying data as a table (toggle or "View data" link).
- **Theme:** read colours from tokens at runtime so charts switch with dark mode; check categorical colours against both surfaces.

## Numbers, dates and units

- Format with `Intl.NumberFormat` and `Intl.DateTimeFormat` in the user's locale; never concatenate strings.
- Compact large numbers in tiles (`notation: "compact"` gives 1.2M) but show full values in tables and tooltips.
- Units in the column header or axis label ("Latency (ms)"), not repeated in every cell.
- Percent vs percentage points: a change from 2% to 3% is "+1 pt" (or "+50%"); label which one.
- Relative times ("5 min ago") for freshness, absolute timestamps with timezone on hover and in exports.
- Represent missing data as an em dash or "No data", distinct from zero. Never plot missing data as zero.

## Loading, empty, stale and error states

- **Per-panel loading:** each panel loads and fails independently with its own skeleton; one slow query must not blank the page.
- **Freshness:** show "Updated 2 min ago" per panel or for the page. When data is older than its expected refresh interval, mark it stale (warning icon + text).
- **Empty:** distinguish "no data yet" (setup needed, link to setup) from "no data for these filters" (offer to widen the range or clear filters) from "zero" (a real value, shown as 0).
- **Error:** in-panel message with Retry; keep the last good data visible and marked stale if available.

## Responsive behaviour

- KPI tiles: 1 column on mobile, 2 at `sm`, 4 or 5 at `lg`.
- Charts: full width on mobile, reduce tick density and drop the legend for direct labels; keep the aspect ratio readable (minimum ~200px tall).
- Tables on mobile: either horizontal scroll inside the bordered container (keep the first column sticky) or switch to a stacked card list showing the 3-4 most important fields with a link to the detail. Never let the table widen the page.

## Dashboard review checklist

- [ ] Each widget answers a written question; page ordered by urgency
- [ ] Every number has unit, period and comparison
- [ ] Deltas coloured by good/bad and shown with arrow and signed text
- [ ] Numbers right-aligned with `tabular-nums`; consistent precision
- [ ] Tables use real table semantics, sortable headers expose `aria-sort`
- [ ] Charts chosen from the question, bars start at zero, five series or fewer in colour
- [ ] Chart key takeaway available as text; data available as a table
- [ ] Missing data distinct from zero; freshness and timezone visible
- [ ] Per-panel loading, empty, stale and error states designed
- [ ] Works in both themes and at 320px without page-level horizontal scroll
