# Chat UI patterns

Patterns for an LLM chat surface in a Next.js App Router app: a server-side route that streams model output over SSE, a client hook that orchestrates the turn, and a message list that renders markdown, math and model-emitted custom blocks.

## Contents

- [Suggested file layout](#suggested-file-layout)
- [The system prompt is server-only](#the-system-prompt-is-server-only)
- [Calling backend services from the server](#calling-backend-services-from-the-server)
- [Staged disclosure: model-emitted custom blocks](#staged-disclosure-model-emitted-custom-blocks)
- [Math rendering with KaTeX](#math-rendering-with-katex)
- [Per-turn progress chip](#per-turn-progress-chip)
- [Classification pills and chips](#classification-pills-and-chips)
- [WebSocket JSON-RPC client for an agent server](#websocket-json-rpc-client-for-an-agent-server)
- [Agent-activity feeds](#agent-activity-feeds)
- [Multi-participant sessions](#multi-participant-sessions)
- [Common pitfalls](#common-pitfalls)
- [Recorded E2E specs for chat scenarios](#recorded-e2e-specs-for-chat-scenarios)

## Suggested file layout

Adapt names to the repo; keep the split between server-only and client code.

| Concern | File |
|---|---|
| Chat panel shell (header, scroll container, input) | `components/chat/ChatPanel.tsx` |
| One message bubble, its metadata pills and custom-block panels | `components/chat/MessageBubble.tsx` |
| Per-turn progress chip | `components/chat/TurnProgress.tsx` |
| Markdown, math and code rendering inside a bubble | `components/chat/MessageMarkdown.tsx` |
| Stream and classifier orchestration, `turnPhase` | `hooks/useChat.ts` |
| **Server-only** system prompt text and `pickPrompt(...)` | `app/api/chat/_prompt.ts` |
| Public types only (no prompt text) | `lib/chat/types.ts` |
| SSE endpoint, server-side prompt selection, model call | `app/api/chat/route.ts` |

## The system prompt is server-only

- Keep every line of the system prompt in one module that starts with `import 'server-only'` and is imported only by route handlers. Client code may import the types, never the text.
- Prompt variants are chosen on the server: `pickPrompt({ classification, locale, ... })` inside `route.ts`. Never `fetch('/api/chat', { body: { system: '...' } })` from the client.
- Validate the request body with a strict schema (for example `zod` `.strict()`): it accepts the conversation and the user message, and rejects any `system` field or unknown key. A client that can set the system prompt can bypass every instruction in it.
- Verify after `next build`: `grep -r "<distinctive phrase from the prompt>" web/.next/static/` returns no hits. Add this as a CI step if the prompt is sensitive.
- The route calls the model from the server (for example Gemini on Vertex AI with Application Default Credentials) and streams tokens back as SSE. Use the Node.js runtime and `export const dynamic = 'force-dynamic'` for streaming routes. Model choice: `llm-models-expert`. Input and output filtering: `llm-guardrails`.

## Calling backend services from the server

Backend services on Cloud Run require IAM (`--no-allow-unauthenticated`). The Next.js server fetches an ID token for the target service and sends it in `X-Serverless-Authorization`, leaving `Authorization` free for the user's JWT, which Cloud Run forwards to the app.

Sketch (adapt error handling, caching and typing to the repo):

```ts
// web/lib/server-fetch.ts
import 'server-only';

const IDENTITY_URL =
  'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity';

async function fetchIdToken(audience: string): Promise<string | null> {
  // K_SERVICE is set by Cloud Run. Locally, services run on localhost without IAM.
  if (!process.env.K_SERVICE) return null;
  const res = await fetch(`${IDENTITY_URL}?audience=${encodeURIComponent(audience)}`, {
    headers: { 'Metadata-Flavor': 'Google' },
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(`ID token request failed: ${res.status}`);
  return res.text();
}

export async function serverFetch(
  serviceUrl: string, // base URL of the target service, from a server-side env var
  path: string,
  init: RequestInit = {},
  userJwt?: string,
): Promise<Response> {
  const headers = new Headers(init.headers);
  const idToken = await fetchIdToken(serviceUrl);
  if (idToken) headers.set('X-Serverless-Authorization', `Bearer ${idToken}`);
  if (userJwt) headers.set('Authorization', `Bearer ${userJwt}`);
  return fetch(new URL(path, serviceUrl), { ...init, headers, cache: 'no-store' });
}
```

- The audience is the receiving service's base URL. ID tokens last about an hour; cache per audience and refresh a few minutes before expiry if call volume matters.
- The web app's runtime service account needs `roles/run.invoker` on each service it calls (see `cloud-run-deploy`).
- To reach an IAM-protected service from a laptop, use `gcloud run services proxy <SERVICE> --region <REGION> --project <PROJECT_ID>` rather than opening the service up.

## Staged disclosure: model-emitted custom blocks

The system prompt can teach the model to wrap parts of an answer in custom tags that the UI renders as click-to-show panels. Example pair:

| Tag | Visual | Use for |
|---|---|---|
| `<hint>...</hint>` | Muted pill, lightbulb icon, "Show hint" / "Hide hint" | A small nudge toward the next step without solving it |
| `<reveal>...</reveal>` | Accent pill, eye icon, "Show answer" / "Hide answer" | The final answer, finished code, a complete worked solution |

Parse with one regex and a backreference so both tags share a code path:

```ts
const STAGED_TAG_RE = /<(reveal|hint)>([\s\S]*?)<\/\1>/g;

type Segment = { type: 'text' | 'hint' | 'reveal'; value: string };

function splitStaged(content: string): Segment[] {
  const segments: Segment[] = [];
  let last = 0;
  for (const m of content.matchAll(STAGED_TAG_RE)) {
    const start = m.index ?? 0;
    if (start > last) segments.push({ type: 'text', value: content.slice(last, start) });
    segments.push({ type: m[1] as 'hint' | 'reveal', value: m[2] });
    last = start + m[0].length;
  }
  if (last < content.length) segments.push({ type: 'text', value: content.slice(last) });
  return segments;
}
```

- Render segments in source order; each panel's body goes back through `MessageMarkdown`. Never inject the raw tag text as HTML.
- While streaming, an opening tag may arrive before its closing tag. Either hold the unmatched tail as plain text until it closes, or hide everything after an unmatched opening tag; do not flash the answer.
- Panels are `<button aria-expanded>` controlling a region, collapsed by default.

## Math rendering with KaTeX

- Wire `remark-math` + `rehype-katex` in `MessageMarkdown.tsx` and import `katex/dist/katex.min.css` once. New markdown features go in that one pipeline.
- Teach the model to emit `$inline$` and `$$display$$` (display math on its own paragraph).
- Single-dollar inline math mis-renders currency ("costs $5 and $10"). If the content often contains prices, set `remark-math`'s `singleDollarTextMath: false` and teach the model `$$...$$` only.
- Scope custom math styling to chat containers (`[role="log"] .katex`, `.prose .katex`) so other pages that render math are not restyled. Give inline math a subtle tinted background and display math a callout (left accent rule, more padding), with light and dark variants keyed on the theme attribute (plain CSS can target `[data-theme=dark] .katex` directly).

## Per-turn progress chip

The chat hook exposes `turnPhase: 'idle' | 'classifying' | 'thinking' | 'streaming' | 'done' | 'error'` plus timings such as `lastClassifyMs` and `firstTokenMs`. `TurnProgress` renders one tone-coded pill above the input, inside an `aria-live="polite"` region:

| Phase | Tone | Example copy |
|---|---|---|
| `classifying` | Info | "Checking your message" |
| `thinking` | Info | "Composing a response (check took {n} ms)" |
| `streaming` | Success | "Replying (first token in {n} ms)" |
| Awaiting human approval | Warning | "Waiting for approval" (supersedes the per-turn phase) |
| `error` | Danger | "Something went wrong. Try sending again." |
| `idle`, `done` | Hidden | (no chip) |

Keep the phase in one state machine in the hook; components only read it. Do not derive it from several booleans.

## Classification pills and chips

If a pre-model classifier labels each user message, render its output under the user's bubble only when there is something to show:

```tsx
{(label !== undefined || (topics?.length ?? 0) > 0) && <ClassificationRow label={label} topics={topics} />}
```

If the label pill renders but no topic chips appear, check the classifier response for an empty `topics` array before debugging the UI. That is a classifier tuning issue, not a rendering bug.

## WebSocket JSON-RPC client for an agent server

When chat talks to a long-running agent server instead of a request/response route:

- Protocol: JSON-RPC 2.0 over WebSocket. Requests carry an `id` and get exactly one response with the same `id`; server notifications (no `id`) carry streaming deltas, tool activity and turn state. Keep a pending-request map keyed by `id`, with timeouts. Background: `agentic-ai-resources`.
- Auth: browsers cannot set an `Authorization` header on a WebSocket upgrade. Have a Next.js route mint a short-lived, single-use ticket and pass it as a subprotocol value or query parameter, or use an HttpOnly cookie, or authenticate in the first frame. Never put the long-lived user JWT in the URL; URLs end up in logs.
- Expose hooks such as `useAgentClient(sessionId)` and `useObserverClient(sessionId, role)`; components never touch the socket.
- Reconnect with jittered exponential backoff and resubscribe after reconnect. Cloud Run ends WebSocket connections at the service's request timeout (at most 60 minutes), so reconnection is a normal path, not an edge case.
- When the server pauses a turn for human approval, show the waiting state and disable sending until the turn resumes or is rejected.
- Role-scoped views (an observer who may see only summaries, an admin who may see only metadata): the server filters what each role receives. The client must never receive data and then hide it.

## Agent-activity feeds

For showing what an agent is doing (lifecycle, routing, tool calls, "thinking"):

- Render process as dense, dim, single-line steps in the style of a terminal trace, not as boxed cards. Attribute each line to its actor; mark the current step with a filled pulsing dot and finished steps with a hollow ring. Only actual messages get full reading weight.
- Fold the flat event stream into one collapsible group per turn with a pure function (for example `lib/<feature>/turn-groups.ts`). It is trivially unit-testable and keeps components simple.
- Respect `prefers-reduced-motion` for the pulsing indicator.

## Multi-participant sessions

If other people can join a conversation:

- Joining is consent-first: a join request is shown to the session owner, who accepts or declines; only then does the participant appear in a presence bar and their messages render as participant messages.
- The default is private 1:1 when the feature flag is off, and the header says so.
- Visible joining and silent observation are different consent regimes. Design, flag and document them separately; never let one silently become the other.

## Common pitfalls

1. **Programmatically setting a React-controlled textarea.** Assigning `el.value` does not fire React's `onChange`. In raw DOM code (`page.evaluate`, benchmark scripts) use the native setter and dispatch an input event:
   ```ts
   const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
   setValue?.call(el, text);
   el.dispatchEvent(new Event('input', { bubbles: true }));
   ```
   Playwright's `locator.fill()` already does the equivalent; prefer it in specs.
2. **A cookie-consent banner intercepts pointer events on first paint.** In E2E specs, seed the consent record before any page script runs with `page.addInitScript(() => localStorage.setItem('<app>-cookie-consent', JSON.stringify({ essential: 'granted' /* others denied */ })))`.
3. **Hydration warnings caused by browser extensions** that mutate inline scripts after SSR. Confirm in a clean browser profile, then add `suppressHydrationWarning` only on the mutated element (it applies one level deep). Never blanket-suppress on `<body>`.
4. **Backticks inside a TypeScript template literal end it early.** Long prompt templates that need markdown code fences should build them from a constant (`const FENCE = String.fromCharCode(96).repeat(3)`) or escape each backtick; never paste a literal backtick into the template.

## Recorded E2E specs for chat scenarios

A Playwright spec that walks the main chat scenarios with video recording is the fastest way to review chat behaviour and to share it.

- Typical scenarios: a normal question answered well; a request the guardrails should redirect or refuse; an attempt to extract the system prompt (refused, nothing disclosed verbatim); a staged-disclosure block renders and expands on click; a backend error shows the error chip and recovers on retry.
- Record with `use: { video: 'on' }` in the project config for that spec. Deliberate pauses (`page.waitForTimeout(1500)`) are acceptable only in recording specs meant for humans to watch; CI specs wait on locators and assertions.
- Test credentials come from Secret Manager, never from the repo:
  ```bash
  cd web
  export E2E_USER_EMAIL=$(gcloud secrets versions access latest --secret=E2E_USER_EMAIL --project=<PROJECT_ID>)
  export E2E_USER_PASSWORD=$(gcloud secrets versions access latest --secret=E2E_USER_PASSWORD --project=<PROJECT_ID>)
  npx playwright test e2e/chat-scenarios.spec.ts --headed   # visible browser
  npx playwright test e2e/chat-scenarios.spec.ts            # headless
  npx playwright show-report
  ```
- Videos land under `test-results/<spec>-<scenario>/video.webm`, one per test. Keep `test-results/` and `playwright-report/` out of git.
