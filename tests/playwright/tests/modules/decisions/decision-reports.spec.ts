import crypto from "node:crypto";
import { readFile } from "node:fs/promises";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "../../e2e-workflows/helpers";

const API_BASE_URL = "http://localhost:8000";
const MODULE = "decisions";
const REPORTS = ["Decision register", "Approval ageing", "Decision log", "Rationale coverage"];

/**
 * Job to be done: —
 * the four Decision Management reports appear in the shared Reports page
 * (rendered by the generic viewer, no custom view), show the project's
 * decisions with their display labels, narrow through the generated option
 * controls, and download as PDF and CSV. Also that a project with the module
 * off offers none of them.
 *
 * Everything is created through the API in a disposable, uniquely named org
 * (CLAUDE.md's test-independence rule) and deleted afterwards.
 */
installCleanupHook();

async function api(request: APIRequestContext, email: string, password = PASSWORD) {
  const login = await request.post(`${API_BASE_URL}/api/v1/auth/login`, { data: { email, password } });
  return { Authorization: `Bearer ${(await login.json()).access_token}` };
}

/**
 * A disposable org (Decision Management on) with an org admin, a project, one
 * Approved decision, one Under review decision and one Draft. Leaves the page
 * logged in as the org admin.
 */
async function setup(page: Page, request: APIRequestContext) {
  const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
  const adminEmail = `e2e-decision-reports-${suffix}@example.com`;
  const serverHeaders = await api(request, "admin@example.com", "ChangeMe123!");
  const org = await (await request.post(`${API_BASE_URL}/api/v1/orgs`, {
    headers: serverHeaders, data: { name: `E2E Decision Reports ${suffix}` },
  })).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Decision Reports Admin", password: PASSWORD, role: "org_admin" },
  });
  await loginAs(page, adminEmail, PASSWORD);
  const headers = await api(request, adminEmail);
  const enable = await request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/${MODULE}`, {
    headers, data: { enabled: true, default_project_enabled: true },
  });
  expect(enable.ok(), await enable.text()).toBeTruthy();
  const project = await (await request.post(`${API_BASE_URL}/api/v1/projects`, {
    headers, data: { organization_id: org.id, name: `Decision Reports Project ${suffix}`, summary: "" },
  })).json();
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/${MODULE}`;
  const types = await (await request.get(`${base}/decision-types`, { headers })).json();

  const create = async (title: string) => {
    const resp = await request.post(base, {
      headers,
      data: {
        title, decision_statement: `We will ${title}.`, decision_type_id: types[0].id,
        decision_date: new Date().toISOString().slice(0, 10), rationale: "Because it is cheaper.",
      },
    });
    expect(resp.ok(), await resp.text()).toBeTruthy();
    return (await resp.json()) as { id: string };
  };
  const step = async (id: string, action: string, data?: object) => {
    const resp = await request.post(`${base}/${id}/${action}`, { headers, data });
    expect(resp.ok(), await resp.text()).toBeTruthy();
  };

  const titles = { approved: `Adopt queue ${suffix}`, review: `Pick vendor ${suffix}`, draft: `Rename service ${suffix}` };
  const approved = await create(titles.approved);
  await step(approved.id, "propose");
  await step(approved.id, "submit-for-review");
  await step(approved.id, "approve", {});
  const review = await create(titles.review);
  await step(review.id, "propose");
  await step(review.id, "submit-for-review");
  await create(titles.draft);
  return { org, project, headers, titles, suffix };
}

function picker(page: Page) {
  return page.getByRole("combobox", { name: "Report", exact: true });
}

test.describe("Decision Management: reports", () => {
  test("the project Reports page lists the four Decision reports", async ({ page, request }) => {
    const { project } = await setup(page, request);
    await page.goto(`/projects/${project.id}/reports`);

    await expect(picker(page)).toHaveValue("requirements");
    const options = await picker(page).locator("option").allTextContents();
    expect(options).toEqual(expect.arrayContaining(REPORTS));

    await picker(page).selectOption({ label: "Decision register" });
    await expect(page).toHaveURL(/report=decision-register/);
    await page.reload();
    await expect(picker(page)).toHaveValue("decision-register");
  });

  test("the register shows display labels and narrows by status", async ({ page, request }) => {
    const { project, titles } = await setup(page, request);
    await page.goto(`/projects/${project.id}/reports?report=decision-register`);

    const register = page.getByRole("region", { name: "Decisions", exact: true });
    await expect(register.getByRole("row")).toHaveCount(4); // header + three decisions
    await expect(register.getByRole("row", { name: new RegExp(titles.approved) })).toContainText("Approved");
    await expect(register.getByRole("row", { name: new RegExp(titles.review) })).toContainText("Under review");
    await expect(register).not.toContainText("under_review");

    await page.getByRole("combobox", { name: "Status" }).selectOption({ label: "Draft" });
    await expect(register.getByRole("row")).toHaveCount(2);
    await expect(register).toContainText(titles.draft);
    await expect(register).not.toContainText(titles.approved);
  });

  test("approval ageing lists only the decision still awaiting a verdict", async ({ page, request }) => {
    const { project, titles } = await setup(page, request);
    await page.goto(`/projects/${project.id}/reports?report=approval-ageing`);

    const awaiting = page.getByRole("region", { name: "Awaiting a verdict" });
    await expect(awaiting).toContainText(titles.review);
    await expect(awaiting).not.toContainText(titles.approved);
    await expect(awaiting).not.toContainText(titles.draft);
    await expect(page.getByRole("region", { name: "No decision maker" })).toContainText(titles.review);
  });

  test("the decision log shows the rationale of decisions made, and rationale coverage lists the unlinked ones", async ({ page, request }) => {
    const { project, titles } = await setup(page, request);

    await page.goto(`/projects/${project.id}/reports?report=decision-log`);
    const log = page.getByRole("region", { name: "Decisions made" });
    await expect(log).toContainText(titles.approved);
    await expect(log).toContainText("Because it is cheaper.");
    await expect(log).not.toContainText(titles.review);

    await page.goto(`/projects/${project.id}/reports?report=rationale-coverage`);
    const bare = page.getByRole("region", { name: "Decisions with no linked artefact" });
    await expect(bare).toContainText(titles.approved);
    await expect(bare).toContainText(titles.draft);
  });

  test("every Decision report downloads as PDF and CSV", async ({ page, request }) => {
    const { project, titles } = await setup(page, request);
    await page.goto(`/projects/${project.id}/reports`);
    await expect(picker(page)).toHaveValue("requirements");
    const values = await picker(page).locator("option").evaluateAll((els, labels) =>
      els.filter((e) => labels.includes(e.textContent ?? "")).map((e) => ({ value: (e as HTMLOptionElement).value, label: e.textContent ?? "" })),
    REPORTS);
    expect(values).toHaveLength(4);

    for (const report of values) {
      await test.step(`${report.label}: PDF and CSV`, async () => {
        await picker(page).selectOption(report.value);
        await expect(page.getByRole("button", { name: "Export" })).toBeVisible();
        for (const kind of ["PDF", "CSV"] as const) {
          await page.getByRole("button", { name: "Export" }).click();
          const [download] = await Promise.all([
            page.waitForEvent("download"),
            page.getByRole("button", { name: `Download ${kind} report` }).click(),
          ]);
          expect(download.suggestedFilename()).toBe(`${report.value}.${kind.toLowerCase()}`);
          if (kind === "CSV" && report.value === "decision-register") {
            const csv = await readFile((await download.path())!, "utf8");
            expect(csv).toContain(titles.approved);
            // A report names each record by its code, and lists its tags.
            expect(csv.split("\n")[0]).toMatch(/^Code,Title,.*,Tags/);
            expect(csv).toContain("DEC-001,");
          }
        }
      });
    }
  });

  test("a project with the module off offers no Decision reports", async ({ page, request }) => {
    const { project, headers } = await setup(page, request);
    const off = await request.put(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/${MODULE}/enablement`, {
      headers, data: { enabled: false },
    });
    expect(off.ok(), await off.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/reports`);
    await expect(page.getByRole("button", { name: "Generate PDF" })).toBeVisible();
    await expect(picker(page)).toHaveCount(0);
  });
});
