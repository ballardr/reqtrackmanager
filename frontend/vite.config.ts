/// <reference types="vitest/config" />
import path from "node:path";

import { storybookTest } from "@storybook/addon-vitest/vitest-plugin";
import react from "@vitejs/plugin-react";
import { playwright } from "@vitest/browser-playwright";
import { defineConfig } from "vite";

// Frontend is loosely coupled to the backend (I-A-01): the API base URL is
// injected at runtime via VITE_API_BASE_URL rather than hardcoded, so the
// same build artifact works across environments.
const dirname = import.meta.dirname;

// Tier C ("federated" / Module Federation) frontend modules — module
// system follow-up, 2026-09-07 (see docs/decisions.md's "Module system
// follow-up: Tier C (Module Federation)" entries and docs/modules.md's
// "Tier C" section). The intended, documented design is for this host
// build to declare a Module Federation host config here (e.g. `@originjs/
// vite-plugin-federation`'s `federation({ name: "host", shared: ["react",
// "react-dom"] })`, configured for *dynamic* remotes — a Tier C remote's
// URL isn't known at this host's own build time, it arrives from the
// backend's manifest endpoint at runtime). **That dependency is
// deliberately not added to this file or package.json**: this repo's own
// sandboxed build/test environment had no network access to the npm
// registry to install, build, or verify it when Tier C was built (confirmed
// directly — `npm view`/`npm install` both timed out against
// registry.npmjs.org), and shipping a `vite.config.ts` importing a package
// that isn't actually installed would break every frontend typecheck/lint/
// build/test run, not just this feature, violating this repo's own
// standing "leave the suite passing" rule. `frontend/src/modules/
// federatedLoader.ts` instead implements, by hand, the same minimal
// container contract a real Module Federation remote build produces
// (`init(sharedScope)`/`get(exposedModuleName)`), using only native
// dynamic `import()` — no new dependency, so nothing here needed to
// change. See that file's own docstring for the full account, including
// the documented upgrade path (a small, scoped change to that one file
// only) once a deployment building this repo has normal npm registry
// access and wants the real plugin's shared-dependency *version*
// negotiation this hand-rolled substitute deliberately doesn't attempt.

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000,
  },
  preview: {
    host: true,
    port: 3000,
  },
  // Runs each Storybook story as a Vitest browser test (real Chromium via
  // Playwright), so `npm run test-storybook` catches stories that fail to
  // render or fail their play functions/assertions — not just a visual
  // component explorer with no automated check behind it.
  test: {
    // Root-level, not per-project: Vitest's workspace ("projects") mode
    // applies coverage/reporters globally across every project rather than
    // letting each declare its own, even though there's currently only the
    // one "storybook" project below.
    reporters: ["default", "junit"],
    outputFile: { junit: "./vitest-report.xml" },
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "json-summary"],
      // Every component/page/hook under src/ counts, even ones with zero
      // stories yet — a coverage % that only reflects the ~handful of files
      // with a `.stories.tsx` would be a misleading number to badge.
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.stories.tsx", "src/**/*.d.ts", "src/main.tsx", "src/vite-env.d.ts"],
    },
    projects: [
      {
        extends: true,
        plugins: [storybookTest({ configDir: path.join(dirname, ".storybook") })],
        test: {
          name: "storybook",
          browser: {
            enabled: true,
            headless: true,
            provider: playwright({}),
            instances: [{ browser: "chromium" }],
          },
        },
      },
    ],
  },
});
