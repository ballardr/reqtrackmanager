import { defineConfig } from "@playwright/test";

// Runs against the already-up dev/test stack (tests/container/docker-compose.yml
// — frontend on :3000, backend on :8000) rather than starting its own
// webServer, so it exercises a real containerized deployment end to end.
// Never point this at the production stack (root docker-compose.yml).
//
// Two projects, not one, because a handful of specs mutate genuinely
// deployment-wide state (ServerSettings.org_label_singular/plural,
// ServerSettings.signup_mode) or a shared org/project's own settings
// (Beta-2's requirement terminology, Alpha's branding) rather than their
// own disposable fixtures — safe under the old `workers: 1` serial-only
// run, but not under real concurrency (Phase 1, docs/platform-review-2026-
// 09-plan.md's Playwright-parallelism audit). `global-state-mutators` runs
// those specs to completion first (each still reverts its own mutation via
// `afterAll`/an explicit last step, so none of the four collide with each
// other on *data*); `default`'s `dependencies` entry means Playwright won't
// start any of the fully-parallel majority of the suite until that project
// has finished. Every other spec in this suite already creates and cleans
// up its own dynamically-named org/project/user fixtures, which is what
// makes turning on `fullyParallel`/multiple `workers` for `default` safe.
//
// `global-state-mutators` itself still gets its own `workers: 1`
// (Playwright honours a per-project override of the top-level `workers`
// limit) even though its 4 files don't touch each other's data — running
// two of them at once measurably increased how often an unrelated
// upload/dialog wait or a raw `page.request.*` call timed out in
// whichever file drew the second worker. Reducing to one worker here
// lowers that rate; it isn't a complete fix for the underlying flake
// (`retries` below is), since the same class of stall was also reproduced
// running a single file alone against this stack — see docs/decisions.md's
// Phase 1 entry.
const GLOBAL_STATE_SPECS = [
  "e2e-workflows/org-label.spec.ts",
  "e2e-workflows/self-signup.spec.ts",
  "e2e-workflows/project-admin-groups-and-fields.spec.ts",
  "e2e-workflows/org-branding-override-reset.spec.ts",
];

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  workers: 2,
  // A raw `page.request.*` call (a real browser-context HTTP client, not
  // mocked) occasionally never resolves even though the backend's own
  // access log shows it received and fully answered the request — observed
  // against both a real GitHub Actions Linux runner (the CI failure this
  // retry setting was added to address, docs/decisions.md's Phase 1 entry)
  // and a local Docker Desktop run, on different specs each time, so this
  // is a transient client-side connection stall in the test harness, not a
  // deterministic app bug — a full retry (a fresh page/browser context, so
  // a fresh connection) is the correct mitigation, not a longer timeout
  // (verified locally: doubling the timeout on the exact call that hangs
  // still exhausts it, since the request never resolves at all). Off
  // locally (only CI opts in) so a genuine local failure isn't masked by 2
  // silent retries before someone notices.
  retries: process.env.CI ? 2 : 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "global-state-mutators",
      testMatch: GLOBAL_STATE_SPECS,
      workers: 1,
    },
    {
      name: "default",
      testMatch: /.*\.spec\.ts/,
      testIgnore: GLOBAL_STATE_SPECS,
      fullyParallel: true,
      dependencies: ["global-state-mutators"],
    },
  ],
});
