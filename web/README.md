# Health Briefing web

Next.js 16 (App Router), React 19, TypeScript (strict), Tailwind CSS v4 and lucide-react. The data contract is
`src/lib/types.ts`; see `../docs/CONTRACT.md`.

## Run

```bash
npm install
npm run dev                 # http://localhost:3000, proxies /api/* to API_BASE_URL (default http://localhost:8080)
npm run dev:mock            # http://localhost:3001, no backend: in-browser mock of the API (src/mocks/*.json)
```

| Variable | Default | Purpose |
|---|---|---|
| `API_BASE_URL` | `http://localhost:8080` | FastAPI base URL for the `/api/:path*` rewrite. Read by `next dev` / `next build` (baked into the build). `NEXT_PUBLIC_API_BASE_URL` is accepted as a fallback. |
| `NEXT_PUBLIC_API_MODE` | `api` | `api` calls the backend; `mock` uses `src/lib/mock/` with the JSON in `src/mocks/`. Build-time. |

The browser only calls relative `/api/*` URLs, so the API needs no CORS entry for the web origin when it is proxied.
The acting user (no auth) is kept in `localStorage` and sent as `X-User-Id`.

## Pages

- `/`: briefings table with user and status filters.
- `/briefings/new`: condition autocomplete, region, and recorded conditions as chips in replay mode.
- `/briefings/[id]`: Research (live agent steps over SSE), Review (option selection and conflict decisions), Report
  (summary, key takeaways, timeline, options, conflict log, sources with dates, audit log; print stylesheet).

## Checks

```bash
npm run lint && npm run type-check && npm run build
```

E2E (`e2e/flow.spec.ts`) runs the full flow against a running stack (API in replay or live mode plus the web app):

```bash
E2E_BASE_URL=http://localhost:3000 npm run e2e      # CHROMIUM_PATH=/path/to/chrome to use a preinstalled browser
```

Screenshots of the mock UI: start `npm run dev:mock`, then
`BASE_URL=http://localhost:3001 SCREENSHOT_DIR=./screenshots npm run screenshots:mock`.

## Mock data

`src/mocks/*.json` are contract-valid (`Briefing`, `User`, `ReplayManifest`) and use real public PubMed and MedlinePlus
records (titles, PMIDs, DOIs and dates as retrieved on 3 October 2026). In this public copy, abstracts from publishers
outside the open-licence allowlist are cut down to the sentences quoted as evidence (see `fixtures/README.md`);
quotes remain verbatim spans of those excerpts. The treatment options, conflicts and report text are illustrative UI data, not a clinical summary.

## Docker

```bash
docker build -t health-briefing-web --build-arg API_BASE_URL=http://api:8080 .
docker run -p 3000:3000 health-briefing-web          # non-root, honours PORT
```
