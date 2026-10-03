---
name: frontend-developer
description: Builds and reviews Next.js App Router frontends in React, strict TypeScript and Tailwind CSS - page and component structure, the enforced React and ESLint rules, server/client boundaries, calling IAM-protected Cloud Run backends through a server-side ID-token proxy, LLM chat UI patterns (SSE streaming, server-only system prompts, per-turn progress, staged-disclosure blocks, KaTeX math), flag-gated mock-driven UI slices, and ESLint 10 / Next 16 / Tailwind v4 gotchas. Use when building or reviewing anything under web/, adding a page or component, wiring the frontend to a backend service, building chat or agent-activity UI, or fixing lint, hydration or theming problems.
---

# Frontend Developer

Standards and patterns for the Next.js frontend in `web/`. Design tokens and visual language live in the `ui-ux-designer` skill; test mechanics (type-check, lint, Playwright, accessibility checks) live in `frontend-test-runner` and `testing-qa`.

Detail is split into reference files, one level deep:

- [reference/chat-ui-patterns.md](reference/chat-ui-patterns.md) - streaming chat UI, server-only system prompt, staged disclosure, math, progress chip, WebSocket JSON-RPC client, agent-activity feeds, chat pitfalls, recorded E2E specs.
- [reference/flags-and-mocks.md](reference/flags-and-mocks.md) - two-layer feature flags, SSR-safe runtime flags, mock chat mode, the cheap "tidy my message" pattern.
- [reference/tooling-gotchas.md](reference/tooling-gotchas.md) - ESLint 10 / Next 16 flat-config migration, Tailwind v4 dark mode with a `data-theme` attribute, hydration warnings, screenshot capture.

## Stack

- Next.js App Router, React with function components and hooks only.
- TypeScript with `strict: true`. No `any`.
- Tailwind CSS for all styling.
- Redux Toolkit with typed hooks (`useAppDispatch`, `useAppSelector`) for global client state; local state stays local.
- `react-markdown` + `remark-gfm` (plus `remark-math` + `rehype-katex` where math renders).
- An icon set such as `lucide-react` or `@tabler/icons-react`. Pick icons that name the concept; avoid decorative "AI magic" icons such as `Sparkles`.

## Core principles

1. **Accessibility first**: WCAG 2.1 AA or later, full keyboard operation, visible focus, correct ARIA, 4.5:1 text contrast.
2. **Mobile first**: build the narrow layout first, then widen (mobile, tablet, desktop).
3. **Type safety**: precise types on props, state, API payloads and function signatures.
4. **Zero lint warnings**: `npm run lint` passes clean. Never add `eslint-disable` comments; fix the cause.
5. **Server owns secrets and trust**: credentials, service URLs, ID tokens and system prompts never reach the browser bundle.
6. **Every state is designed**: default, hover, focus, active, disabled, loading, error and empty.

## React and ESLint rules (enforced)

These are enforced in `web/eslint.config.mjs`. Fix the code, not the rule.

### `react-hooks/set-state-in-effect`: no synchronous setState in an effect body
- **Lazy initializer**: for mount-time state from `localStorage` or URL params, use `useState(() => ...)` instead of `useEffect` + `setState`. Guard browser APIs (`typeof window === 'undefined'`) and watch for hydration mismatch; for values that must match SSR, use `useSyncExternalStore` (see [flags-and-mocks](reference/flags-and-mocks.md)).
- **Derive during render**: if state depends on props or other state, compute it in render (or `useMemo`). For a reset-on-prop-change, compare to the previous value in render (`if (prop !== prevProp) { setPrevProp(prop); setState(...) }`) instead of an effect.
- **Async callbacks are fine**: `setState` inside `fetch().then(...)`, `setTimeout`, or an event listener registered in an effect is allowed. Only synchronous `setState` in the effect body triggers the rule.

### `react-hooks/exhaustive-deps`: complete dependency arrays
- Include every reactive value in `useEffect` / `useCallback` / `useMemo` deps.
- Wrap functions in `useCallback` before listing them as deps.
- Declare the `useCallback` **above** the `useEffect` that references it, or TypeScript reports "used before its declaration".

### `react/no-array-index-key`: no array indices as keys
- Use stable content keys: `key={item.id}` or a composite such as `` key={`${item.type}-${item.name}`} ``.
- For static decorative arrays (confetti, placeholder rows), define a constant array with explicit `id` fields.

### Next.js rules
- `@next/next/no-img-element`: use `<Image>` from `next/image`.
- `@next/next/no-html-link-for-pages`: use `<Link>` from `next/link` for internal routes.

### Render purity
- No impure calls during render: no `Math.random()`, `Date.now()`, or writes to refs or external state in the render path. Generate IDs with `useId`, timestamps in event handlers.
- Extract helpers and subcomponents instead of nesting logic in JSX.

## Project layout (convention)

Match what the repo already has; where nothing exists yet, use:

```
web/
  app/
    (auth)/            # login, registration (route group, no URL segment)
    <feature>/         # one folder per route; page.tsx, layout.tsx, loading.tsx, error.tsx
    api/               # route handlers (server-only): BFF endpoints, SSE streams
    globals.css
    layout.tsx         # root layout
  components/
    common/            # Button, Card, Input, Dialog (reusable, no feature logic)
    layout/            # Header, Sidebar, shells
    <feature>/         # feature-specific components
  hooks/               # client hooks (useChat, useFeatureFlag)
  lib/
    api/               # typed client for the app's own /api routes
    server-fetch.ts    # server-only helper for calling backend services
    store/             # Redux Toolkit store and slices
    utils/
  e2e/                 # Playwright specs
```

## Server/client boundary and backend calls

- Backend services run on Cloud Run with `--no-allow-unauthenticated`, with no exceptions. A CI policy check should fail any change that introduces `--allow-unauthenticated`.
- The browser never calls a backend service URL. Client code calls the app's own `app/api/*` route handlers (or server actions); those call the backend through one server-only helper, conventionally `web/lib/server-fetch.ts`.
- That helper fetches a Google-signed ID token for the target service (audience = the service's base URL) and sends it as `X-Serverless-Authorization: Bearer <id-token>`. Cloud Run checks IAM against that header and passes the regular `Authorization` header through untouched, so the user's own JWT can travel alongside it.
- The backend still verifies the user JWT (FastAPI bearer dependency or middleware). IAM is the outer boundary; application auth is the second.
- Mark server-only modules with `import 'server-only'` so an accidental client import fails the build.
- Service URLs come from server-side env vars (no `NEXT_PUBLIC_` prefix). Anything prefixed `NEXT_PUBLIC_` is inlined into the browser bundle at build time.

A sketch of the helper is in [chat-ui-patterns](reference/chat-ui-patterns.md#calling-backend-services-from-the-server). Deployment, service accounts and the invoker role: `cloud-run-deploy` and `devops-infrastructure`.

## LLM chat UI (summary)

Full patterns in [reference/chat-ui-patterns.md](reference/chat-ui-patterns.md). The non-negotiables:

- The system prompt lives in a server-only module imported only by the chat route handler. The route rejects any client-supplied `system` field (strict request schema). After `next build`, grepping `.next/static/` for a distinctive prompt phrase must return nothing.
- The model is called from the server (Gemini on Vertex AI via Application Default Credentials). No model API keys in the web app.
- Render model output through `react-markdown`; never `dangerouslySetInnerHTML`, never `rehype-raw` on model text.
- Model-emitted custom tags (for example `<hint>` / `<reveal>`) are parsed into typed segments and rendered as components, not as HTML.
- A single `turnPhase` state machine drives a progress chip in an `aria-live="polite"` region; the message list is `role="log"`.

## Common workflows

### Adding a page
1. Create `app/<route>/page.tsx`; keep it a Server Component unless it needs interactivity, and push `'use client'` down to the smallest leaf.
2. Add `loading.tsx` / `error.tsx` where the route fetches data.
3. Connect to Redux only for genuinely global state.
4. Add it to navigation (Header / Sidebar).
5. Check mobile, tablet and desktop widths and keyboard navigation.

### Creating a component
1. Place it in `components/<category>/`; export from the folder's `index.ts` if the repo uses barrels.
2. Define a props `interface`; no `any`, no `React.FC` needed.
3. Style with Tailwind using design tokens from `ui-ux-designer`; do not hardcode hex values.
4. Cover every state (default, hover, focus, disabled, loading, error, empty).
5. Verify keyboard and screen-reader behaviour.

### Integrating a backend endpoint
1. Define request and response types (validate untrusted responses at the boundary, for example with `zod`).
2. Add or extend an `app/api/*` route handler that calls the service through `server-fetch`.
3. Call that route from a typed client in `lib/api/`.
4. Handle loading, error (with a retry where it makes sense) and empty states.
5. Update Redux only if the data is global.

## Verification

After a batch of edits, from `web/`:

```bash
npm run type-check && npm run lint
npx playwright test            # when behaviour or flows changed
```

Fix everything reported. A clean single-file lint (for example from a post-edit hook) does not replace the full run. Test-writing conventions: `frontend-test-runner`.

## Self-review checklist

- [ ] Semantic HTML and a correct heading hierarchy
- [ ] Keyboard operable, visible focus, ARIA correct, contrast meets AA
- [ ] Responsive at mobile, tablet and desktop widths
- [ ] Loading, error and empty states handled
- [ ] No unnecessary re-renders, no oversized client bundles (keep `'use client'` leaves small)
- [ ] Types precise; no `any`; no `eslint-disable`
- [ ] No secret, service URL, ID token or system prompt reachable from client code
- [ ] User-visible strings are plain, consistent with existing wording, and free of internal jargon
- [ ] Matches existing project conventions and the design tokens in `ui-ux-designer`

## After completing a feature

Use the `project-manager` skill to update the project's progress tracker and documentation, then report the files changed, what was verified (commands run and results) and suggested next steps.
