import { defineConfig } from "@playwright/test";

// Runs against the already-up dev/test stack (tests/container/docker-compose.yml: frontend on :3000, backend on
// :8000) rather than starting its own webServer, so it exercises a real containerized deployment end to end.
// Never point this at the production stack (deployments/full/docker-compose.yml).
//
// Two projects: a handful of specs mutate deployment-wide state (ServerSettings.org_label_singular/plural,
// ServerSettings.signup_mode) or a shared org/project's own settings (Beta-2's requirement terminology, Alpha's
// branding), which is unsafe under concurrency. `global-state-mutators` runs those specs first, each reverting its own
// mutation, and `default` depends on it, so the fully-parallel majority starts only after it finishes. Every other
// spec creates and cleans up its own dynamically-named fixtures, which makes `fullyParallel` safe for `default`.
//
// `global-state-mutators` has its own `workers: 1` (a per-project override): two of its files at once raised the rate
// of unrelated upload/dialog and raw `page.request.*` timeouts. That lowers the rate of the underlying stall; `retries`
// below is the mitigation (see docs/decisions.md).
const GLOBAL_STATE_SPECS = [
  "e2e-workflows/org-label.spec.ts",
  "e2e-workflows/self-signup.spec.ts",
  "e2e-workflows/project-admin-groups-and-fields.spec.ts",
  "e2e-workflows/org-branding-override-reset.spec.ts",
  // Sets the platform logo band colour (read by every sign-in page) and Alpha's own.
  "e2e-workflows/logo-band.spec.ts",
  // Sets the platform footer position and footer details (read by every signed-out page) and Alpha's own position.
  "e2e-workflows/footer-position.spec.ts",
  // Marks the seeded Gamma-2 project as a template, which hides it from the Projects list that other specs search.
  "e2e-workflows/project-admin-templates-and-reports.spec.ts",
  // Flips Gamma's org-wide "Allow ... managers to create sub-projects" security toggle mid-test, the shared-org-setting
  // class of the other files here; under `fullyParallel` it races this file's other tests, which assume the relaxed
  // path is on. See docs/decisions.md.
  "e2e-workflows/project-hierarchy.spec.ts",
  // Reads and mutates "Default Organization"'s own SSO config (`oidc_required_group`, the "reqtrack-org-admins" group
  // mapping), and its tests rely on declaration order (the required-group gate is enabled before the test that expects
  // it off). That holds only when the file runs serially; under `fullyParallel` a later test's
  // `requireOrgAdminsGroup()` can race the earlier one. Same shared-org-setting class as the others. See
  // docs/decisions.md.
  "e2e-workflows/sso.spec.ts",
  // Switches the deployment-wide file upload switch off while it runs: any spec uploading a file in parallel
  // would be refused. Each test restores the switch in its cleanup hook.
  "e2e-workflows/file-uploads-switch.spec.ts",
];

export default defineConfig({
  // Fails fast, naming the cause, when the stack's file storage is full or unreachable.
  globalSetup: "./global-setup.ts",
  testDir: "./tests",
  timeout: 30_000,
  workers: 2,
  // A raw `page.request.*` call occasionally never resolves although the backend's access log shows it was answered
  // (seen on a GitHub Actions runner and on Docker Desktop, on different specs): a transient client-side connection
  // stall. A full retry (a fresh browser context and connection) is the mitigation, not a longer timeout, because the
  // request never resolves at all. Off locally (only CI opts in) so a genuine failure is not masked by silent retries.
  retries: process.env.CI ? 2 : 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    // A Markdown field opens in Visual by default; specs type the source, so every browser starts remembering Write
    // (a spec that tests the default clears the key first).
    storageState: {
      cookies: [],
      origins: [{ origin: "http://localhost:3000", localStorage: [{ name: "reqtrack.markdownEditorView", value: "write" }] }],
    },
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
