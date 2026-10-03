# Brand Assets and Icons

## Contents

- [Asset inventory and naming](#asset-inventory-and-naming)
- [Logo usage by context](#logo-usage-by-context)
- [Brand mark component](#brand-mark-component)
- [Icon library rules](#icon-library-rules)
- [Voice and tone](#voice-and-tone)

## Asset inventory and naming

Keep every brand asset in one folder, `web/public/images/brand/` (served at `/images/brand/`), and name files by variant and background so the right one is obvious:

```
/images/brand/<brand>-logo.svg                  master lockup (mark + wordmark), for light backgrounds
/images/brand/<brand>-logo-dark.svg             lockup for dark backgrounds
/images/brand/<brand>-mark.svg                  mark only, single colour, uses currentColor
/images/brand/<brand>-mark-{light,dark}@4x.png  raster mark for places that cannot use SVG
/images/brand/<brand>-stacked-{light,dark}.svg  stacked lockup for square spaces
/images/brand/<brand>-appicon-{light,dark}.png  app icons (maskable, with safe padding)
/images/brand/<brand>-og-{light,dark}.png       1200x630 social share image
/app/icon.svg, /app/apple-icon.png, /app/favicon.ico   favicons via Next.js file conventions
```

Rules:

- SVG first; raster only where SVG is unsupported (email, some social previews, app stores). Export raster at 2x and 4x.
- Each variant states the background it is designed for; never place the light-background lockup on a dark surface.
- Define clear space (for example, the height of the mark on every side) and a minimum size below which you switch from the lockup to the mark alone.
- Record the inventory in the living design-system page with a preview of each file on its intended background.

## Logo usage by context

| Context | Asset | Notes |
|---|---|---|
| Header / nav | Lockup SVG for the current theme | `<Image>` with explicit `width`/`height`, `priority` if above the fold, `alt` = product name |
| Footer | Mark or small lockup | Decorative if the product name is also in text nearby (`alt=""`) |
| Auth screens | Lockup centred above the form | One logo only; no marketing chrome |
| Favicon / tab | Mark on a solid background | Must read at 16px; test both browser themes |
| Social share | OG image with lockup and a short headline | Text large enough to read in a feed thumbnail |

Swap light/dark logo files with CSS (`[data-theme="dark"] .logo-light { display: none }`) or a `<picture>` element rather than reading the theme in JavaScript, to avoid hydration mismatches.

## Brand mark component

If the mark appears inline in UI (feature cards, empty states, loading), make it a React component so it inherits colour and size like an icon:

```tsx
type BrandMarkProps = { className?: string; size?: number; strokeWidth?: number; title?: string };

export function BrandMark({ className, size = 24, strokeWidth = 2, title }: BrandMarkProps) {
  return (
    <svg
      viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor"
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
      className={className} role={title ? "img" : undefined} aria-hidden={title ? undefined : true}
    >
      {title ? <title>{title}</title> : null}
      {/* brand mark paths */}
    </svg>
  );
}

<BrandMark className="size-6 text-primary" />
```

- Uses `currentColor`, so it is styled with text colour utilities and follows the theme.
- Match the icon library's 24px grid and stroke width so the mark sits naturally next to icons.
- Use this component everywhere the mark appears. Do not substitute a generic library icon that resembles it; that dilutes the brand and creates two near-identical glyphs.
- Variants (mark with check, mark with alert) are separate named exports from the same file, not ad-hoc compositions.

## Icon library rules

- One library app-wide (for example `lucide-react`); do not mix sets with different stroke weights and corner styles.
- Sizes: `size-4` (16px) in dense tables and inline with small text, `size-5` (20px) default, `size-6` (24px) in buttons with large text, `size-7`/`size-8` in feature tiles.
- Icons pair with text labels except for universally understood actions (close, search, menu), and even those get an `aria-label`.
- Choose icons that name the concept literally (a calendar for scheduling, a database for data sources). Avoid decorative "AI" icons (sparkles, magic wands) that tell the user nothing.
- Status icons are fixed per level (see the status table in SKILL.md); do not reuse them for unrelated meanings.
- Brand and social-network logos are not in `lucide-react`; use inline SVGs from each network's official brand kit, sized and coloured per that kit's rules.
- Import icons individually (`import { Calendar } from "lucide-react"`) so unused icons are tree-shaken.

## Voice and tone

Visual design and copy should feel like one product. Before writing UI copy, agree a short voice definition and keep it next to the tokens:

- **Three or four tone attributes**, each with a "this, not that" pair (for example "clear, not clever"; "confident, not boastful"; "friendly, not chummy").
- **Audiences** and what each needs from the UI (an operator needs speed and precision; a first-time user needs reassurance and next steps).
- **Vocabulary**: one term per concept across the app (do not alternate "workspace", "project" and "space"), and a list of terms to avoid.
- **Microcopy rules**: sentence case for labels and headings, verbs on buttons, no exclamation marks in errors, numbers as numerals.
