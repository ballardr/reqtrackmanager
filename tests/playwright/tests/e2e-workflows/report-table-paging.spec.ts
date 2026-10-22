import crypto from "node:crypto";
import { readFile } from "node:fs/promises";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

const API_BASE_URL = "http://localhost:8000";
const DECISIONS = 55;
const PAGE_SIZE = 50;

/**
 * Job to be done: —
 * a long report table shows its first page on screen with a "Showing n of m"
 * count and a "Load more" button, reveals the rest on request, and the
 * downloaded CSV still holds every row.
 *
 * Each test builds its own disposable, uniquely named org and deletes it
 * afterwards (CLAUDE.md's test-independence rule).
 */
installCleanupHook();

async function login(request: APIRequestContext, email: string, password = PASSWORD) {
  const resp = await request.post(`${API_BASE_URL}/api/v1/auth/login`, { data: { email, password } });
  return { Authorization: `Bearer ${(await resp.json()).access_token}` };
}

/** A disposable org (Decision Management on) whose project holds `DECISIONS` draft decisions. Leaves the page logged in. */
async function setup(page: Page, request: APIRequestContext) {
  const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
  const adminEmail = `e2e-report-paging-${suffix}@example.com`;
  const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
  const org = await (await request.post(`${API_BASE_URL}/api/v1/orgs`, { headers: serverHeaders, data: { name: `E2E Report Paging ${suffix}` } })).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Paging Admin", password: PASSWORD, role: "org_admin" },
  });
  await loginAs(page, adminEmail, PASSWORD);
  const headers = await login(request, adminEmail);
  const enable = await request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/decisions`, {
    headers, data: { enabled: true, default_project_enabled: true },
  });
  expect(enable.ok(), await enable.text()).toBeTruthy();
  const project = await (await request.post(`${API_BASE_URL}/api/v1/projects`, {
    headers, data: { organization_id: org.id, name: `Paging Project ${suffix}`, summary: "" },
  })).json();
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/decisions`;
  const types = await (await request.get(`${base}/decision-types`, { headers })).json();
  for (let start = 0; start < DECISIONS; start += 5) {
    await Promise.all(
      Array.from({ length: Math.min(5, DECISIONS - start) }, async (_, offset) => {
        const resp = await request.post(base, {
          headers, data: { title: `Paged ${suffix} ${start + offset}`, decision_statement: "We will.", decision_type_id: types[0].id },
        });
        expect(resp.ok(), await resp.text()).toBeTruthy();
      }),
    );
  }
  return { project, suffix };
}

test.describe("Report table paging", () => {
  test("a long table shows a page at a time and the CSV export keeps every row", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await page.goto(`/projects/${project.id}/reports?report=decision-register`);

    const register = page.getByRole("region", { name: "Decisions", exact: true });
    await expect(register.getByRole("row")).toHaveCount(PAGE_SIZE + 1); // header + first page
    await expect(register.getByText(`Showing ${PAGE_SIZE} of ${DECISIONS} rows`)).toBeVisible();

    await register.getByRole("button", { name: /Load more/ }).click();
    await expect(register.getByRole("row")).toHaveCount(DECISIONS + 1);
    await expect(register.getByRole("button", { name: /Load more/ })).toHaveCount(0);
    await expect(register.getByText(/Showing \d+ of/)).toHaveCount(0);

    await page.getByRole("button", { name: "Export", exact: true }).click();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Download CSV report" }).click(),
    ]);
    const csv = await readFile((await download.path())!, "utf8");
    expect(csv.split("\n").filter((line) => line.includes(`Paged ${suffix}`))).toHaveLength(DECISIONS);
  });

  test("the count and button are back after reloading the report", async ({ page, request }) => {
    const { project } = await setup(page, request);
    await page.goto(`/projects/${project.id}/reports?report=decision-register`);
    const register = page.getByRole("region", { name: "Decisions", exact: true });
    await register.getByRole("button", { name: /Load more/ }).click();
    await page.reload();
    await expect(register.getByRole("row")).toHaveCount(PAGE_SIZE + 1);
  });
});
