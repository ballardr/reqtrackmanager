import { defineConfig } from "@playwright/test";

// Runs against the already-up dev/test stack (tests/container/docker-compose.yml
// — frontend on :3000, backend on :8000) rather than starting its own
// webServer, so it exercises a real containerized deployment end to end.
// Never point this at the production stack (root docker-compose.yml).
export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
