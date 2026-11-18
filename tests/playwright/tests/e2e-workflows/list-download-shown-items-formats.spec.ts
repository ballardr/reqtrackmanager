import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";
import { chooseExport, openListMenu } from "../listActions";
import { openMenuParent } from "../menuTree";

/**
 * Job to be done: take the list I am looking at out of the product as an OpenDocument file (a text report or a
 * spreadsheet), with the page's filters applied, from the List actions menu's Download shown items group.
 *
 * Each test works in its own disposable project, so nothing here depends on another test or an earlier run.
 */
test.describe("Download shown items on a record list", () => {
  installCleanupHook();

  const API = "http://localhost:8000/api/v1";

  async function projectWithChangeRequest(page: import("@playwright/test").Page) {
    const { projectId, headers } = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Download Shown");
    const name = `E2E Shown Change ${Date.now()}`;
    expect(
      (await page.request.post(`${API}/projects/${projectId}/change-requests`, {
        headers, data: { kind: "new_requirement", proposed_name: name, reason: "Downloaded as ODT and ODS" },
      })).ok(),
    ).toBeTruthy();
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${projectId}`);
    await page.getByRole("link", { name: "Change requests", exact: true }).click();
    await expect(page.getByRole("link", { name })).toBeVisible();
    return name;
  }

  test("the parent lists CSV, PDF, Word, ODT and ODS in a group beneath it, not flat in the menu", async ({ page }) => {
    await projectWithChangeRequest(page);
    const menu = await openListMenu(page);
    const formats = await openMenuParent(page, "Download shown items", menu);
    for (const name of ["CSV", "PDF", "Word", "ODT", "ODS"]) {
      await expect(formats.getByRole("menuitem", { name: new RegExp(`^${name}`) })).toBeVisible();
    }
    // Escape closes the level first, the menu second.
    await menu.getByRole("menuitem", { name: "PDF" }).focus();
    await page.keyboard.press("Escape");
    await expect(formats).toHaveCount(0);
    await expect(page.getByRole("dialog", { name: "List actions" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "List actions" })).toHaveCount(0);
  });

  test("ODT and ODS download the shown change requests as OpenDocument files", async ({ page }) => {
    const name = await projectWithChangeRequest(page);
    for (const [format, extension, mimetype] of [
      ["ODT", "odt", "application/vnd.oasis.opendocument.text"],
      ["ODS", "ods", "application/vnd.oasis.opendocument.spreadsheet"],
    ] as const) {
      const request = page.waitForRequest((r) => r.url().includes("/reports/record-list") && r.url().includes(`format=${extension}`));
      const download = page.waitForEvent("download");
      await chooseExport(page, format);
      await request;
      const file = await download;
      expect(file.suggestedFilename()).toBe(`change-requests-export.${extension}`);
      const bytes = fs.readFileSync((await file.path())!);
      expect(bytes.subarray(0, 2).toString()).toBe("PK"); // an OpenDocument file is a zip
      expect(bytes.toString("latin1")).toContain(mimetype);
      await expect(page.getByText(`Change requests exported as ${format}.`)).toBeVisible();
    }
    expect(name).toBeTruthy();
  });
});
