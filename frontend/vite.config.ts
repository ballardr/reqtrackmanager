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
