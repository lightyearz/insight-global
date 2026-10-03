# Feature flags, mock modes and cheap pre-processing

How new UI ships dark in production yet stays fully demoable, screenshot-able and reviewable offline.

## Contents

- [Flag-gated, mock-driven UI slices](#flag-gated-mock-driven-ui-slices)
- [SSR-safe runtime flags with useSyncExternalStore](#ssr-safe-runtime-flags-with-usesyncexternalstore)
- [Mock chat mode](#mock-chat-mode)
- ["Tidy my message": cheap query reformatting](#tidy-my-message-cheap-query-reformatting)

## Flag-gated, mock-driven UI slices

Ship every new surface behind two independent switches:

1. **Feature flag, two layers.**
   - Build layer: `NEXT_PUBLIC_FF_<NAME>=true` (or `NODE_ENV === 'development'`) decides whether the feature can exist in this bundle.
   - Runtime layer: a `localStorage` key turns it on in one browser.
   - Both must be true, so a production build without the env var is untouched no matter what is in anyone's storage.
2. **Mock flag.** A separate switch that makes the feature play a scripted timeline instead of calling real backends.

Shape of the code:

- A pure `is<Thing>Enabled()` function that works outside React and returns `false` on the server (`typeof window === 'undefined'`), so SSR never renders the flagged UI and there is no hydration mismatch.
- A hook that reads the flag reactively (next section) and, when the mock flag is on, drives the component from a fixture timeline.
- Place both in `lib/<feature>/`, next to the feature they gate.

`NEXT_PUBLIC_*` values are inlined at build time, and only for literal property access. `process.env.NEXT_PUBLIC_FF_THING` works; `process.env[name]` built from a variable is `undefined` in the browser.

Result: production stays unchanged while reviewers, screenshots and demo videos see the full feature.

## SSR-safe runtime flags with useSyncExternalStore

For a `localStorage`-backed override that must react to changes (including from other tabs), use `useSyncExternalStore` instead of `useState` + `useEffect`. The server snapshot is `false` (no hydration mismatch), and there is no `react-hooks/set-state-in-effect` warning.

```ts
// lib/thing/flag.ts
import { useSyncExternalStore } from 'react';

const BUILD_ENABLED =
  process.env.NEXT_PUBLIC_FF_THING === 'true' || process.env.NODE_ENV === 'development';
const STORAGE_KEY = 'ff:thing';
const CHANGE_EVENT = 'ff-change';

export function isThingEnabled(): boolean {
  if (!BUILD_ENABLED || typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false; // storage blocked (private mode, sandboxed iframe)
  }
}

export function setThingEnabled(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(STORAGE_KEY, '1');
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore: flag simply stays off
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('storage', onChange); // fires only in OTHER tabs
  window.addEventListener(CHANGE_EVENT, onChange); // same-tab changes
  return () => {
    window.removeEventListener('storage', onChange);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

export function useThingEnabled(): boolean {
  return useSyncExternalStore(subscribe, isThingEnabled, () => false);
}
```

The browser's `storage` event does not fire in the tab that made the change, hence the custom event.

## Mock chat mode

A `useMockChat` flag (same two-layer shape as any demo-mode flag). When on, the chat hook:

- skips the classifier and `/api/chat` entirely;
- walks the same `turnPhase` sequence with artificial delays (`classifying`, then `thinking`, then `streaming`);
- streams a curated fixture response word by word;
- uses the fixture's expected classification for the pills and chips.

Why it matters:

- Screenshots and demos of every state, including error, approval-pending and guardrail-triggered states, render deterministically even when a live backend is down or misbehaving.
- Theme-by-state screenshot matrices are captured by driving the real theme switcher live, without reloading. A reload resets the conversation state you are trying to capture.
- Features that piggy-back on the chat hook (for example the tidy step below) must also short-circuit in mock mode, so mock mode makes no network calls.

## "Tidy my message": cheap query reformatting

Optional pre-processing that cleans up a short user message (typos, run-on phrasing) before it is sent to the main model.

- Run it on the server with a small, cheap model (for example a Flash-Lite tier Gemini model on Vertex AI), never from the browser.
- Gate it to short messages (roughly 2 to 200 characters); long messages pass through unchanged.
- Run it in parallel with the classifier so it adds no latency, and never let it block the reply: on any error or timeout, use the original text.
- Always keep `originalContent` alongside the cleaned text. Show a subtle "show original" affordance only when the cleaned text differs.
- Ship it behind a build-time flag (for example `NEXT_PUBLIC_ENABLE_QUERY_TIDY`), off in production until evaluated (see `llm-evaluation`).
- Mock chat mode skips the call.
