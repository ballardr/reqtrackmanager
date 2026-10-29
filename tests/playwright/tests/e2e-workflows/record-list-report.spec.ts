import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";
import { chooseExport } from "../listActions";

/**
 * Job to be done: get a plain table of a kind of record — as a screen, a PDF or a Word file — from the Reports page
 * without visiting the list, and get the same PDF or Word file from a list's own Export menu with the list's
 * filters applied.
 *
 * Each test works in its own disposable project with its own uniquely named records.
 */
test.describe("Record list report", () => {
  installCleanupHook();

  async function projectWithRequirement(page: import("@playwright/test").Page, label: string) {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, label);
    const name = `E2E Record List ${Date.now()}`;
    const resp = await page.request.post(`http://localhost:8000/api/v1/projects/${project.projectId}/requirements`, {
      headers: project.headers,
      data: { name, component_id: project.components[0].id, category_id: project.categories[0].id },
    });
    expect(resp.ok(), await resp.text()).toBeTruthy();
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    return { ...project, requirementName: name };
  }

  test("the Reports page lists a type as a table, switches type and downloads Word", async ({ page }) => {
    const project = await projectWithRequirement(page, "E2E Record List Page");
    await page.goto(`/projects/${project.projectId}?reports=choose&report=record-list`);

    await test.step("the first type is run and its rows are shown, code first", async () => {
      await expect(page.getByLabel("Record type")).toHaveValue("requirement");
      await expect(page.getByRole("cell", { name: project.requirementName })).toBeVisible();
      await expect(page.getByRole("columnheader", { name: "Code" })).toBeVisible();
    });

    await test.step("another type is a different table", async () => {
      await page.getByLabel("Record type").selectOption("requirement_action");
      await expect(page.getByRole("cell", { name: project.requirementName })).toHaveCount(0);
      await page.getByLabel("Record type").selectOption("requirement");
      await expect(page.getByRole("cell", { name: project.requirementName })).toBeVisible();
    });

    await test.step("Word download is a real document", async () => {
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const download = page.waitForEvent("download");
      await page.getByRole("button", { name: "Download Word report" }).click();
      const file = await download;
      expect(file.suggestedFilename()).toBe("record-list.docx");
      const bytes = fs.readFileSync((await file.path())!);
      expect(bytes.subarray(0, 2).toString()).toBe("PK");
      expect(bytes.includes("word/document.xml")).toBeTruthy();
    });
  });

  test("a list's Export menu offers PDF and Word with the list's own filters", async ({ page }) => {
    const project = await projectWithRequirement(page, "E2E Record List Menu");
    await page.goto(`/projects/${project.projectId}`);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    const request = page.waitForRequest((r) => r.url().includes("/reports/record-list"));
    const download = page.waitForEvent("download");
    await chooseExport(page, "PDF");
    const sent = new URL((await request).url());
    expect(sent.searchParams.get("record_type")).toBe("requirement");
    expect(sent.searchParams.get("format")).toBe("pdf");
    const file = await download;
    expect(file.suggestedFilename()).toBe("requirements-export.pdf");
    expect(fs.readFileSync((await file.path())!).subarray(0, 5).toString()).toBe("%PDF-");
    await expect(page.getByText("Requirements exported as PDF.")).toBeVisible();
  });
});
