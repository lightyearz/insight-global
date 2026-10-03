# Design Tokens

## Contents

- [Where tokens live](#where-tokens-live)
- [Placeholder token set (Tailwind v4 CSS)](#placeholder-token-set-tailwind-v4-css)
- [Measured contrast](#measured-contrast)
- [Using tokens in components](#using-tokens-in-components)
- [Naming rules](#naming-rules)
- [Swapping in a real brand](#swapping-in-a-real-brand)
- [Gradients and decorative colour](#gradients-and-decorative-colour)

## Where tokens live

One file owns every token: `web/app/globals.css` (or a `tokens.css` it imports). Components never define colours, radii or shadows of their own. TypeScript that needs a token value (canvas charts, generated images) reads it at runtime with `getComputedStyle(document.documentElement).getPropertyValue('--color-primary')`, so it follows the active theme.

## Placeholder token set (Tailwind v4 CSS)

Brand-neutral values (Tailwind slate neutrals, indigo primary). Light values are registered in `@theme`, which makes Tailwind generate utilities (`bg-surface`, `text-text-muted`, `border-border-strong`, `rounded-lg`, `shadow-md`) that reference the variables. Dark values redefine the same variables under `[data-theme="dark"]`, so every utility switches with the theme and components need no `dark:` variants.

Do not re-map tokens to themselves inside `@theme inline` (`--color-primary: var(--color-primary)`); that is a circular reference. Either register values directly as below, or keep raw values under different names (`--primary`) and map `--color-primary: var(--primary)`.

```css
@import "tailwindcss";

@theme {
  /* Surfaces */
  --color-bg: #F8FAFC;
  --color-surface: #FFFFFF;
  --color-surface-muted: #F1F5F9;
  --color-surface-raised: #FFFFFF;
  --color-overlay: rgb(15 23 42 / 0.5);

  /* Text */
  --color-text: #0F172A;
  --color-text-muted: #475569;
  --color-text-subtle: #5B6B80;
  --color-text-inverse: #F8FAFC;

  /* Borders */
  --color-border: #E2E8F0;          /* decorative dividers only */
  --color-border-strong: #64748B;   /* inputs, checkboxes, control outlines (>= 3:1) */

  /* Primary */
  --color-primary: #4F46E5;
  --color-primary-hover: #4338CA;
  --color-on-primary: #FFFFFF;
  --color-primary-subtle: #EEF2FF;       /* selected rows, active nav background */
  --color-on-primary-subtle: #3730A3;
  --color-focus-ring: #4F46E5;

  /* Status: text/icon colour + tinted surface */
  --color-neutral: #475569;  --color-neutral-surface: #F1F5F9;
  --color-info: #1D4ED8;     --color-info-surface: #EFF6FF;
  --color-success: #15803D;  --color-success-surface: #F0FDF4;
  --color-warning: #B45309;  --color-warning-surface: #FFFBEB;
  --color-danger: #B91C1C;   --color-danger-surface: #FEF2F2;

  /* Shape (overrides Tailwind's default radius scale on purpose) */
  --radius-sm: 6px;  --radius-md: 8px;  --radius-lg: 12px;
  --radius-xl: 16px; --radius-2xl: 24px;

  /* Elevation */
  --shadow-sm: 0 1px 2px rgb(15 23 42 / 0.06), 0 1px 3px rgb(15 23 42 / 0.10);
  --shadow-md: 0 4px 6px rgb(15 23 42 / 0.07), 0 2px 4px rgb(15 23 42 / 0.06);
  --shadow-lg: 0 10px 15px rgb(15 23 42 / 0.10), 0 4px 6px rgb(15 23 42 / 0.05);

  /* Motion easing (Tailwind namespace: ease-standard, ease-exit) */
  --ease-standard: cubic-bezier(0.2, 0, 0, 1);
  --ease-exit: cubic-bezier(0.4, 0, 1, 1);
}

/* Tokens that are not Tailwind theme namespaces */
:root {
  color-scheme: light;
  --duration-fast: 150ms;
  --duration-base: 200ms;
  --duration-slow: 300ms;
  --z-sticky: 10; --z-dropdown: 20; --z-overlay: 40; --z-dialog: 50; --z-toast: 60;
}

[data-theme="dark"] {
  color-scheme: dark;

  --color-bg: #020617;
  --color-surface: #0F172A;
  --color-surface-muted: #1E293B;
  --color-surface-raised: #1E293B;
  --color-overlay: rgb(2 6 23 / 0.7);

  --color-text: #F1F5F9;
  --color-text-muted: #CBD5E1;
  --color-text-subtle: #94A3B8;
  --color-text-inverse: #0F172A;

  --color-border: #334155;
  --color-border-strong: #64748B;

  --color-primary: #818CF8;
  --color-primary-hover: #A5B4FC;
  --color-on-primary: #1E1B4B;
  --color-primary-subtle: #1E1B4B;
  --color-on-primary-subtle: #C7D2FE;
  --color-focus-ring: #818CF8;

  --color-neutral: #CBD5E1;  --color-neutral-surface: #1E293B;
  --color-info: #60A5FA;     --color-info-surface: #172554;
  --color-success: #4ADE80;  --color-success-surface: #052E16;
  --color-warning: #FBBF24;  --color-warning-surface: #451A03;
  --color-danger: #F87171;   --color-danger-surface: #450A0A;

  /* Shadows barely read on dark; rely on surface steps and borders */
  --shadow-sm: 0 1px 2px rgb(0 0 0 / 0.4);
  --shadow-md: 0 4px 8px rgb(0 0 0 / 0.45);
  --shadow-lg: 0 12px 24px rgb(0 0 0 / 0.5);
}

body {
  background-color: var(--color-bg);
  color: var(--color-text);
}
```

## Measured contrast

Minimum across `bg`, `surface` and `surface-muted` in each theme (WCAG ratio, checker in the `accessibility.md` reference):

| Pair | Light | Dark | Required |
|---|---|---|---|
| text | 16.3 | 13.4 | 4.5 |
| text-muted | 6.9 | 9.9 | 4.5 |
| text-subtle | 5.0 | 5.7 | 4.5 |
| on-primary on primary | 6.3 | 5.4 | 4.5 |
| primary as link text on surface | 6.3 | 6.0 | 4.5 |
| on-primary-subtle on primary-subtle | 8.9 | 10.7 | 4.5 |
| border-strong vs surface (non-text) | 4.8 | 3.8 | 3.0 |
| focus-ring vs surface (non-text) | 6.3 | 6.0 | 3.0 |
| status text on its status surface | 4.8 to 6.9 | 5.8 to 9.9 | 4.5 |

`--color-border` is deliberately low contrast; use it only for dividers whose removal would not hide information. Anything a user must perceive to operate a control (input outline, checkbox box, toggle track) uses `--color-border-strong`.

## Using tokens in components

```tsx
// Registered utilities (preferred)
<section className="rounded-lg border border-border bg-surface p-6 shadow-sm">
  <h2 className="text-lg font-semibold text-text">Usage</h2>
  <p className="text-sm text-text-muted">Last 30 days</p>
</section>

// Arbitrary-value fallback for a token that is not registered in @theme
<div className="z-[var(--z-sticky)] transition-opacity duration-[var(--duration-base)]" />
```

Never write a raw hex value in a component (`bg-[#4F46E5]`). If a needed colour has no token, add a token for both themes first.

## Naming rules

- `--color-<role>[-<variant>]`. Roles: `bg`, `surface`, `text`, `border`, `primary`, `focus-ring`, `neutral`, `info`, `success`, `warning`, `danger`. Variants: `muted`, `subtle`, `strong`, `raised`, `hover`, `surface`.
- Foreground for a filled background is `on-<role>` (`--color-on-primary`, `--color-on-primary-subtle`).
- Feature-scoped tokens are allowed when a feature needs its own palette (for example `--chat-user-bubble`), but they live in the token file, are defined for both themes, and derive from the semantic set where possible.
- Never name by hue (`--color-yellow`), by component (`--button-blue`) or by page.

## Swapping in a real brand

1. Pick the brand primary and generate a 50-950 scale for it (any OKLCH scale generator) so hover and subtle variants stay in the same hue.
2. Set `--color-primary` to the step that reaches at least 4.5:1 against `--color-on-primary`. For light brand hues (yellow, lime, cyan), keep the vivid step as the fill and set `--color-on-primary` to near-black instead of white.
3. If the vivid brand colour fails 3:1 as a focus ring or 4.5:1 as link text on the surface, keep it for fills and use a darker step for `--color-focus-ring` and links.
4. Tint neutrals slightly toward the brand hue (warm brand, warm greys) for cohesion; keep them low-chroma.
5. Keep status colours conventional (green success, amber warning, red danger). Do not reuse the brand colour as a status colour; a yellow brand must not double as the warning colour.
6. Re-run the contrast checker for every pair in both themes and update the measured-contrast table.
7. Update the living design-system page and capture screenshots in both themes.

## Gradients and decorative colour

- Gradients are decoration for marketing surfaces (hero, landing sections), built from adjacent steps of one hue or from `bg` to `primary-subtle`: `linear-gradient(to bottom right, var(--color-bg), var(--color-primary-subtle), var(--color-bg))`.
- Text over a gradient must pass contrast at every point it crosses: check against the lightest point for dark text and the darkest point for light text.
- App screens (dashboards, forms, tables) use flat surfaces. Gradients behind data reduce legibility.
