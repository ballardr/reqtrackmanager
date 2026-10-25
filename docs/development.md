# Development Guide

This guide covers running ReqTrackManager locally to try it out or hack on it, plus the day-to-day contributor workflow: backend/frontend setup outside Docker, running the test suites, linting, and CI. For deploying a real instance, see [deployment.md](deployment.md); for the product itself, see the [README](../README.md) and [user-guide.md](user-guide.md).

## Quick start — local development / evaluation

Use the dedicated dev/test stack, **not** the root `docker-compose.yml` (that one is production-oriented and requires real secrets — see [deployment.md](deployment.md)):

```bash
cd tests/container
docker compose up --build -d
```

This starts Postgres (its own `reqtrack_test` database, isolated from any production instance), the bundled `storage` service (S3-compatible file storage, via SeaweedFS), MailHog (SMTP catcher), Keycloak (a real OIDC provider, for testing per-organisation SSO end-to-end), the backend, and the frontend. On first boot the backend automatically runs database migrations and creates a bootstrap **server admin** user and default organisation.

Once healthy:

- **Frontend UI**: http://localhost:3000
- **Backend API / Swagger UI**: http://localhost:8000/docs
- **Backend OpenAPI schema (JSON)**: http://localhost:8000/openapi.json
- **Health check**: http://localhost:8000/health
- **Prometheus metrics**: http://localhost:8000/metrics
- **MCP server** (AI-assistant access to requirements — see [mcp-server.md](mcp-server.md)): http://localhost:8100/mcp
- **MailHog UI** (view sent notification emails): http://localhost:8025
- **Docs site preview** (see [Documentation website](#documentation-website) below): http://localhost:3001/reqtrackmanager/ — the app's header **Help** link opens this local copy in this stack (`HELP_URL` in `tests/container/docker-compose.yml`; set `HELP_URL` in your shell to override). A real deployment keeps the public-site default.

Default bootstrap admin login: `admin@example.com` / `ChangeMe123!`.

**Never point this stack at the internet, and never confuse it with the production stack** (`docker-compose.yml`, repo root) — see [deployment.md](deployment.md#two-separate-compose-stacks) for why they're kept deliberately separate.

### Demo data

To populate the running stack with a realistic, presentable dataset (a fictional drone-inspection company, two projects at different lifecycle stages, requirements at varied statuses, an approved and a pending change request, discussion threads, custom fields, and a branded report template):

```bash
cd tests/container && docker compose exec backend python scripts/seed_demo_data.py
```

Idempotent (skips if already seeded) and API-driven, same as the E2E persona dataset (`scripts/seed_e2e_dataset.py`) — this is a separate script with separate, screenshot-friendly content, not a variant of the E2E fixtures. Login as `demo.admin@example.com` / `DemoDemo123!` afterward; see the script's own docstring for the other seeded personas and their roles. This is also the dataset the README's screenshots are captured from.

There's no organisation-deletion endpoint (see [docs/soc2/policies/data-retention-and-disposal-policy.md](soc2/policies/data-retention-and-disposal-policy.md)), so this script only skips rather than resets existing demo data. A future public demo instance that resets nightly would do the reset at the database level instead — `docker compose down -v && docker compose up -d --build` against a dedicated demo compose stack, then re-run the seed script — the same pattern used below to get back to a clean slate.

## Backend

```bash
cd tests/container
docker compose up -d db   # needs the dev/test Postgres running (reqtrack_test)

cd ../../backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://reqtrack:reqtrack@localhost:5432/reqtrack_test
uvicorn app.main:app --reload --port 8000
```

Migrations run automatically on startup. To run them manually, or to create a new one: `python scripts/db.py upgrade head` / `python scripts/db.py revision -m "..."` (from `backend/`, venv active) — not bare `alembic <command>`. A first-party module's own migrations live colocated with the rest of that module's code (e.g. `app/modules/compliance/migrations/`, not the flat `backend/alembic/versions/` every module used to share) rather than in one place, and Alembic's own static `alembic.ini` config can't see that dynamically — the wrapper is what actually resolves every registered module's migration directory before dispatching to Alembic, so it still walks the full chain correctly. See [docs/modules.md](modules.md)'s own migration section for the full module-authoring convention.

**Backend tests** live under `backend/tests/` (core/cross-cutting) and, for a first-party module, colocated at `backend/app/modules/<key>/tests/` instead (Compliance's own tests are there, not in `backend/tests/`, as of a plans/completed/compliance-module-plan.md Phase 11 follow-up) — `pytest` from `backend/` discovers both automatically, no separate invocation needed. They run against their own dedicated `reqtrack_pytest_test` database, never `reqtrack_test` (the dev/demo database the stack above and Playwright use) — `backend/tests/conftest.py` unconditionally rewrites whatever `DATABASE_URL` it's given to that database name (same host/port/user/password, just a different name) before any test runs, and creates it automatically if it doesn't exist yet. This is deliberate: the suite drops and recreates the entire schema at the start of every session and truncates every table after every test, which used to make `reqtrack_test` unsafe to run pytest against while also using it for manual/demo testing (see `docs/decisions.md`) — pointing pytest at its own database removes that conflict entirely, regardless of what `DATABASE_URL` you pass it. `tests/conftest.py`'s own `*_test`-suffix guard still applies as a backstop (it refuses to start against a database not ending in `_test`).

**Storage canary.** If the file storage the stack uses is full or unreachable (the Docker VM disk filling with build cache is the usual cause, and shows up as unrelated upload specs failing with a 500), the backend test `tests/test_storage_health.py::test_real_configured_storage_accepts_writes` and the Playwright `globalSetup` (`tests/playwright/global-setup.ts`, via `GET /api/v1/system/storage-health`) fail up front naming the cause. Free space with `docker builder prune -af`.

```bash
cd tests/container && docker compose up -d db   # provides both reqtrack_test and (auto-created) reqtrack_pytest_test
cd ../../backend && source .venv/bin/activate
DATABASE_URL=postgresql://reqtrack:reqtrack@localhost:5432/reqtrack_test pytest -n 4 -q   # actually runs against reqtrack_pytest_test_gw0..gw3
```

Run the full suite with `-n 4`, as CI does (`pytest-xdist`, in `requirements.txt`): each worker gets its own database (`reqtrack_pytest_test_gw0`, `_gw1`, ...), so they never interfere. The full suite takes about 15 to 25 minutes that way and about 95 minutes without `-n`. Use plain `pytest -q` for a single file or test, and never start a second pytest run while one is going: two runs share the same databases.

Or run them inside the dev/test stack's own backend container:

```bash
cd tests/container && docker compose exec backend pytest -n 4 -q
```

Because pytest never touches `reqtrack_test`, running it doesn't disturb the dev/test stack's own manually-seeded data, demo data, or bootstrap admin user — no restart or reseed needed afterward, and it's safe to run pytest and use the UI/Playwright against the same running stack at the same time.

**Linting** (N-E-04): `ruff` is configured in `backend/pyproject.toml` — `ruff check app` (or `tests`) from `backend/`. `B008` (function calls in argument defaults) is deliberately disabled since FastAPI's `Depends(...)` dependency-injection idiom is exactly that pattern.

## Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000, proxies to VITE_API_BASE_URL (default http://localhost:8000)
npm run build    # type-checks with tsc, then builds
npm run lint     # ESLint (N-E-07): TypeScript + React Hooks + Fast Refresh rules
npm run storybook       # component explorer at http://localhost:6006, with a light/dark theme toggle
npm run build-storybook # static Storybook build
npm run test-storybook  # runs every story as an automated test (real Chromium via Playwright), both themes included
npm run test-storybook -- --coverage   # same, plus a v8 coverage report (frontend/coverage/) — needs `npx playwright install --with-deps chromium` first if you haven't run Storybook/its tests before
```

Coverage today only reflects the files actually exercised by a story (`*.stories.tsx`) — most page-level logic is instead covered by the Playwright E2E suite below, which this number doesn't measure, so don't read a low frontend-coverage % as "untested."

### Changing frontend dependencies

CI (`ci.yml`) and `frontend/Dockerfile` both install with Node 24; `frontend/.nvmrc` pins the same major version for local use (`nvm use` from `frontend/`, or let `nvm`'s shell integration auto-switch on `cd`). Keep all three in lockstep if Node is bumped again in future — a locally-installed Node on a different major version bundles a different npm major version, which can resolve transitive optional dependencies differently and write a `package-lock.json` that *looks* complete but that a different npm version's `npm ci` rejects with "Missing: `<pkg>` from lock file" — the lockfile is valid, just for a different npm version. See [decisions.md](decisions.md) for a real instance of this.

Playwright is the exception to "caret ranges are fine": `playwright` (`frontend/`) and `@playwright/test` (`tests/playwright/`) are pinned to exact versions, and the matching `mcr.microsoft.com/playwright:vX.Y.Z-noble` image tags in `ci.yml` must be bumped in the same change (the npm package and browser build must be the same release, or the browser fails to launch and the run executes zero tests). `scripts/check-playwright-image-sync.py` enforces this: it runs as the first step of the `frontend` and `e2e-tests` CI jobs and in the pre-commit hook when `ci.yml` or either lockfile is staged.

After adding, removing, or bumping any dependency in `frontend/package.json`, regenerate the lock file with:

```bash
frontend/scripts/sync-lockfile.sh                    # sync package-lock.json to the current package.json
frontend/scripts/sync-lockfile.sh some-package@1.2.3  # add/bump a package — args pass through to npm install
```

It refuses to run if the active Node's major version doesn't match `frontend/.nvmrc`, then reinstalls from scratch and re-verifies the result with `npm ci`.

A pre-commit hook also backstops this automatically: `npm install` in `frontend/` wires up `core.hooksPath` to the repo's tracked `.githooks/` directory (via the `postinstall` script), and `.githooks/pre-commit` runs `npm ci --dry-run` (fast, writes nothing to disk) whenever `frontend/package.json` or `package-lock.json` is staged, blocking the commit if they're out of sync — the same hook also covers `docs/website/package.json`/`package-lock.json` (see [Documentation website](#documentation-website) below).

## Documentation website

The public documentation site lives at [docs/website/](../docs/website/) (Docusaurus), covering everything in [docs/plans/completed/docs-website-plan.md](plans/completed/docs-website-plan.md)'s "Site structure." To preview it locally with live reload:

```bash
cd docs/website
npm install
npm start   # http://localhost:3000 (a separate dev server — stop the app's own frontend dev server first, or pass --port)
```

`npm run build` produces the static site in `docs/website/build/` and fails on any broken internal link or anchor (`onBrokenLinks`/`onBrokenAnchors: 'throw'` in `docusaurus.config.ts`) — this is what CI's `docs` job runs. `npm run serve` serves that production build locally (what the `docs` service in the dev/test Compose stack below also does, so a container-based preview exercises the same static output GitHub Pages will).

For a preview that doesn't need a local Node install, or to see it alongside the rest of the running stack, the dev/test Compose stack above also runs it as the `docs` service (`docker compose up --build -d docs` from `tests/container/`) — see [Quick start](#quick-start--local-development--evaluation) above for the URL. It has no `depends_on`: the docs site is fully static and independent of `db`/`backend`/everything else in that stack.

Changing `docs/website/package.json` follows the same lockfile-sync discipline as the frontend: run `docs/website/scripts/sync-lockfile.sh` (it refuses to run under the wrong Node major version, per `docs/website/.nvmrc`) rather than a bare `npm install`.

## Performance profiling

[perf/README.md](../perf/README.md) describes the portable profiling runner (`perf/run_profile.sh <host-label> --plan|--quick|--full`): an isolated Compose project, dataset tiers from 30 to 20,000 requirements per project, Locust scenarios, and anonymised results bundles under `perf/results/`. It is run by hand on the hosts that matter; CI never runs timed performance tests, only the tests that pin its safety and the dataset generator (`backend/tests/test_perf_runner.py`, `test_perf_dataset.py`).

To see where the backend's memory, CPU or database statements go, add `--profiling cpu|heap` to a run or merge `docker-compose.profile.yml` over the development stack (the `profile` image target with memray and py-spy, and `PROFILE_MODE`, which writes per-route statement counts as files and adds no endpoint); see "Profiling the backend" in [perf/README.md](../perf/README.md). The tests that pin it are `backend/tests/test_profiling.py` and `test_perf_runner.py`.

## End-to-end tests

Requires the dev/test stack running:

```bash
cd tests/container && docker compose up --build -d

cd ../playwright
npm install
npx playwright install --with-deps chromium
npm test
```

**Writing specs that survive a shared, growing database.** The e2e data
persists between runs and grows with every disposable project/requirement a
spec creates, so:

- Open seeded projects and requirements with `openProject`,
  `openRequirementByName` or `openRequirementByCode` (in
  `tests/e2e-workflows/helpers.ts`). They search first, so they work no
  matter which page of a paginated list the row lands on. Never click a
  name you assume is on page one.
- Clean up shared state you change with `onCleanup(fn)` plus
  `installCleanupHook()` at the top of the `describe`. Use API calls with
  `apiHeaders(request, email)`, never `page`. This runs in `afterEach`,
  which still runs when a test times out; a `finally` in the test body
  doesn't get the chance, because the page is already closed.
- If a test writes to a project in bulk or changes its structure (imports,
  exports, stage approval, renames), use its own project from
  `createDisposableProject`, which archives it afterwards. Likewise, never
  deactivate, ban or re-prefer (view mode, collapsed sections) a shared
  persona that other specs log in as. Create a throwaway account, or set
  the preference explicitly and reset it in `onCleanup`.
- Await a save before reloading (`clickAndAwaitSave`), or the reload can
  cancel it.
- Keep each test well inside its 30s budget, aiming for under about 60%
  locally, since CI runners are slower. Split long journeys, and do setup
  that isn't under test through the API.

## Continuous integration

`.github/workflows/ci.yml` runs on every push/PR to `main` (and on demand via `workflow_dispatch`):

- **`frontend`** — lint, type-check + build, then the Storybook/Vitest suite above with coverage (`npm run test-storybook -- --coverage`), reported as a check via a JUnit report plus a job-summary percentage and a downloadable HTML report.
- **`backend-tests`** — the full backend pytest suite with coverage (check + job-summary percentage + downloadable HTML report) against the real dev/test Docker Compose stack (`tests/container/`), the same one you run locally, then `ruff` lint. Fails if line coverage drops below the `--cov-fail-under` figure in `ci.yml` (the published figure minus two points; raise it when coverage rises, never lower it to pass a run).
- **`e2e-tests`** — the full dev/test stack, the mcp-server's own pytest suite and `ruff` lint, then the full Playwright E2E suite.
- **`dependency-scan`** — `pip-audit` on `backend/requirements.txt` and `mcp-server/requirements.txt` (resolves transitive packages too) and `npm audit --omit=dev --audit-level=high` on the frontend and Playwright lockfiles. The documentation site's audit is reported but not gating while Docusaurus's `braces` dependency has no patched release. A finding is fixed by upgrading the package; there is no ignore list. To reproduce locally: `pip install pip-audit && pip-audit -r backend/requirements.txt`, and `npm audit --omit=dev` in the folder.
- **`publish-badges`** — runs after both jobs above (`needs:`), regardless of whether they passed (best-effort; never fails the pipeline). Turns each side's coverage/JUnit output into the four `shields.io` endpoint badges at the top of the README (backend tests + coverage, Storybook tests, frontend coverage), and pushes them to a dedicated `badges` branch. A dedicated job rather than a step inside `frontend`/`backend-tests` specifically because those two run in parallel — either publishing its own badges independently would force-push over the other's files nondeterministically depending on which finished last.
- **`image-scan`** — no `needs`, so it runs alongside the test jobs and fails within minutes rather than after the ~40 minute suites. Builds the production backend/frontend/mcp-server/docs-site images (the docs image with a `/docs/` base path, smoke tested) and scans every image with [Trivy](https://trivy.dev): a HIGH or CRITICAL finding that has a fix fails the job. To reproduce, `docker run --rm -v /var/run/docker.sock:/var/run/docker.sock ghcr.io/aquasecurity/trivy:0.75.0 image --severity HIGH,CRITICAL --ignore-unfixed <image>`. A base-image finding is fixed by moving the base image or running `apk upgrade` in the Dockerfile, never an ignore file.
- **`version`** — computes the [GitVersion](https://gitversion.net/) SemVer (`GitVersion.yml`, `mode: ContinuousDeployment` — see that file's own comment for why not `Mainline`, which GitVersion 6 removed) and the build date once, so every image leg tags and labels identically.
- **`docker-build`** — gated on `frontend`, `backend-tests`, `e2e-tests`, `dependency-scan`, `image-scan` and `version` passing. A matrix of the five production images (`backend`, `backup`, `frontend`, `mcp-server`, `docs`) × `amd64` and `arm64`, each leg on a native runner of its architecture (`ubuntu-latest`, `ubuntu-24.04-arm`) rather than under QEMU. Every leg builds on every run, pull requests included, so an architecture-specific build break fails the PR. The `arm64` legs also load the image and run [`scripts/smoke_test_image.sh`](../scripts/smoke_test_image.sh) (the backend starts against a throwaway PostgreSQL, runs migrations, logs in and lists projects; the others start and answer on their health/static endpoints) and the same Trivy gate as `image-scan`; only a leg that passes pushes its digest (untagged), and never on a pull request. Run the smoke test yourself on any Docker host with `scripts/smoke_test_image.sh backend <image> [expected-arch]`. Unit, backend and Playwright tests stay `amd64`-only; the smoke test is the `arm64` gate.
- **`docker-publish`** — runs on `main` only, after every `docker-build` leg passed. Assembles each image's two digests into one multi-arch manifest list tagged with the SemVer, the commit SHA and `latest`, pushes to `ghcr.io/<owner>/<repo>-{backend,backup,frontend,mcp-server,docs}`, and fails if either platform is missing from a result. See [deployment.md](deployment.md#obtaining-container-images) for how to point `docker-compose.yml` at a published image instead of building locally.

See the [README's Code Quality Rules](../README.md#code-quality-rules) for the conventions all of the above is expected to follow.

### Testing the pipeline locally with `act`

[`act`](https://github.com/nektos/act) (`brew install act`, or see its own install docs) runs GitHub Actions workflows locally against your own Docker daemon — useful for catching a broken workflow file (bad YAML, a wrong step reference, a job that only fails under CI's actual environment) without pushing and waiting on a real run. This project's CI has genuinely been debugged this way before — see `ci.yml`'s own comments on the `continue-on-error` steps and the demo-data seeding fix, both found via local `act` runs surfacing a real gap that individual local testing hadn't.

```bash
act -l                                                              # list every job act sees in ci.yml
act push -j frontend -P ubuntu-latest=catthehacker/ubuntu:act-latest
act push -j backend-tests -P ubuntu-latest=catthehacker/ubuntu:act-latest
```

A few things worth knowing before you run it:

- **The `-P ubuntu-latest=...` flag avoids an interactive prompt.** The very first time `act` runs, it asks you to pick a runner-image size (Large/Medium/Micro) and hangs waiting for input if stdin isn't a real terminal (e.g. run from a script or an agent). Pinning `catthehacker/ubuntu:act-latest` (the "Medium" image, ~500MB, matches most of what real `ubuntu-latest` provides) up front skips the prompt entirely; add `-P ubuntu-latest=...` to every invocation, or run `act` once interactively first and let it write your choice to `~/.actrc`.
- **`frontend`'s Playwright/Chromium step needs a bigger `/dev/shm`.** `act` runs your job as a plain `docker run` container on top of your own Docker daemon (unlike a real GitHub-hosted runner, which is a full VM, not a nested container) — a plain container's default 64 MB `/dev/shm` is too small for headless Chromium, which crashes on launch and leaves the test step hanging indefinitely rather than failing outright. Add `--container-options "--shm-size=2gb --init"` (the `--init` also fixes a related symptom: without a real init process reaping zombie children, a crashed browser's defunct process can leave the parent `vitest` process hanging even after it's already finished and written its report). **Neither flag is needed in the real `ci.yml`** — this is purely an artifact of how `act` simulates a runner, not something that affects actual GitHub Actions runs, so don't add either to the workflow file itself:

  ```bash
  act push -j frontend -P ubuntu-latest=catthehacker/ubuntu:act-latest --container-options "--shm-size=2gb --init"
  ```

- **`backend-tests` and `e2e-tests` need Docker-in-Docker.** They run `docker compose` itself (the real dev/test stack) from inside the job container, so `act` needs to give it access to your host's Docker socket — pass `-v /var/run/docker.sock:/var/run/docker.sock` (already the default for most `act` setups; only worth troubleshooting if you see a "Cannot connect to the Docker daemon" error inside the job).
- **`docker-build` and `docker-publish` aren't meaningfully runnable under `act`.** They need a real `GITHUB_TOKEN` with `packages: write` to push to `ghcr.io`, an `arm64` runner for half the matrix, and GitVersion (in `version`) needs real commit history — the push steps fail without genuine registry credentials (expected, not a bug to chase). Test the image itself with `scripts/smoke_test_image.sh` instead.
- **`dorny/test-reporter` and `actions/upload-artifact` fail under `act` for an unrelated reason**: they need a real `ACTIONS_RUNTIME_TOKEN`, which `act` doesn't provide. This is exactly why those steps (and the equivalents in `frontend`) have `continue-on-error: true` — the real pass/fail signal for each job is always the actual test command's own exit code, not these reporting/artifact conveniences layered on top.
