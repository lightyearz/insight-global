# Tooling gotchas

Problems that cost real time to diagnose, with the fix that held.

## Contents

- [ESLint 10 with Next 16 (flat config)](#eslint-10-with-next-16-flat-config)
- [Tailwind v4 dark mode with a data-theme attribute](#tailwind-v4-dark-mode-with-a-data-theme-attribute)
- [Screenshots after CSS changes](#screenshots-after-css-changes)
- [Hydration warnings from browser extensions](#hydration-warnings-from-browser-extensions)
- [Old patterns](#old-patterns)

## ESLint 10 with Next 16 (flat config)

- `FlatCompat` from `@eslint/eslintrc` crashes ESLint 10 with a circular-JSON error when it loads the `next/typescript` shareable config. Use the native flat configs that `eslint-config-next` 16 and later ship: `eslint-config-next/core-web-vitals` and `eslint-config-next/typescript`.
- `eslint-plugin-react` 7.37.x calls the removed `context.getFilename()` while auto-detecting the React version. Pin the version in settings (`settings: { react: { version: '19.2' } }`, matching `package.json`) until the plugin's next major removes the call.
- `eslint-plugin-react-hooks` 7.1.x turns on the React Compiler advisory rules by default: `set-state-in-effect`, `purity`, `immutability`, `preserve-manual-memoization`. On an existing codebase, set them to `warn` for the migration only, reduce the count in every PR, then promote them back to `error` and keep `--max-warnings 0`.
- Next 16 no longer provides `next lint`; the `lint` script calls `eslint` directly.

```js
// web/eslint.config.mjs
import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    settings: { react: { version: '19.2' } },
    rules: {
      'react/no-array-index-key': 'error',
      'react-hooks/exhaustive-deps': 'error',
      // Migration only: ratchet to zero, then back to 'error'.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/purity': 'warn',
      'react-hooks/immutability': 'warn',
      'react-hooks/preserve-manual-memoization': 'warn',
    },
  },
  globalIgnores([
    '.next/**', 'out/**', 'build/**', 'next-env.d.ts',
    'playwright-report/**', 'test-results/**',
  ]),
]);
```

## Tailwind v4 dark mode with a data-theme attribute

When the app themes through an attribute on `<html>` (`data-theme="dark"`, set by a theme provider) rather than the OS `prefers-color-scheme`, Tailwind's `dark:` variant does not follow it by default.

- The documented remedy is `@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *));` in `globals.css`. In practice this did **not** take effect under the Turbopack dev compiler: the `dark:` classes never applied, so a panel kept its light background while the surrounding theme switched its text to light (light text on a light panel). Do not rely on it without checking both `next dev` and a production build.
- Preferred: semantic design tokens as CSS custom properties, defined under `:root` and overridden under `[data-theme=dark]`, and used through Tailwind (`bg-[var(--surface-warning)]` or tokens mapped in `@theme`). Components then need no dark variants at all. Token names come from `ui-ux-designer`.
- One-off override that always works: the ancestor arbitrary variant, for example `[[data-theme=dark]_&]:bg-amber-950/40`.
- Plain CSS (for example KaTeX overrides in `globals.css`) can key on `[data-theme=dark] .katex` directly.

## Screenshots after CSS changes

`@custom-variant`, `@theme` and other Tailwind v4 config changes are compile-time. HMR can keep serving the old CSS, so screenshots regenerated right after such a change may show the previous styling. Restart the dev server (or use a fresh production build) before capturing.

## Hydration warnings from browser extensions

Some extensions rewrite the DOM after SSR (inline analytics scripts in the root layout are a common target), which React reports as a hydration mismatch.

- Confirm it is an extension: reproduce in a clean browser profile or a private window with extensions disabled. If the warning disappears, it is not your bug.
- Suppress narrowly with `suppressHydrationWarning` on the element that gets mutated (for example `<head>` and the specific `<script>`). It only applies one level deep (that element's own attributes and text), so it does not hide real mismatches elsewhere.
- Never blanket-suppress on `<body>` to silence a warning you have not diagnosed.

## Old patterns

- `FlatCompat` + `@eslint/eslintrc` bridging legacy `extends: ['next/core-web-vitals', 'next/typescript']` into a flat config. Replaced by the native flat configs above; it breaks on ESLint 10.
- `next lint` as the lint script. Replaced by calling `eslint` directly.
