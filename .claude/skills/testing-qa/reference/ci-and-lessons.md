# CI wiring and lessons learned

## Contents

- Test workflow template (GitHub Actions)
- Pre-commit hooks
- Lesson: path-filtered jobs hide latent failures
- Lesson: know whether lint is a gate
- Lesson: `asyncio.get_event_loop()` in sync helpers
- Lesson: validate an ML change against the one component it touches
- Lesson: guard model-loading config without downloading the model

## Test workflow template (GitHub Actions)

```yaml
name: tests
on:
  pull_request:
  push:
    branches: [main]
  schedule:
    - cron: "17 3 * * *"        # nightly full run, see the path-filter lesson below

permissions:
  contents: read

jobs:
  python:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        service: [service-a, service-b]       # or compute from changed paths
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_db
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U test" --health-interval 5s
          --health-timeout 5s --health-retries 10
    env:
      DATABASE_URL: postgresql+asyncpg://test:test@localhost:5432/test_db
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r services/${{ matrix.service }}/requirements-dev.txt
      - run: ruff check services/${{ matrix.service }}
      - run: ruff format --check services/${{ matrix.service }}
      - working-directory: services/${{ matrix.service }}
        run: >
          python -m pytest -m "not model_loaded and not live_llm and not smoke"
          --cov=app --cov-report=xml --cov-fail-under=80
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: coverage-${{ matrix.service }}
          path: services/${{ matrix.service }}/coverage.xml

  web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
      - run: npm run type-check
      - run: npm run lint
      - run: npx playwright install --with-deps chromium
      - run: npx playwright test --project=public
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: web/playwright-report
```

pytest exits with code 5 when no tests are collected; let that fail the job rather than masking it with `|| true`. Pin action versions to the current major (or a commit SHA) and update them deliberately.

## Pre-commit hooks

Keep them fast enough that nobody skips them:

- Ruff check and format on staged Python files.
- ESLint and Prettier on staged frontend files (`lint-staged`).
- A secret scanner (for example `gitleaks` or `detect-secrets`).
- Optionally the unit tests of the module being changed; leave integration and E2E suites to CI.

## Lesson: path-filtered jobs hide latent failures

When CI runs a service's tests only if that service changed, a broken suite can sit "green" for weeks because the job is skipped or a no-op. It surfaces the day a pull request finally touches that service, and that PR inherits the rot.

- A green check that did not run tests is not a passing test. Check the job log for the collected-test count.
- Add a scheduled full run (nightly) of every suite, and alert on its failure.
- When you touch a long-untouched service, run its suite first, before your change, so pre-existing failures are not blamed on you.

## Lesson: know whether lint is a gate

If CI runs `ruff check --exit-zero` or marks lint steps `continue-on-error`, lint is advisory and a backlog of existing issues will not block merges. Do not chase the backlog in an unrelated change; keep the files you touch clean.

Run Ruff with the same configuration CI uses, normally from the repository root. Ruff uses only the closest configuration file and does not merge parent files, so running it inside a directory with its own `pyproject.toml` `[tool.ruff]` section or `ruff.toml` applies a different rule set and reports noise CI never sees.

## Lesson: `asyncio.get_event_loop()` in sync helpers

`asyncio.get_event_loop().run_until_complete(...)` inside a synchronous fixture or helper raises `RuntimeError: There is no current event loop in thread 'MainThread'` on modern Python once an earlier async test (via pytest-asyncio) has closed the thread's loop. It passes when run alone and fails in the full suite.

```python
# GOOD: no loop is running in a sync helper, so create and close one explicitly
def run_sync[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)

# or, when you need the loop object:
loop = asyncio.new_event_loop()
try:
    result = loop.run_until_complete(coro)
finally:
    loop.close()
```

Better still, make the fixture async and let pytest-asyncio manage the loop.

## Lesson: validate an ML change against the one component it touches

A change that affects only one component can be verified against that component alone. For example, editing the example set behind an embedding-similarity classifier changes only the similarity scores, so it can be checked by embedding the examples and a set of probe inputs with the production model and comparing positive versus negative similarity, without the vector store, the rest of the pipeline, or a deploy. Write the probe set down so the check is repeatable.

## Lesson: guard model-loading config without downloading the model

Model-loading code often needs specific constructor arguments (device placement, memory flags, revision pins) whose absence only fails on real hardware. Guard them with a fake instead of shipping a large model into CI:

```python
def test_loader_should_force_cpu_and_disable_low_mem_init(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeModel:
        def __init__(self, name: str, **kwargs: object) -> None:
            captured["name"] = name
            captured.update(kwargs)

    monkeypatch.setattr("app.infrastructure.embeddings.SentenceTransformer", FakeModel)

    load_embedding_model()

    assert captured["device"] == "cpu"
    assert captured["model_kwargs"] == {"low_cpu_mem_usage": False}
```

Mark the tests that do load real weights (`@pytest.mark.model_loaded`) and exclude them from the default CI run.
