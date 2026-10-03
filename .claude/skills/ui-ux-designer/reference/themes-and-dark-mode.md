# Themes and Dark Mode

## Contents

- [Mechanism](#mechanism)
- [Applying the theme without a flash](#applying-the-theme-without-a-flash)
- [Dark mode design rules](#dark-mode-design-rules)
- [User-selectable accent themes](#user-selectable-accent-themes)
- [Theming one section independently](#theming-one-section-independently)
- [Verifying themes](#verifying-themes)

## Mechanism

- Theme lives in a `data-theme` attribute on `<html>`: `light` or `dark`. All semantic tokens are redefined under `[data-theme="dark"]` (values in the `design-tokens.md` reference); components reference tokens only and contain no `dark:` variants.
- Default to the OS preference (`prefers-color-scheme`) until the user chooses; then store the explicit choice (`light`, `dark` or `system`) in `localStorage` under an app-namespaced key such as `<app>-theme`.
- Set `color-scheme: light` / `dark` alongside the tokens so native form controls, scrollbars and the default canvas match.
- Tailwind's `dark:` variant does not automatically follow a `data-theme` attribute, and a `@custom-variant` override has proved unreliable under some dev compilers; see the `frontend-developer` skill's tooling notes. Token-based theming sidesteps the issue.

## Applying the theme without a flash

The attribute must be set before first paint, or users see a light flash on a dark preference.

- Use a small theme provider (for example `next-themes` configured with `attribute="data-theme"`), or an inline blocking script in the root layout's `<head>` that reads `localStorage` and `matchMedia('(prefers-color-scheme: dark)')` and sets the attribute.
- Add `suppressHydrationWarning` on `<html>` only, because the server cannot know the attribute value. Do not spread it further.
- Components that render differently per theme (theme-specific images, a toggle's icon) must not read the theme during server render. Render a neutral placeholder until mounted, or swap via CSS (`[data-theme="dark"] .logo-light { display: none }`), which avoids hydration mismatches entirely.

## Dark mode design rules

- **Not pure black.** Use a very dark tinted neutral (`#020617`-ish) for the page and step lighter for raised surfaces. Lighter surface = higher elevation.
- **Not pure white text.** Use an off-white (`#F1F5F9`-ish) to reduce halation on dark backgrounds.
- **Desaturate and lighten accents.** Saturated mid-tone brand colours vibrate on dark; use the 300-400 steps and a dark foreground on filled controls.
- **Borders over shadows.** Shadows barely read on dark surfaces; separate layers with surface steps and `--color-border`.
- **Re-check every pair.** Contrast does not transfer between themes; a pair that passes in light can fail in dark and vice versa.
- **Images and illustrations.** Provide dark variants for logos and diagrams with transparent backgrounds; consider a slight dim (`brightness(0.9)`) on photos. Screenshots of the product should match the active theme where they appear in-app.
- **Charts.** Read series colours from tokens at runtime; check categorical colours against the dark surface too.
- **Status surfaces.** Use deep, low-chroma tints (the 950 steps) with light status text, not the light-mode pastel surfaces.

## User-selectable accent themes

Some surfaces (chat, personal workspaces) let users pick an accent. Keep **mode** (light/dark) and **accent** orthogonal: `data-theme` for mode, `data-accent` for accent, so every accent works in both modes.

Accent themes override a small set of feature-scoped tokens, never the whole system:

```css
/* Default accent (indigo) */
:root {
  --chat-bg: #FFFFFF;
  --chat-accent: #4F46E5;
  --chat-assistant-bubble: #F1F5F9;  --chat-assistant-text: #0F172A;
  --chat-user-bubble: #4F46E5;       --chat-user-text: #FFFFFF;
}
[data-theme="dark"] {
  --chat-bg: #0F172A;
  --chat-accent: #818CF8;
  --chat-assistant-bubble: #1E293B;  --chat-assistant-text: #E2E8F0;
  --chat-user-bubble: #818CF8;       --chat-user-text: #1E1B4B;
}

/* Teal accent */
[data-accent="teal"] {
  --chat-bg: #F0FDFA;
  --chat-accent: #0F766E;
  --chat-assistant-bubble: #CCFBF1;  --chat-assistant-text: #134E4A;
  --chat-user-bubble: #0F766E;       --chat-user-text: #FFFFFF;
}
[data-theme="dark"][data-accent="teal"] {
  --chat-bg: #0F172A;
  --chat-accent: #2DD4BF;
  --chat-assistant-bubble: #1E293B;  --chat-assistant-text: #E2E8F0;
  --chat-user-bubble: #2DD4BF;       --chat-user-text: #042F2E;
}

/* Neutral accent */
[data-accent="neutral"] {
  --chat-bg: #FAFAFA;
  --chat-accent: #52525B;
  --chat-assistant-bubble: #F4F4F5;  --chat-assistant-text: #18181B;
  --chat-user-bubble: #3F3F46;       --chat-user-text: #FFFFFF;
}
[data-theme="dark"][data-accent="neutral"] {
  --chat-bg: #18181B;
  --chat-accent: #A1A1AA;
  --chat-assistant-bubble: #27272A;  --chat-assistant-text: #E4E4E7;
  --chat-user-bubble: #52525B;       --chat-user-text: #FAFAFA;
}
```

Measured bubble-text contrast (all at least 4.5:1): default 16.3 / 6.3 light, 11.9 / 5.4 dark; teal 8.4 / 5.5 light, 11.9 / 7.8 dark; neutral 16.1 / 10.4 light, 11.7 / 7.4 dark (assistant / user).

Rules:

- Offer three to five accents at most, each verified in both modes before it ships.
- Accents change decoration and bubbles, never status colours, focus rings or destructive actions.
- Persist the accent in `localStorage` (`<app>-accent`) and apply it with the same pre-paint script as the mode.
- The picker shows a live preview swatch with the accent name as text, and is a proper radio group.

## Theming one section independently

A showcase or preview section sometimes needs its own light/dark toggle (for example, a product screenshot block with its own switch). Because tokens are scoped by attribute selector, setting `data-theme="dark"` on the **section element** re-themes that whole subtree without affecting the page:

```tsx
const [mode, setMode] = useState<"light" | "dark">("light");

<section data-theme={mode} className="bg-bg text-text rounded-2xl p-8">
  {/* heading, body, toggle and screenshots all follow `mode` */}
</section>
```

Theme the **whole** section (background, headings, body text and the toggle itself), not only the image inside it; a dark screenshot floating on a light section looks broken. Drive this from component state, not from Tailwind `dark:` classes.

Two caveats with the token file as written:

- A **dark island in a light page** works as shown. A **light island in a dark page** does not, because light values are registered only on `:root` via `@theme`; the section would inherit dark values. If you need light islands, also declare the light colour values under `[data-theme="light"]`.
- Accent selectors such as `[data-theme="dark"][data-accent="teal"]` need both attributes on the same element; put `data-accent` on the section too.

## Verifying themes

- Toggle themes live (no reload) through the real theme switcher and capture each key page in every mode x accent combination you ship.
- Restart the dev server before capturing after any Tailwind or token change; hot reload can keep serving stale CSS.
- Run the token contrast test (see the `accessibility.md` reference) for every mode and accent.
- Check forced-colours mode once per release.
