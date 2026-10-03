# Animation and Motion

## Contents

- [When to animate](#when-to-animate)
- [Motion tokens](#motion-tokens)
- [Motion library patterns](#motion-library-patterns)
- [CSS patterns](#css-patterns)
- [Reduced motion](#reduced-motion)

## When to animate

Motion must explain something: where an element came from, what changed, or that the system is working. If it explains nothing, remove it.

Good uses: entering and leaving overlays, expanding panels, reordering lists, confirming an action (a check that draws in), loading indicators, drawing attention to a single newly-arrived item.

Avoid: animating every element on page load in app screens, bouncing or looping decoration, animating numbers in tables on every refresh, motion on each streamed token, parallax in content users read.

Rules:

- Animate `transform` and `opacity` only. Animating `width`, `height`, `top` or `margin` causes layout work and jank; use layout animations or `grid-template-rows: 0fr -> 1fr` for expand/collapse.
- Enter with ease-out (fast start, gentle stop), exit with ease-in and shorter duration than enter.
- Small, nearby changes are fast; large or far movements are slower, but nothing in app UI exceeds ~400ms.
- Marketing pages can be more expressive (staggered reveals, larger offsets); app screens stay quiet.
- Hover scale on app controls is subtle (1.02) or absent; marketing CTAs may go to 1.05.

## Motion tokens

| Token | Value | Use |
|---|---|---|
| `--duration-fast` | 150ms | Hover, focus, colour changes, small toggles |
| `--duration-base` | 200ms | Dropdowns, tooltips, popovers |
| `--duration-slow` | 300ms | Dialogs, drawers, page-section reveals |
| `--ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` | Enter and move |
| `--ease-exit` | `cubic-bezier(0.4, 0, 1, 1)` | Exit |

Tailwind: `transition-colors duration-150`, `ease-standard` (registered in `@theme`), or `duration-[var(--duration-base)]`.

## Motion library patterns

The `motion` package (formerly `framer-motion`; import from `motion/react`) covers enter/exit, stagger, layout and gesture animation. Any component using it is a client component.

```tsx
"use client";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

// Fade and rise on mount
export function Reveal({ children }: { children: React.ReactNode }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={{ opacity: 0, y: reduce ? 0 : 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.2, 0, 0, 1] }}
    >
      {children}
    </motion.div>
  );
}

// Staggered list (marketing sections; keep app lists static)
const container = { hidden: { opacity: 0 }, visible: { opacity: 1, transition: { staggerChildren: 0.06 } } };
const item = { hidden: { opacity: 0, y: 12 }, visible: { opacity: 1, y: 0 } };

<motion.ul initial="hidden" animate="visible" variants={container}>
  {features.map((f) => (
    <motion.li key={f.id} variants={item}>{f.title}</motion.li>
  ))}
</motion.ul>

// Enter and exit (toasts, panels)
<AnimatePresence>
  {open && (
    <motion.div
      key="panel"
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1, transition: { duration: 0.2 } }}
      exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.15 } }}
    />
  )}
</AnimatePresence>

// Press feedback on a marketing CTA
<motion.button whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }} transition={{ type: "spring", stiffness: 400, damping: 30 }}>
  Get started
</motion.button>
```

Notes:

- List children need stable content keys (`key={f.id}`), never indices; exit animations depend on them.
- `layout` on a `motion` element animates reorders and size changes with transforms; prefer it to animating dimensions.
- Do not start entrance animations from `opacity: 0` on content that is above the fold and critical for Largest Contentful Paint; render it visible and animate secondary content instead.

## CSS patterns

For simple cases, CSS is lighter than a library and works in server components:

```css
@keyframes fade-in {
  from { opacity: 0; transform: scale(0.98); }
  to   { opacity: 1; transform: scale(1); }
}
@keyframes slide-up {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
.animate-fade-in  { animation: fade-in var(--duration-base) var(--ease-standard) both; }
.animate-slide-up { animation: slide-up var(--duration-slow) var(--ease-standard) both; }

/* Expand/collapse without animating height */
.collapsible { display: grid; grid-template-rows: 0fr; transition: grid-template-rows var(--duration-slow) var(--ease-standard); }
.collapsible[data-open="true"] { grid-template-rows: 1fr; }
.collapsible > * { overflow: hidden; }
```

In Tailwind v4, register custom animations in `@theme` (`--animate-fade-in: fade-in 200ms cubic-bezier(0.2, 0, 0, 1) both;` plus the `@keyframes` inside `@theme`) to get an `animate-fade-in` utility.

## Reduced motion

Respect `prefers-reduced-motion: reduce` everywhere:

- Replace movement (translate, scale, parallax) with a plain opacity fade or no animation.
- Stop auto-playing loops, background video and animated illustrations, or show a static frame with a play control.
- Keep functional feedback (progress bars, spinners) but slow or simplify it.

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

Tailwind variants: `motion-safe:animate-slide-up` applies only when motion is allowed; `motion-reduce:transition-none` removes it when reduced. In `motion/react`, `useReducedMotion()` or `<MotionConfig reducedMotion="user">` at the app root.
