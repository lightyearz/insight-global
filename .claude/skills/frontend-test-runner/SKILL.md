---
name: frontend-test-runner
description: Runs and writes checks and tests for the Next.js / React / TypeScript frontend - type-check, ESLint, unit and component tests with Testing Library, Playwright E2E (projects, storageState auth, locators, web-first waits, console-error capture, mocked LLM routes) and automated accessibility scans with axe. Use when running type-check, lint or Playwright, writing or reviewing frontend tests, or fixing failing or flaky E2E specs.
---

# Frontend Test Runner

How to run and write checks for the Next.js app in `web/`. Strategy and coverage policy are in `testing-qa`; component and code standards are in `frontend-developer`; design tokens in `ui-ux-designer`.

Working configuration and helpers (Playwright config, auth setup, console collector, link checker, page objects, mocked chat route, ESLint flat config) are in [reference/playwright-setup.md](reference/playwright-setup.md).

## Commands

Run from `web/`. Script names assume the `package.json` scripts shown in the reference file.

```bash
npm run type-check                 # tsc --noEmit
npm run lint                       # eslint .
npm run lint:fix
npm run type-check && npm run lint # the pre-push minimum

npm test                           # unit and component tests (Vitest or Jest)

npx playwright test                       # all E2E projects
npx playwright test --project=public      # smoke: public pages, no auth
npx playwright test --project=links       # broken-link checker
npx playwright test --project=authenticated   # needs E2E_USER_EMAIL / E2E_USER_PASSWORD
npx playwright test e2e/specs/smoke/home.spec.ts -g "loads"   # one spec, one test
npx playwright test --ui                  # interactive mode
npx playwright test --repeat-each=5 <spec>   # flake check
npx playwright show-report

BASE_URL=https://<PREVIEW_URL> npx playwright test --project=public   # against a deployment
```

Without `BASE_URL`, the config starts `npm run dev` and targets `http://localhost:3000`. Do not run data-writing authenticated suites against production.

## TypeScript standards (tests included)

- `strict: true`; no `any` (use `unknown` plus narrowing, generics, or a precise type).
- No `as` casts except at a validated boundary, with a comment saying why. Prefer `satisfies` to check a value against a type without widening it.
- `interface` for object shapes, `type` for unions and mapped types.
- `import type` for type-only imports.

```typescript
interface UserProfile {
  readonly id: string;
  email: string;
  role: 'member' | 'admin';
}

async function getUser(id: string): Promise<UserProfile> { /* ... */ }

const routes = { home: '/', settings: '/settings' } satisfies Record<string, `/${string}`>;
```

## ESLint rules to enforce

| Rule | Level |
|---|---|
| `@typescript-eslint/no-explicit-any` | error |
| `@typescript-eslint/no-unused-vars` (`argsIgnorePattern: "^_"`) | error |
| `@typescript-eslint/consistent-type-imports` | error |
| `@typescript-eslint/no-floating-promises` (type-aware) | error, catches a missing `await` on Playwright calls |
| `react-hooks/rules-of-hooks`, `react-hooks/exhaustive-deps` | error |
| `no-console` (allow `warn`, `error`) | warn |
| `playwright/*` recommended (via `eslint-plugin-playwright`, on `e2e/**`) | error |

Recent Next.js versions move away from `next lint`; run the ESLint CLI with a flat config (`eslint.config.mjs`).

## SOLID applied to React

| Principle | In components |
|---|---|
| Single responsibility | One component per visual concern; logic in hooks (`useSession()`, `usePermissions()`) |
| Open/closed | Composition over role conditionals: `<DashboardLayout sidebar={<AdminSidebar />} />` |
| Liskov | Extend native props: `interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>` |
| Interface segregation | Pass the two fields a component needs, not the whole object |
| Dependency inversion | Inject services through context or hooks, not singleton imports, so tests can swap them |

## Unit and component tests

- Vitest (or Jest) with React Testing Library and `@testing-library/jest-dom`.
- Query the way users perceive the UI: `getByRole`, `getByLabelText`, `getByText`; `getByTestId` only as a fallback.
- Drive interactions with `@testing-library/user-event`, and assert on what is rendered, not on component state.
- Cover every state: default, loading, error, empty, disabled.
- Async Server Components are not supported by these runners; cover them with Playwright.
- Mock network at the boundary (`msw` handlers or an injected API client), not `fetch` internals.

## Playwright E2E

### Locators

```typescript
// GOOD: user-facing, doubles as an accessibility check
await page.getByRole('button', { name: 'Send' }).click();
await page.getByLabel('Email').fill(EMAIL);
await page.getByTestId('message-list').waitFor();    // when no stable accessible name exists

// BAD: breaks on styling or layout changes
await page.locator('.btn-primary.send').click();
await page.locator('button:nth-child(3)').click();
```

### Waiting

Use web-first assertions, which retry until the condition holds:

```typescript
await expect(page.getByRole('heading', { level: 1 })).toHaveText('Dashboard');
await expect(page.getByTestId('assistant-message').last()).toHaveAttribute('data-state', 'complete');
```

Never `page.waitForTimeout()`. For streamed LLM output, have the UI expose a completion signal (an attribute, or the send button re-enabling) and wait on it rather than on text length.

### Authentication

Log in once per role in a setup project and reuse the saved `storageState`; never log in through the UI in every test. Credentials come from `E2E_USER_EMAIL` / `E2E_USER_PASSWORD` (read from Secret Manager or CI secrets, never committed). Saved state files live in `e2e/.auth/` and are gitignored. Authenticated specs skip at file scope when credentials are absent, so a local run without them is green-with-skips rather than red.

### Determinism

- Mock the LLM route (`page.route('**/api/chat', ...)`) in UI tests so they do not depend on model output, cost, or latency. Keep a small, separately-run set of recorded journeys against the real model.
- Create test data through the API in `beforeEach` with unique identifiers; clean up in `afterEach`.
- Seed dismissal of overlays (cookie banner, onboarding tour) with `page.addInitScript` before navigation.
- Capture console errors and uncaught page errors on every smoke page and fail on unexpected ones.

### Accessibility

Scan every page in the smoke suite with `@axe-core/playwright` against WCAG 2.1 A/AA tags and expect zero violations. Automated scans catch only part of the problems, so also check new interactive UI for: keyboard-only operation, visible focus, correct landmarks (`main`, `nav`), labelled controls, and 4.5:1 text contrast.

## Anti-patterns

- CSS or positional selectors instead of role, label or test-id locators.
- `waitForTimeout()` or arbitrary sleeps.
- Testing component internals instead of user-visible behaviour.
- Ignoring console errors and page errors.
- Tests that depend on data left by other tests, or on the real LLM for UI behaviour.
- Large snapshot assertions instead of semantic checks.
- Hiding flakiness behind retries; a test that passed only on retry is reported as flaky and must be fixed.
- Running authenticated suites with a stale `storageState`.

## After running

1. `npm run type-check` and `npm run lint` pass with zero errors.
2. Unit and E2E tests pass, or skip only where credentials are intentionally absent.
3. No new `any`, and no `as` cast without a justification comment.
4. New UI has accessibility assertions (axe scan plus role-based locators).
5. New or fixed specs pass with `--repeat-each=5`.
