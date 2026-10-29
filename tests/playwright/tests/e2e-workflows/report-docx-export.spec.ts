import crypto from "node:crypto";
import { readFile } from "node:fs/promises";

import { expect, type APIRequestContext, type Download, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: —
 * a user downloads any report as an editable Word (DOCX) file: the
 * requirement report from the "More formats" menu beside "Generate PDF", and a
 * catalogue report (Decision register) from the runner's Export menu.
 *
 * Each test builds its own disposable, uniquely named org and deletes it
 * afterwards (CLAUDE.md's test-independence rule).
 */
installCleanupHook();

async function login(request: APIRequestContext, email: string, password = PASSWORD) {
  const resp = await request.post(`${API_BASE_URL}/api/v1/auth/login`, { data: { email, password } });
  return { Authorization: `Bearer ${(await resp.json()).access_token}` };
}

/** A disposable org (Decision Management on) with an org admin and a project holding one requirement. Leaves the page logged in. */
async function setup(page: Page, request: APIRequestContext) {
  const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
  const adminEmail = `e2e-docx-${suffix}@example.com`;
  const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
  const org = await (await request.post(`${API_BASE_URL}/api/v1/orgs`, { headers: serverHeaders, data: { name: `E2E Docx ${suffix}` } })).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Docx Admin", password: PASSWORD, role: "org_admin" },
  });
  await loginAs(page, adminEmail, PASSWORD);
  const headers = await login(request, adminEmail);
  const enable = await request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/decisions`, {
    headers, data: { enabled: true, default_project_enabled: true },
  });
  expect(enable.ok(), await enable.text()).toBeTruthy();
  const project = await (await request.post(`${API_BASE_URL}/api/v1/projects`, {
    headers, data: { organization_id: org.id, name: `Docx Project ${suffix}`, summary: "" },
  })).json();
  const component = await (await request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/components`, {
    headers, data: { name: "Core", prefix: "CO" },
  })).json();
  const category = await (await request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/categories`, {
    headers, data: { name: "Performance", prefix: "PERF", component_id: component.id },
  })).json();
  const requirement = await request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/requirements`, {
    headers, data: { name: "Boot fast", reasoning: "UX matters", component_id: component.id, category_id: category.id },
  });
  expect(requirement.ok(), await requirement.text()).toBeTruthy();
  return { project };
}

/** A real DOCX is a zip holding `word/document.xml` (stored uncompressed in the directory). */
async function expectWordFile(download: Download, filenameEnd: string) {
  expect(download.suggestedFilename()).toMatch(new RegExp(`${filenameEnd.replace(".", "\\.")}$`));
  const bytes = await readFile((await download.path()) as string);
  expect(bytes.subarray(0, 2).toString()).toBe("PK");
  expect(bytes.includes("word/document.xml")).toBeTruthy();
}

test.describe("Word (DOCX) report export", () => {
  test("the requirement report downloads as Word from the More formats menu", async ({ page, request }) => {
    const { project } = await setup(page, request);
    await page.goto(`/projects/${project.id}?reports=choose`);

    await page.getByRole("button", { name: "More formats" }).click();
    const menu = page.getByRole("dialog", { name: "Export" });
    await expect(menu.getByRole("button", { name: "Download PDF report" })).toHaveCount(0); // PDF has its own primary button
    for (const name of ["ODT", "HTML", "CSV", "Excel", "ODS"]) {
      await expect(menu.getByRole("button", { name: `Download ${name} report` })).toBeVisible();
    }
    const downloadPromise = page.waitForEvent("download");
    await menu.getByRole("button", { name: "Download Word report" }).click();
    await expectWordFile(await downloadPromise, "-requirements.docx");
  });

  test("a catalogue report downloads as Word from its Export menu and confirms with a toast", async ({ page, request }) => {
    const { project } = await setup(page, request);
    await page.goto(`/projects/${project.id}?reports=choose&report=decision-register`);
    await expect(page.getByRole("region", { name: "Decisions", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Export", exact: true }).click();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("dialog", { name: "Export" }).getByRole("button", { name: "Download Word report" }).click();
    await expectWordFile(await downloadPromise, "decision-register.docx");
    await expect(page.getByText("Downloaded Decision register (Word).")).toBeVisible();
  });

  test("a module report is also offered as HTML, OpenDocument text, Excel and OpenDocument spreadsheet", async ({ page, request }) => {
    const { project } = await setup(page, request);
    await page.goto(`/projects/${project.id}?reports=choose&report=decision-register`);
    await expect(page.getByRole("region", { name: "Decisions", exact: true })).toBeVisible();

    const files: [string, string, string][] = [
      ["Download HTML report", "decision-register.html", "<"],
      ["Download ODT report", "decision-register.odt", "PK"],
      ["Download Excel report", "decision-register.xlsx", "PK"],
      ["Download ODS report", "decision-register.ods", "PK"],
    ];
    for (const [label, filename, magic] of files) {
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const downloadPromise = page.waitForEvent("download");
      await page.getByRole("dialog", { name: "Export" }).getByRole("button", { name: label }).click();
      const download = await downloadPromise;
      expect(download.suggestedFilename()).toMatch(new RegExp(`${filename.replace(".", "\\.")}$`));
      const bytes = await readFile((await download.path()) as string);
      expect(bytes.subarray(0, magic.length).toString()).toBe(magic);
    }
  });
});
