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

// Tier C ("federated") frontend modules declare no Module Federation host plugin here: remote URLs arrive from the
// backend's manifest endpoint at runtime, and `frontend/src/modules/federatedLoader.ts` implements the container
// contract (`init(sharedScope)`/`get(exposedModuleName)`) with native dynamic `import()`, so no federation package
// is a dependency. It does not negotiate shared-dependency versions (see docs/modules.md, "Tier C").

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
  // Runs each Storybook story as a Vitest browser test (real Chromium via Playwright), so
  // `npm run test-storybook` fails a story that does not render or fails its play function.
  test: {
    // Root-level, not per-project: Vitest's workspace ("projects") mode applies reporters globally.
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
