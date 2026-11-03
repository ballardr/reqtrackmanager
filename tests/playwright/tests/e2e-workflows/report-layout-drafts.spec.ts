import { expect, test } from "@playwright/test";

import { createDocumentLayoutWorld, installCleanupHook, loginAs, openDesignerTextView, PASSWORD, saveNewVersion } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: save often so nothing is lost, without filling the layout's history with versions nobody wanted.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout drafts", () => {
  installCleanupHook();

  const status = (page: import("@playwright/test").Page) => page.getByRole("status", { name: "Draft status" });

  test("autosave keeps the work across a reload and publishing makes exactly one version", async ({ page, request }) => {
    const { adminEmail, project, layout } = await createDocumentLayoutWorld(request, "draft-autosave");
    await loginAs(page, adminEmail, PASSWORD);
    await page.goto(`/projects/${project.id}/report-layouts/${layout.id}`);
    await openDesignerTextView(page);
    const editor = page.getByRole("textbox", { name: "Layout text" });

    await test.step("editing writes the draft after a pause, with a status", async () => {
      await expect(status(page)).toHaveText("No draft");
      await editor.fill("@layout document\n\n@heading Kept by autosave\n");
      await expect(status(page)).toHaveText(/^Draft saved/, { timeout: 20_000 });
      await expect(page.getByText("Unsaved changes")).toHaveCount(0);
    });

    await test.step("a reload opens on the draft, with its notice", async () => {
      await page.reload();
      await expect(page.getByRole("note", { name: "Draft" })).toContainText("based on version 1");
      await openDesignerTextView(page);
      await expect(editor).toHaveValue(/Kept by autosave/);
    });

    await test.step("History lists no version for the draft, only a Draft row", async () => {
      await page.getByRole("tab", { name: "History", exact: true }).click();
      await expect(page.getByRole("note", { name: "Draft" })).toContainText("Discard draft");
      await expect(page.getByRole("table", { name: "Versions" }).getByRole("row")).toHaveCount(2);
      await page.getByRole("tab", { name: "Design", exact: true }).click();
    });

    await test.step("saving publishes the draft as version 2 and clears the draft", async () => {
      await saveNewVersion(page, "From the draft");
      await expect(page.getByText("Version 2", { exact: true })).toBeVisible();
      await expect(status(page)).toHaveText("No draft");
      await expect(page.getByRole("note", { name: "Draft" })).toHaveCount(0);
      const versions = await (await request.get(`${API}/projects/${project.id}/report-layouts/${layout.id}/versions`, { headers: (await loginHeaders(request, adminEmail)) })).json();
      expect(versions).toHaveLength(2);
    });
  });

  test("with autosave off nothing is stored until Save draft, and a draft can be discarded", async ({ page, request }) => {
    const { adminEmail, project, layout } = await createDocumentLayoutWorld(request, "draft-manual");
    await loginAs(page, adminEmail, PASSWORD);
    await page.goto(`/projects/${project.id}/report-layouts/${layout.id}`);
    await openDesignerTextView(page);
    const editor = page.getByRole("textbox", { name: "Layout text" });
    await page.getByRole("switch", { name: "Autosave drafts" }).click();

    await test.step("an edit is not stored, and leaving asks first", async () => {
      await editor.fill("@layout document\n\n@heading Only in the editor\n");
      await expect(status(page)).toHaveText("Changes not saved to a draft");
      await page.waitForTimeout(4000);
      await expect(status(page)).toHaveText("Changes not saved to a draft");
      await page.getByRole("button", { name: "Report layouts" }).click();
      await expect(page.getByRole("dialog", { name: "Leave without saving?" })).toBeVisible();
      await page.getByRole("dialog", { name: "Leave without saving?" }).getByRole("button", { name: "Close" }).click();
    });

    await test.step("Save draft stores it and leaving no longer asks", async () => {
      await page.getByRole("button", { name: "Save draft", exact: true }).click();
      await expect(status(page)).toHaveText(/^Draft saved/);
      await page.reload();
      await expect(page.getByRole("note", { name: "Draft" })).toBeVisible();
    });

    await test.step("Discard draft returns to the saved version", async () => {
      await page.getByRole("note", { name: "Draft" }).getByRole("button", { name: "Discard draft" }).click();
      await page.getByRole("dialog", { name: "Discard this draft?" }).getByRole("button", { name: "Discard draft" }).click();
      await expect(page.getByRole("note", { name: "Draft" })).toHaveCount(0);
      await openDesignerTextView(page);
      await expect(editor).not.toHaveValue(/Only in the editor/);
      await expect(page.getByText("Version 1", { exact: true })).toBeVisible();
    });
  });

  test("a draft changed by someone else pauses autosave until the author chooses", async ({ page, request }) => {
    const { adminEmail, headers, project, layout } = await createDocumentLayoutWorld(request, "draft-conflict");
    await loginAs(page, adminEmail, PASSWORD);
    await page.goto(`/projects/${project.id}/report-layouts/${layout.id}`);
    await openDesignerTextView(page);
    const editor = page.getByRole("textbox", { name: "Layout text" });

    // Someone else writes the draft after this editor loaded the layout (it saw no draft).
    const theirs = { schema_version: 1, family: "document", nodes: [{ type: "heading", text: "Their heading", level: 1 }] };
    const wrote = await request.put(`${API}/projects/${project.id}/report-layouts/${layout.id}/draft`, {
      headers, data: { tree: theirs, base_version: 1, revision: 0 },
    });
    expect(wrote.ok()).toBeTruthy();

    await editor.fill("@layout document\n\n@heading Mine\n");
    const banner = page.getByRole("alert", { name: "Someone else changed this draft" });
    await expect(banner).toBeVisible({ timeout: 20_000 });
    await banner.getByRole("button", { name: "Keep mine" }).click();
    await expect(banner).toHaveCount(0);
    await expect(status(page)).toHaveText(/^Draft saved/, { timeout: 20_000 });
  });
});

async function loginHeaders(request: import("@playwright/test").APIRequestContext, email: string) {
  const resp = await request.post(`${API}/auth/login`, { data: { email, password: PASSWORD } });
  return { Authorization: `Bearer ${(await resp.json()).access_token}` };
}
