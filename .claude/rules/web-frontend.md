---
paths:
  - "web/**/*.{ts,tsx}"
---

# Next.js frontend rules (web/)

Full standards: the `frontend-developer` skill.

- TypeScript `strict: true`. Never `any`; prefer `interface` over `type` for object shapes.
- Function components with hooks only. No class components.
- Render must be pure: no `Math.random()`, `Date.now()`, or state and ref writes in the render path. Do not initialise state inside `useEffect`; use a `useState` initialiser, `useMemo`, or `useSyncExternalStore` for browser-only values. Extract helpers instead of nesting logic in JSX.
- Never add `eslint-disable` comments; fix the cause. Stable keys, never array indices. `next/image` instead of `<img>`, `next/link` for internal routes.
- Pick icons that name the concept; avoid decorative "AI magic" icons such as `Sparkles`.
- The browser never calls a backend service URL. Client code calls the app's own `app/api/*` route handlers; those call Cloud Run services through one server-only helper (conventionally `web/lib/server-fetch.ts`) that attaches the ID token in `X-Serverless-Authorization`.
- Secrets, service URLs and system prompts stay in server-only modules (`import 'server-only'`). Only values that are safe to publish may use the `NEXT_PUBLIC_` prefix.
- Never render model output or other untrusted text with `dangerouslySetInnerHTML`; go through the markdown renderer.
- User-visible strings: plain, calm language consistent with existing wording; no internal service names or implementation jargon.
- After a batch of edits run `cd web && npm run type-check && npm run lint` and fix everything reported. A single-file lint from a post-edit hook (if one is configured) does not replace the full check.
