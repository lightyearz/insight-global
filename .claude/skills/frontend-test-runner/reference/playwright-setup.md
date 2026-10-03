# Playwright and lint setup for web/

## Contents

- Directory layout
- package.json scripts
- playwright.config.ts
- Auth setup project (storageState)
- Authenticated spec that skips without credentials
- Console-error collector
- Accessibility scan
- Broken-link checker
- Page object for a chat screen
- Mocking the LLM route
- ESLint flat config
- CI notes

## Directory layout

```
web/
  playwright.config.ts
  e2e/
    auth.setup.ts              # logs in once per role, saves storageState
    .auth/                     # saved sessions (gitignored)
    specs/
      smoke/                   # public pages, no auth: load, console errors, axe
      links/                   # broken-link checker
      authenticated/           # signed-in journeys
    helpers/
      routes.ts                # single registry of app routes used by specs
      console-collector.ts
      pages/                   # page objects for complex screens
```

Add `e2e/.auth/`, `playwright-report/` and `test-results/` to `.gitignore`.

## package.json scripts

```json
{
  "scripts": {
    "dev": "next dev",
    "type-check": "tsc --noEmit",
    "lint": "eslint .",
    "lint:fix": "eslint . --fix",
    "test": "vitest run",
    "e2e": "playwright test",
    "e2e:smoke": "playwright test --project=public",
    "e2e:links": "playwright test --project=links",
    "e2e:auth": "playwright test --project=authenticated",
    "e2e:report": "playwright show-report"
  }
}
```

## playwright.config.ts

```typescript
import { defineConfig, devices } from '@playwright/test';

const BASE_URL = process.env.BASE_URL ?? 'http://localhost:3000';
const USER_STATE = 'e2e/.auth/user.json';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,          // retried passes are reported as flaky; fix them
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'html',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  // start the dev server only when targeting localhost
  webServer: process.env.BASE_URL
    ? undefined
    : {
        command: 'npm run dev',
        url: 'http://localhost:3000',
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'public',
      testMatch: /specs\/smoke\/.*\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'public-mobile',
      testMatch: /specs\/smoke\/.*\.spec\.ts/,
      use: { ...devices['Pixel 7'] },
    },
    {
      name: 'links',
      testMatch: /specs\/links\/.*\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'authenticated',
      testMatch: /specs\/authenticated\/.*\.spec\.ts/,
      dependencies: ['setup'],
      use: { ...devices['Desktop Chrome'], storageState: USER_STATE },
    },
  ],
});
```

## Auth setup project (storageState)

Log in through the API, not the UI, when the session is cookie-based:

```typescript
// e2e/auth.setup.ts
import { expect, test as setup } from '@playwright/test';

const USER_STATE = 'e2e/.auth/user.json';

setup('authenticate as member', async ({ request }) => {
  const email = process.env.E2E_USER_EMAIL;
  const password = process.env.E2E_USER_PASSWORD;
  setup.skip(!email || !password, 'E2E_USER_EMAIL / E2E_USER_PASSWORD not set');

  const response = await request.post('/api/auth/login', { data: { email, password } });
  expect(response.ok()).toBeTruthy();

  await request.storageState({ path: USER_STATE });   // cookies set by the login response
});
```

If the app keeps the session in `localStorage` instead of cookies, log in with `page` in the setup test and save `page.context().storageState({ path })`. Add one setup test and one state file per role (`admin.json`, ...).

Load credentials locally from Secret Manager rather than a dotfile:

```bash
export E2E_USER_EMAIL=$(gcloud secrets versions access latest --secret=E2E_USER_EMAIL --project=<PROJECT_ID>)
export E2E_USER_PASSWORD=$(gcloud secrets versions access latest --secret=E2E_USER_PASSWORD --project=<PROJECT_ID>)
```

## Authenticated spec that skips without credentials

```typescript
// e2e/specs/authenticated/settings.spec.ts
import { expect, test } from '@playwright/test';

test.skip(!process.env.E2E_USER_EMAIL, 'E2E credentials not set');   // file scope: no context is created

test('settings page shows the signed-in email', async ({ page }) => {
  await page.goto('/settings');
  await expect(page.getByLabel('Email')).toHaveValue(process.env.E2E_USER_EMAIL ?? '');
});
```

## Console-error collector

```typescript
// e2e/helpers/console-collector.ts
import type { ConsoleMessage, Page } from '@playwright/test';

export interface CollectedErrors {
  errors: { text: string; url: string }[];
  pageErrors: Error[];
}

export function collectConsoleErrors(page: Page): CollectedErrors {
  const collected: CollectedErrors = { errors: [], pageErrors: [] };
  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() === 'error') {
      collected.errors.push({ text: msg.text(), url: msg.location().url });
    }
  });
  page.on('pageerror', (error: Error) => collected.pageErrors.push(error));
  return collected;
}

// noise you have decided to tolerate, in one reviewed place
export const KNOWN_NOISE = [/analytics/i, /gtag/i];
```

```typescript
// e2e/specs/smoke/home.spec.ts
import { expect, test } from '@playwright/test';
import { collectConsoleErrors, KNOWN_NOISE } from '../../helpers/console-collector';

test('home loads without console or page errors', async ({ page }) => {
  const { errors, pageErrors } = collectConsoleErrors(page);
  await page.goto('/');
  await expect(page.getByRole('main')).toBeVisible();

  const real = errors.filter((e) => !KNOWN_NOISE.some((re) => re.test(e.text)));
  expect(real).toEqual([]);
  expect(pageErrors).toEqual([]);
});
```

## Accessibility scan

```typescript
import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { PUBLIC_ROUTES } from '../../helpers/routes';

for (const route of PUBLIC_ROUTES) {
  test(`${route} has no WCAG A/AA violations`, async ({ page }) => {
    await page.goto(route);
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();
    expect(results.violations).toEqual([]);
  });
}
```

For a known, ticketed violation, exclude the specific selector with `.exclude('<selector>')` and a comment linking the ticket, rather than disabling the rule globally.

## Broken-link checker

```typescript
// e2e/specs/links/internal-links.spec.ts
import { expect, test } from '@playwright/test';
import { PUBLIC_ROUTES } from '../../helpers/routes';

for (const route of PUBLIC_ROUTES) {
  test(`internal links on ${route} resolve`, async ({ page, request, baseURL }) => {
    await page.goto(route);
    const hrefs = await page
      .locator('a[href]')
      .evaluateAll((anchors: HTMLAnchorElement[]) => anchors.map((a) => a.href));

    const origin = new URL(baseURL ?? page.url()).origin;
    const internal = [...new Set(hrefs.map((h) => h.split('#')[0]))].filter((h) =>
      h.startsWith(origin),
    );

    for (const href of internal) {
      const response = await request.get(href);
      expect.soft(response.status(), href).toBeLessThan(400);
    }
  });
}
```

## Page object for a chat screen

```typescript
// e2e/helpers/pages/chat-page.ts
import { expect, type Locator, type Page } from '@playwright/test';

export class ChatPage {
  readonly input: Locator;
  readonly send: Locator;
  readonly replies: Locator;

  constructor(private readonly page: Page) {
    this.input = page.getByRole('textbox', { name: 'Message' });
    this.send = page.getByRole('button', { name: 'Send' });
    this.replies = page.getByTestId('assistant-message');
  }

  async goto(): Promise<void> {
    await this.page.goto('/chat');
  }

  async ask(message: string): Promise<Locator> {
    const before = await this.replies.count();
    await this.input.fill(message);
    await this.send.click();
    const reply = this.replies.nth(before);
    await expect(reply).toHaveAttribute('data-state', 'complete');   // UI-provided completion signal
    return reply;
  }
}
```

## Mocking the LLM route

```typescript
test('shows the assistant reply', async ({ page }) => {
  await page.route('**/api/chat', (route) =>
    route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/plain; charset=utf-8' },
      body: 'Here is a scripted answer.',
    }),
  );

  const chat = new ChatPage(page);
  await chat.goto();
  const reply = await chat.ask('Hello');
  await expect(reply).toContainText('scripted answer');
});
```

`route.fulfill` delivers the body in one piece, so it does not exercise incremental rendering. Cover streaming behaviour in a component test with a mocked `ReadableStream`, or in the separately-run recorded journeys against the real model. Also mock the error path (`status: 500`, an empty body, a timeout via `route.abort('timedout')`) and assert the UI's error state.

## ESLint flat config

```javascript
// eslint.config.mjs
import playwright from 'eslint-plugin-playwright';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';
// also add the Next.js preset from eslint-config-next; its export shape depends on the Next.js version

export default tseslint.config(
  { ignores: ['.next/**', 'node_modules/**', 'playwright-report/**', 'test-results/**'] },
  ...tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-hooks/exhaustive-deps': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/consistent-type-imports': 'error',
      '@typescript-eslint/no-floating-promises': 'error',
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },
  { files: ['e2e/**/*.ts'], ...playwright.configs['flat/recommended'] },
  { files: ['**/*.js', '**/*.mjs'], ...tseslint.configs.disableTypeChecked },
);
```

## CI notes

- Install only the browsers you run: `npx playwright install --with-deps chromium`.
- Run `public` and `links` on every pull request that touches `web/`; run `authenticated` where the CI secrets exist (main branch or a protected environment).
- Upload `playwright-report/` (and `test-results/` traces) as artifacts with `if: always()`.
- Point `BASE_URL` at a preview deployment to test the built app rather than the dev server; dev-mode behaviour (React strict-mode double effects, on-demand compilation) differs from production.
