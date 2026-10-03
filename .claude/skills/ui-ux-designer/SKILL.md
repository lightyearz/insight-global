---
name: ui-ux-designer
description: Applies a token-based design system to Next.js, React and Tailwind UIs - semantic colour tokens with light and dark themes, a typography scale, a 4px spacing scale, radius, elevation and motion tokens, the full component state matrix, WCAG 2.2 AA accessibility, status and severity visuals, and data-dense dashboard patterns (KPI tiles, tables, filters, charts). Ships a brand-neutral placeholder token set to swap for a real brand. Use when designing or reviewing any UI, choosing colours, type or spacing, defining component states, building dashboards, tables or chat surfaces, theming dark mode, auditing accessibility, or checking visual consistency before frontend-developer implements it.
---

# UI/UX Designer

Design method and design-system rules for a Next.js (App Router) + React + TypeScript + Tailwind CSS frontend. This skill owns **what the UI should look and behave like**; the `frontend-developer` skill owns how it is built (React and ESLint rules, server/client boundaries, tooling gotchas). Test mechanics for accessibility and visual checks live in `frontend-test-runner` and `testing-qa`.

The token values in this skill are a **brand-neutral placeholder set** (slate neutrals, an indigo primary). They are contrast-checked and safe to ship as a starting point. Replacing them with a real brand means editing one token file, not components.

## Reference files (load on demand)

- [reference/design-tokens.md](reference/design-tokens.md) - the full placeholder token set as CSS custom properties (light and dark), Tailwind v4 `@theme` mapping, naming rules, and how to swap in a brand.
- [reference/component-patterns.md](reference/component-patterns.md) - buttons, inputs, cards, badges, dialogs, toasts, chat bubbles, with every interactive state.
- [reference/data-dense-dashboards.md](reference/data-dense-dashboards.md) - dashboard layout, KPI tiles, tables, filters, charts, density, loading/empty/error states.
- [reference/accessibility.md](reference/accessibility.md) - WCAG 2.2 AA checklist, contrast maths with a runnable checker, focus, keyboard, ARIA patterns, testing.
- [reference/themes-and-dark-mode.md](reference/themes-and-dark-mode.md) - dark mode via a `data-theme` attribute, user-selectable accent themes, persistence without a flash of the wrong theme.
- [reference/animation-and-motion.md](reference/animation-and-motion.md) - motion tokens, Framer Motion and CSS patterns, reduced motion.
- [reference/brand-and-icons.md](reference/brand-and-icons.md) - brand asset inventory and naming, a single brand-mark component, icon library rules.
- [reference/showcase-and-screenshots.md](reference/showcase-and-screenshots.md) - product screenshot showcases, annotation callouts, lightboxes, capturing a theme matrix for review.

## Design principles

1. **Clarity over cleverness.** Every element has one clear job. Remove decoration that does not inform.
2. **Tokens, not values.** Components reference semantic tokens (`--color-surface`, `--space-4`), never raw hex codes or arbitrary pixel values. A raw hex in a component is a review finding.
3. **Every state is designed.** Default, hover, focus-visible, active, disabled, loading, error, empty, selected. A component without its error and empty states is not finished.
4. **Accessibility is a requirement, not a pass.** WCAG 2.2 AA minimum: 4.5:1 text contrast, 3:1 for UI boundaries and focus rings, full keyboard operation, visible focus, correct names and roles.
5. **Never encode meaning in colour alone.** Pair colour with an icon, a label, a pattern or position.
6. **Mobile first.** Design the narrow layout first, then add columns as space allows. No horizontal page scroll at 320 CSS px.
7. **Progressive disclosure.** Show what the user needs for the current decision; put the rest one interaction away.
8. **Consistency beats local optimisation.** Reuse an existing pattern unless it demonstrably fails the user; if you change it, change it everywhere.

## Token model

Two layers:

1. **Primitive palette** (optional, private): raw scales such as `slate-50 ... slate-950`. Only token files reference these.
2. **Semantic tokens** (public): named by role, not appearance - `--color-bg`, `--color-surface`, `--color-text-muted`, `--color-primary`, `--color-on-primary`, `--color-border-strong`, `--color-focus-ring`, `--color-danger`, `--color-danger-surface`. Components use only these.

Rules:

- Name by **role**, never by hue (`--color-danger`, not `--color-red`). Hue names break the moment the brand or the theme changes.
- Every background token that carries text has a matching foreground token (`--color-primary` / `--color-on-primary`). Check each pair for contrast in **both** themes.
- Dark mode redefines the same semantic names under `[data-theme="dark"]`; components need no `dark:` variants. See [themes-and-dark-mode](reference/themes-and-dark-mode.md).

Placeholder core values (full set in [design-tokens](reference/design-tokens.md)):

| Token | Light | Dark | Use |
|---|---|---|---|
| `--color-bg` | `#F8FAFC` | `#020617` | Page background |
| `--color-surface` | `#FFFFFF` | `#0F172A` | Cards, panels, dialogs |
| `--color-surface-muted` | `#F1F5F9` | `#1E293B` | Table headers, wells, hover rows |
| `--color-text` | `#0F172A` | `#F1F5F9` | Headings, body |
| `--color-text-muted` | `#475569` | `#CBD5E1` | Secondary text |
| `--color-text-subtle` | `#5B6B80` | `#94A3B8` | Captions, metadata |
| `--color-border` | `#E2E8F0` | `#334155` | Decorative dividers |
| `--color-border-strong` | `#64748B` | `#64748B` | Input and control boundaries (3:1) |
| `--color-primary` | `#4F46E5` | `#818CF8` | Primary actions, links, selection |
| `--color-on-primary` | `#FFFFFF` | `#1E1B4B` | Text and icons on primary |
| `--color-focus-ring` | `#4F46E5` | `#818CF8` | Focus outlines |

Every text/background pair above meets 4.5:1 on `bg`, `surface` and `surface-muted` in its theme; `border-strong` and `focus-ring` meet 3:1. Re-run the checker in [accessibility](reference/accessibility.md) whenever a value changes.

**Light primaries need dark foregrounds.** A yellow, lime or light cyan brand colour almost never reaches 4.5:1 with white text. Set `--color-on-primary` to a near-black and check it; do not darken the brand colour until it turns muddy.

## Status and severity

Use one status scale app-wide, in a fixed order, with redundant encoding:

| Level | Text / icon token | Surface token | Icon (lucide-react) | Typical label |
|---|---|---|---|---|
| Neutral | `--color-neutral` | `--color-neutral-surface` | `Circle` / `Info` | Draft, Inactive |
| Info | `--color-info` | `--color-info-surface` | `Info` | Note, In progress |
| Success | `--color-success` | `--color-success-surface` | `CheckCircle2` | Healthy, Passed |
| Warning | `--color-warning` | `--color-warning-surface` | `AlertTriangle` | Degraded, Needs review |
| Danger | `--color-danger` | `--color-danger-surface` | `XOctagon` / `AlertOctagon` | Failed, Blocked |

Rules:

- Always render **icon + text label**, not a coloured dot alone. Colour-blind users and greyscale printouts must still read the level.
- If the product has its own ordered severity scale (risk levels, priority, SLA tiers), map each level to exactly one row above and document the mapping next to the tokens. Do not invent per-feature colours.
- Reserve `danger` for states that need action. Overusing red trains users to ignore it.
- Status text on its surface meets 4.5:1 in both themes in the placeholder set.

## Typography

Font: the platform system stack, or one variable font loaded through `next/font` (self-hosted, no layout shift). Two families at most (sans + mono).

```css
--font-sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
--font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
```

Type scale (rem-based so it respects user zoom and font-size settings):

| Token | Size | Weight | Line height | Use |
|---|---|---|---|---|
| `display` | 3rem (48px) | 700 | 1.1, letter-spacing -0.02em | Marketing hero only |
| `h1` | 2.25rem (36px) | 700 | 1.2 | Page title |
| `h2` | 1.875rem (30px) | 700 | 1.3 | Section title |
| `h3` | 1.5rem (24px) | 600 | 1.4 | Card or panel title |
| `h4` | 1.125rem (18px) | 600 | 1.4 | Sub-section, dialog title |
| `body-lg` | 1.25rem (20px) | 400 | 1.6 | Lead paragraphs |
| `body` | 1rem (16px) | 400 | 1.5 | Default text |
| `body-sm` | 0.875rem (14px) | 400 | 1.5 | Dense UI, table cells |
| `label` | 0.875rem (14px) | 500 | 1.4 | Form labels, buttons in dense UI |
| `caption` | 0.75rem (12px) | 400 | 1.4 | Metadata, axis labels; never for body copy |

Rules:

- One `h1` per page; headings in order without skipped levels. Style is independent of level: a visually small heading can still be an `h2`.
- Body copy at 16px minimum; dense app chrome may use 14px. 12px only for metadata.
- Prose line length 60-75 characters (`max-w-prose` or `max-w-[65ch]`).
- Numbers that line up (tables, KPIs, timers) use `tabular-nums`.
- Scale headings responsively (`text-3xl md:text-4xl lg:text-5xl`) rather than shrinking body text on mobile.

## Spacing, radius, elevation

Spacing uses a 4px base aligned with Tailwind's default scale (`1` = 4px), so `p-4` means 16px everywhere.

| Token | Value | Tailwind | Use |
|---|---|---|---|
| `--space-1` | 4px | `1` | Icon-to-text gap |
| `--space-2` | 8px | `2` | Tight gaps inside a component |
| `--space-3` | 12px | `3` | Small gaps, compact padding |
| `--space-4` | 16px | `4` | Default component padding |
| `--space-6` | 24px | `6` | Card padding, gaps between related groups |
| `--space-8` | 32px | `8` | Gaps between sections |
| `--space-12` | 48px | `12` | Major section spacing |
| `--space-16` | 64px | `16` | Hero and landing spacing |

Proximity carries meaning: space **inside** a group is smaller than space **between** groups. If two unrelated things are as close as two related things, the layout is lying.

| Radius token | Value | Use |
|---|---|---|
| `--radius-sm` | 6px | Badges, checkboxes, small chips |
| `--radius-md` | 8px | Buttons, inputs |
| `--radius-lg` | 12px | Cards, panels |
| `--radius-xl` | 16px | Dialogs, large cards |
| `--radius-2xl` | 24px | Hero media, feature blocks |
| `rounded-full` | 9999px | Pills, avatars (Tailwind built-in) |

Nested radii: inner radius = outer radius minus the padding between them, or the corners look uneven.

Elevation: three shadow levels (`--shadow-sm` for cards, `--shadow-md` for popovers and menus, `--shadow-lg` for dialogs). In dark mode shadows barely read; separate layers with a lighter surface token and a border instead.

Z-index: a fixed scale (`base 0`, `sticky 10`, `dropdown 20`, `overlay 40`, `dialog 50`, `toast 60`). Never pick an arbitrary `z-[999]`.

## Layout and breakpoints

Tailwind defaults: `sm` 640px, `md` 768px, `lg` 1024px, `xl` 1280px, `2xl` 1536px.

```tsx
<div className="flex flex-col gap-4 sm:flex-row">{/* stack, then row */}</div>
<div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">{/* cards */}</div>
<main className="mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8">{/* page gutter */}</main>
```

- Page gutters: 16px on mobile, 24px from `sm`, 32px from `lg`.
- Content width caps: prose `65ch`, forms `max-w-xl`, app pages `max-w-7xl`, dashboards may run full width.
- Touch targets at least 24x24 CSS px (WCAG 2.2 AA), aim for 44x44 on touch-first screens.
- Test at 320px wide and at 200% browser zoom.

## Icons and brand

- One icon library across the app (for example `lucide-react`). Standard size `size-5` (20px) inline, `size-4` in dense tables, `size-6`/`size-7` in feature tiles. Stroke width consistent.
- Choose icons that name the concept. Avoid generic "AI magic" sparkles and decorative icons that add no meaning.
- The brand mark is a single custom component using `currentColor`; do not substitute a generic library icon that merely resembles the logo.
- Icon-only buttons need an accessible name (`aria-label`); decorative icons get `aria-hidden="true"`.
- `lucide-react` no longer ships brand or social-network logos; use inline SVGs from each network's official brand kit.

Details and asset naming: [brand-and-icons](reference/brand-and-icons.md).

## Component states

Every interactive component specifies all applicable states:

| State | Treatment |
|---|---|
| Default | Token colours, clear affordance (buttons look pressable, links look like links) |
| Hover | Subtle shift (one step darker/lighter or a muted background); never the only cue |
| Focus-visible | 2px `--color-focus-ring` outline with 2px offset; never `outline: none` without a replacement |
| Active / pressed | Slightly darker or inset; `aria-pressed` for toggles |
| Disabled | Reduced emphasis, `cursor-not-allowed`, still legible; prefer explaining why over silently disabling |
| Loading | Spinner or skeleton in place, layout does not jump, control disabled with `aria-busy` |
| Error | Danger colour + icon + message text tied with `aria-describedby`; say how to fix it |
| Empty | Explain what will appear here and offer the next action |
| Selected / current | Primary-tinted surface + a non-colour cue (check, bold, indicator bar); `aria-current` or `aria-selected` |

Edge cases to design for: very long text and unbroken strings, missing or null data, zero and huge numbers, first-time use, slow network, permission denied, and right-to-left if the product localises.

Patterns with code: [component-patterns](reference/component-patterns.md).

## Data-dense screens

Dashboards and admin tables get their own rules (density options, right-aligned numerics, sticky headers, "as of" timestamps, filter bars, chart selection). Read [data-dense-dashboards](reference/data-dense-dashboards.md) before designing any dashboard, report or table-heavy page.

## Implementation rules for designers handing off code

These are enforced by the frontend lint setup; designs and snippets must respect them (full detail in `frontend-developer`):

- Images through `<Image>` from `next/image`; internal links through `<Link>` from `next/link`.
- List keys from content (`key={item.id}`), never array indices. Static decorative arrays get explicit `id` fields.
- No `eslint-disable` comments; fix the cause.
- No synchronous `setState` inside `useEffect`; use lazy `useState` initialisers or derive during render.
- Style with tokens through Tailwind (`bg-surface`, `text-text-muted`, or `bg-[var(--token)]` for unregistered tokens), not hardcoded hex values.

```tsx
<button
  type="button"
  className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 font-semibold text-on-primary
             transition-colors hover:bg-primary-hover
             focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring
             disabled:cursor-not-allowed disabled:opacity-50"
>
  Create report
</button>
```

Utilities such as `bg-primary` and `text-on-primary` exist because the tokens are registered in Tailwind's `@theme` (see [design-tokens](reference/design-tokens.md)).

## Living design-system page

Keep one page that renders every token and component so reviewers see the system, not just the spec: colour swatches with contrast ratios, type specimens, spacing and radius samples, every component in every state, and a theme toggle. A dev-only route (for example `/design-system`, excluded from production builds or behind a flag) or Storybook both work. Update it in the same change that adds or alters a token or component.

## Review workflow

When reviewing existing UI:

1. Load the page in both themes, at 320px, 768px and 1280px, and at 200% zoom.
2. Grep the changed files for raw hex codes, arbitrary pixel values (`p-[13px]`), and `z-[`. Each is a finding unless justified.
3. Tab through every interactive element; confirm visible focus, logical order, and that nothing is reachable only by mouse.
4. Check contrast of any new colour pair with the checker in [accessibility](reference/accessibility.md).
5. Look for missing states (loading, error, empty, disabled) and for colour-only meaning.
6. Look for cognitive overload: too many competing primary actions, unclear hierarchy, walls of equal-weight text.
7. Report findings ranked by user impact, each with the file, the problem, the user-facing consequence, and the concrete fix (token or class to use).

## Checklist before handing off

- [ ] Only semantic tokens; no raw hex, no arbitrary spacing or z-index values
- [ ] Type follows the scale; one `h1`; headings in order
- [ ] Spacing from the 4px scale; group spacing reflects relationships
- [ ] All states designed: hover, focus-visible, active, disabled, loading, error, empty, selected
- [ ] Works in light and dark themes; every new colour pair contrast-checked in both
- [ ] Status shown with icon + label, never colour alone
- [ ] Responsive at 320 / 768 / 1280 px; no horizontal page scroll; 200% zoom usable
- [ ] Keyboard operable; touch targets at least 24x24 px
- [ ] Motion respects `prefers-reduced-motion`
- [ ] Icons from the one library; icon-only buttons have accessible names
- [ ] Living design-system page updated if tokens or components changed

## After completing design work

1. Hand the implementation notes to `frontend-developer` (or implement directly following that skill's rules), and the test plan to `frontend-test-runner` (type-check, lint, Playwright, axe checks).
2. Ask `project-manager` to record the completed design tasks and any new components in the project's tracking docs.
3. Report to the user: before/after screenshots in both themes, files changed, and the key visual and accessibility improvements.
