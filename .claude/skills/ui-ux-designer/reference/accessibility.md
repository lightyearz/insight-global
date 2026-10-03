# Accessibility

## Contents

- [Target](#target)
- [WCAG 2.2 AA checklist for UI work](#wcag-22-aa-checklist-for-ui-work)
- [Contrast maths and a checker](#contrast-maths-and-a-checker)
- [Focus](#focus)
- [Keyboard](#keyboard)
- [Semantics and ARIA](#semantics-and-aria)
- [Motion, zoom and user preferences](#motion-zoom-and-user-preferences)
- [Testing](#testing)

## Target

WCAG 2.2 Level AA is the floor for every screen, including internal and admin tools. Where a cheap AAA practice exists (44x44 touch targets, reduced motion), use it.

## WCAG 2.2 AA checklist for UI work

The success criteria designers most often affect:

| SC | Requirement | What to check |
|---|---|---|
| 1.1.1 Non-text content (A) | Text alternative for meaningful images and icons | `alt` describes purpose; decorative images `alt=""`; decorative icons `aria-hidden` |
| 1.3.1 Info and relationships (A) | Structure in markup, not just visuals | Headings, lists, tables, labels, fieldsets are real elements |
| 1.4.1 Use of colour (A) | Colour is not the only cue | Status, errors, chart series, links in text (underline) |
| 1.4.3 Contrast minimum (AA) | Text 4.5:1; large text (24px, or 18.66px bold) 3:1 | Every token pair in both themes, text over images |
| 1.4.4 Resize text (AA) | Usable at 200% text size | rem units, no fixed-height text containers |
| 1.4.10 Reflow (AA) | No 2D scrolling at 320 CSS px wide | Tables and code scroll inside containers |
| 1.4.11 Non-text contrast (AA) | UI component boundaries and states 3:1 | Input borders, checkbox boxes, toggle tracks, focus rings, chart lines that carry meaning |
| 1.4.12 Text spacing (AA) | No loss of content when users increase spacing | Avoid fixed heights on text boxes |
| 1.4.13 Content on hover or focus (AA) | Tooltips dismissible, hoverable, persistent | `Esc` closes; pointer can move onto the tooltip |
| 2.1.1 Keyboard (A) | Everything operable by keyboard | Custom widgets, drag-and-drop alternatives |
| 2.4.3 Focus order (A) | Logical order | DOM order matches visual order |
| 2.4.7 Focus visible (AA) | Visible focus indicator | Never remove outlines without replacement |
| 2.4.11 Focus not obscured (AA, new in 2.2) | Focused element not hidden by sticky headers, banners or chat widgets | `scroll-padding-top` equal to sticky header height |
| 2.5.7 Dragging movements (AA, new in 2.2) | Single-pointer alternative to drag | Reorder via buttons or menu as well as drag |
| 2.5.8 Target size minimum (AA, new in 2.2) | Targets at least 24x24 CSS px or spaced | Icon buttons, table row actions, close buttons |
| 3.2.6 Consistent help (A, new in 2.2) | Help mechanism in the same place across pages | Support link or chat launcher position |
| 3.3.1 / 3.3.3 Error identification and suggestion | Errors described in text with a fix | Inline field errors plus summary |
| 3.3.2 Labels or instructions (A) | Visible labels | No placeholder-only fields |
| 3.3.7 Redundant entry (A, new in 2.2) | Do not ask for the same data twice in a flow | Prefill or offer "same as above" |
| 3.3.8 Accessible authentication (AA, new in 2.2) | No cognitive test to log in | Allow paste and password managers; no copy-the-code puzzles without alternatives |
| 4.1.2 Name, role, value (A) | Custom controls expose state | `aria-expanded`, `aria-pressed`, `aria-selected`, `aria-checked` |
| 4.1.3 Status messages (AA) | Announce status without moving focus | `role="status"` / `aria-live="polite"` for toasts, save confirmations, result counts |

## Contrast maths and a checker

Contrast ratio = (L1 + 0.05) / (L2 + 0.05), where L is relative luminance of the lighter (L1) and darker (L2) colour. Luminance linearises each sRGB channel (`c <= 0.04045 ? c/12.92 : ((c+0.055)/1.055)^2.4`) and weights them 0.2126 R + 0.7152 G + 0.0722 B.

Drop-in TypeScript, usable in a Vitest test that asserts every token pair:

```ts
export function luminance(hex: string): number {
  const n = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// expect(contrast(tokens.light["text-muted"], tokens.light["surface-muted"])).toBeGreaterThanOrEqual(4.5);
```

A token-contrast test that parses the token CSS and checks a declared list of foreground/background pairs for both themes turns contrast from a review step into a CI failure. Semi-transparent colours must be composited over their actual background before measuring.

## Focus

- Use `:focus-visible` so mouse clicks do not show rings but keyboard focus always does.
- Ring: 2px solid `--color-focus-ring`, 2px offset. Use `outline`, not only `box-shadow`: box-shadows disappear in Windows forced-colours (high contrast) mode, outlines do not.
- On filled buttons whose colour equals the ring colour, the offset gap provides the separation; check the ring against the page background (3:1).
- Sticky headers: set `scroll-padding-top` on `html` to the header height so focused elements are not hidden underneath (SC 2.4.11).
- After route changes, move focus to the new page's `h1` (or a skip target) and announce the title; after closing a dialog, return focus to its trigger; after deleting an item, move focus to the next item or the list heading.

## Keyboard

- Tab reaches every interactive element in visual order; nothing non-interactive is focusable (`tabIndex` > 0 is never used).
- Provide a "Skip to main content" link as the first focusable element.
- Composite widgets (tabs, menus, listboxes, grids, radio groups) use one tab stop and arrow keys inside, per the WAI-ARIA Authoring Practices Guide; a primitive library gives you this for free.
- `Esc` closes the topmost overlay. `Enter`/`Space` activate buttons. No keyboard traps.
- Every hover-only affordance (row actions, tooltips, reveal-on-hover callouts) has a focus equivalent or is non-essential.

## Semantics and ARIA

- First rule of ARIA: use the native element (`<button>`, `<a href>`, `<input type="checkbox">`, `<dialog>`, `<details>`) before adding roles. A `div` with `onClick` is a bug.
- Landmarks: one `<header>`, `<nav>` (labelled when there are several), `<main>`, `<footer>`.
- Every page has a unique, descriptive `<title>` (Next.js `metadata.title`).
- Icon-only controls: `aria-label` on the button, `aria-hidden="true"` on the SVG.
- Visually hidden text uses the `sr-only` utility, never `display: none` (which hides from screen readers too).
- Live regions must exist in the DOM before content is injected into them, or announcements are dropped.
- For streaming text (chat, logs), announce completed units (a finished message), not every token.

## Motion, zoom and user preferences

- Respect `prefers-reduced-motion: reduce`: remove parallax, auto-playing animation and large transforms; keep short opacity fades. See the `animation-and-motion.md` reference.
- Respect `prefers-color-scheme` as the default theme when the user has not chosen one.
- Respect `forced-colors: active`: do not convey state only with background colour; borders and outlines survive, backgrounds may not.
- Never disable zoom (`user-scalable=no`, `maximum-scale=1`).
- Auto-advancing carousels and timers need pause controls; anything moving for more than 5 seconds needs a way to stop it.

## Testing

Automated tools catch only part of the issues (they cannot judge focus order, meaningful alt text or whether an error message helps); combine them with manual passes.

1. **Automated:** axe-core in Playwright (`@axe-core/playwright`) on every key page in both themes, failing CI on serious and critical violations. Mechanics live in `frontend-test-runner`. Lighthouse accessibility as a smoke check.
2. **Keyboard pass:** unplug the mouse; complete the main task flows with Tab, Shift+Tab, arrows, Enter, Space, Esc.
3. **Zoom and reflow:** 200% and 400% browser zoom; 320px viewport.
4. **Screen reader smoke test:** VoiceOver (macOS, iOS), NVDA (Windows), TalkBack (Android). Check headings list, landmarks, form labels and error announcements.
5. **Colour:** greyscale and colour-vision-deficiency simulation in browser devtools (Rendering panel, "Emulate vision deficiencies"); forced-colours emulation.
