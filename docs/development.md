# Development Guide

This guide covers running ReqTrackManager locally to try it out or hack on it, plus the day-to-day contributor workflow: backend/frontend setup outside Docker, running the test suites, linting, and CI. For deploying a real instance, see [deployment.md](deployment.md); for the product itself, see the [README](../README.md) and [user-guide.md](user-guide.md).

## Quick start — local development / evaluation

Use the dedicated dev/test stack, **not** the root `docker-compose.yml` (that one is production-oriented and requires real secrets — see [deployment.md](deployment.md)):

```bash
cd tests/container
docker compose up --build
```

This starts Postgres (its own `reqtrack_test` database, isolated from any production instance), MinIO (S3-compatible file storage), MailHog (SMTP catcher), Keycloak (a real OIDC provider, for testing per-organisation SSO end-to-end), the backend, and the frontend. On first boot the backend automatically runs database migrations and creates a bootstrap **server admin** user and default organisation.

Once healthy:

- **Frontend UI**: http://localhost:3000
- **Backend API / Swagger UI**: http://localhost:8000/docs
- **Backend OpenAPI schema (JSON)**: http://localhost:8000/openapi.json
- **Health check**: http://localhost:8000/health
- **Prometheus metrics**: http://localhost:8000/metrics
- **MCP server** (AI-assistant access to requirements — see [mcp-server.md](mcp-server.md)): http://localhost:8100/mcp
- **MailHog UI** (view sent notification emails): http://localhost:8025
- **MinIO console** (view uploaded files): http://localhost:9001

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

Migrations run automatically on startup. To run them manually: `alembic upgrade head` (from `backend/`).

**Backend tests** run against their own dedicated `reqtrack_pytest_test` database, never `reqtrack_test` (the dev/demo database the stack above and Playwright use) — `backend/tests/conftest.py` unconditionally rewrites whatever `DATABASE_URL` it's given to that database name (same host/port/user/password, just a different name) before any test runs, and creates it automatically if it doesn't exist yet. This is deliberate: the suite drops and recreates the entire schema at the start of every session and truncates every table after every test, which used to make `reqtrack_test` unsafe to run pytest against while also using it for manual/demo testing (see `docs/decisions.md`) — pointing pytest at its own database removes that conflict entirely, regardless of what `DATABASE_URL` you pass it. `tests/conftest.py`'s own `*_test`-suffix guard still applies as a backstop (it refuses to start against a database not ending in `_test`).

```bash
cd tests/container && docker compose up -d db   # provides both reqtrack_test and (auto-created) reqtrack_pytest_test
cd ../../backend && source .venv/bin/activate
DATABASE_URL=postgresql://reqtrack:reqtrack@localhost:5432/reqtrack_test pytest -q   # actually runs against reqtrack_pytest_test
```

Or run them inside the dev/test stack's own backend container:

```bash
cd tests/container && docker compose exec backend pytest -q
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

After adding, removing, or bumping any dependency in `frontend/package.json`, regenerate the lock file with:

```bash
frontend/scripts/sync-lockfile.sh                    # sync package-lock.json to the current package.json
frontend/scripts/sync-lockfile.sh some-package@1.2.3  # add/bump a package — args pass through to npm install
```

It refuses to run if the active Node's major version doesn't match `frontend/.nvmrc`, then reinstalls from scratch and re-verifies the result with `npm ci`.

A pre-commit hook also backstops this automatically: `npm install` in `frontend/` wires up `core.hooksPath` to the repo's tracked `.githooks/` directory (via the `postinstall` script), and `.githooks/pre-commit` runs `npm ci --dry-run` (fast, writes nothing to disk) whenever `frontend/package.json` or `package-lock.json` is staged, blocking the commit if they're out of sync.

## End-to-end tests

Requires the dev/test stack running:

```bash
cd tests/container && docker compose up --build -d

cd ../playwright
npm install
npx playwright install --with-deps chromium
npm test
```

## Continuous integration

`.github/workflows/ci.yml` runs on every push/PR to `main` (and on demand via `workflow_dispatch`):

- **`frontend`** — lint, type-check + build, then the Storybook/Vitest suite above with coverage (`npm run test-storybook -- --coverage`), reported as a check via a JUnit report plus a job-summary percentage and a downloadable HTML report.
- **`backend-and-e2e`** — the full backend pytest suite with coverage (check + job-summary percentage + downloadable HTML report), `ruff` lint (backend and mcp-server), the mcp-server's own pytest suite, and the full Playwright E2E suite — all against the real dev/test Docker Compose stack (`tests/container/`), the same one you run locally.
- **`publish-badges`** — runs after both jobs above (`needs:`), regardless of whether they passed (best-effort; never fails the pipeline). Turns each side's coverage/JUnit output into the four `shields.io` endpoint badges at the top of the README, and pushes them to a dedicated `badges` branch. A dedicated job rather than a step inside `frontend`/`backend-and-e2e` specifically because those two run in parallel — either publishing its own badges independently would force-push over the other's files nondeterministically depending on which finished last.
- **`docker-build`** — gated on `frontend` and `backend-and-e2e` passing. Builds the production backend/frontend/mcp-server images, tags each with a [GitVersion](https://gitversion.net/)-computed SemVer (`GitVersion.yml`, `mode: ContinuousDeployment` — see that file's own comment for why not `Mainline`, which GitVersion 6 removed) plus the commit SHA and `latest`, and pushes all three to `ghcr.io/<owner>/<repo>-{backend,frontend,mcp-server}` — except on pull request runs, which still build (proving the Dockerfiles work) but never push. See [deployment.md](deployment.md#obtaining-container-images) for how to point `docker-compose.yml` at a published image instead of building locally.

See the [README's Code Quality Rules](../README.md#code-quality-rules) for the conventions all of the above is expected to follow.

### Testing the pipeline locally with `act`

[`act`](https://github.com/nektos/act) (`brew install act`, or see its own install docs) runs GitHub Actions workflows locally against your own Docker daemon — useful for catching a broken workflow file (bad YAML, a wrong step reference, a job that only fails under CI's actual environment) without pushing and waiting on a real run. This project's CI has genuinely been debugged this way before — see `ci.yml`'s own comments on the `continue-on-error` steps and the demo-data seeding fix, both found via local `act` runs surfacing a real gap that individual local testing hadn't.

```bash
act -l                                                              # list every job act sees in ci.yml
act push -j frontend -P ubuntu-latest=catthehacker/ubuntu:act-latest
act push -j backend-and-e2e -P ubuntu-latest=catthehacker/ubuntu:act-latest
```

A few things worth knowing before you run it:

- **The `-P ubuntu-latest=...` flag avoids an interactive prompt.** The very first time `act` runs, it asks you to pick a runner-image size (Large/Medium/Micro) and hangs waiting for input if stdin isn't a real terminal (e.g. run from a script or an agent). Pinning `catthehacker/ubuntu:act-latest` (the "Medium" image, ~500MB, matches most of what real `ubuntu-latest` provides) up front skips the prompt entirely; add `-P ubuntu-latest=...` to every invocation, or run `act` once interactively first and let it write your choice to `~/.actrc`.
- **`frontend`'s Playwright/Chromium step needs a bigger `/dev/shm`.** `act` runs your job as a plain `docker run` container on top of your own Docker daemon (unlike a real GitHub-hosted runner, which is a full VM, not a nested container) — a plain container's default 64 MB `/dev/shm` is too small for headless Chromium, which crashes on launch and leaves the test step hanging indefinitely rather than failing outright. Add `--container-options "--shm-size=2gb --init"` (the `--init` also fixes a related symptom: without a real init process reaping zombie children, a crashed browser's defunct process can leave the parent `vitest` process hanging even after it's already finished and written its report). **Neither flag is needed in the real `ci.yml`** — this is purely an artifact of how `act` simulates a runner, not something that affects actual GitHub Actions runs, so don't add either to the workflow file itself:

  ```bash
  act push -j frontend -P ubuntu-latest=catthehacker/ubuntu:act-latest --container-options "--shm-size=2gb --init"
  ```

- **`backend-and-e2e` needs Docker-in-Docker.** It runs `docker compose` itself (the real dev/test stack) from inside the job container, so `act` needs to give it access to your host's Docker socket — pass `-v /var/run/docker.sock:/var/run/docker.sock` (already the default for most `act` setups; only worth troubleshooting if you see a "Cannot connect to the Docker daemon" error inside the job).
- **`docker-build` isn't meaningfully runnable under `act`.** It needs a real `GITHUB_TOKEN` with `packages: write` to push to `ghcr.io`, and GitVersion needs real commit history (`act` does give it a full checkout of your local repo, so version *computation* works, but the push step will fail without genuine registry credentials — expected, not a bug to chase).
- **`dorny/test-reporter` and `actions/upload-artifact` fail under `act` for an unrelated reason**: they need a real `ACTIONS_RUNTIME_TOKEN`, which `act` doesn't provide. This is exactly why those steps (and the equivalents in `frontend`) have `continue-on-error: true` — the real pass/fail signal for each job is always the actual test command's own exit code, not these reporting/artifact conveniences layered on top.
