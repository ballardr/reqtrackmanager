import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, openDesignerPreviewDialog, openSetupReport, PASSWORD, saveNewVersion, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: put a coloured shape behind a logo (or a plate, a line, an arrow) in a report: choose it in the block
 * editor, read it as one line in the text view, see it in the preview, and have an unsafe custom SVG refused with the
 * server's message; and the demo organisation's logo report (the white-on-transparent product mark in front of a plate in
 * the accent colour) shows both in the preview.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report shapes", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-shapes-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Shapes ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Shapes Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Shapes ${suffix}`, summary: "" } })).json();
    const layoutName = `E2E shapes ${suffix}`;
    const layout = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: {
        name: layoutName, description: "E2E layout", family: "document",
        tree: {
          schema_version: 1, family: "document", orientation: "portrait",
          nodes: [
            { type: "shape", shape: "rounded", fill: "#475569", width: 5, height: 2, placement: "behind", anchor: "page", offset_x: 2, offset_y: 2 },
            { type: "text", text: "Over the plate." },
          ],
        },
      },
    });
    expect(layout.ok(), await layout.text()).toBeTruthy();
    return { headers, project, layoutName };
  }

  test("a shape is changed in the block editor, written as one line in the text view and drawn in the preview", async ({ page, request }) => {
    const { project, layoutName } = await setup(page, request);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await openSetupReport(page, layoutName);
    await page.getByRole("tab", { name: "Blocks" }).click();
    await page.locator(".blocklyText.rl-block-title", { hasText: /^Shape$/ }).first().click();
    const inspector = page.getByLabel("Block details");

    await test.step("the kind is named in words and a change is kept", async () => {
      const kind = inspector.getByRole("combobox", { name: "Shape" });
      await expect(kind.locator("option")).toContainText(["Rectangle", "Rounded rectangle", "Ellipse", "Triangle", "Line", "Arrow", "Custom SVG"]);
      await kind.selectOption({ label: "Ellipse" });
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("the preview draws the shape under the text", async () => {
      await openDesignerPreviewDialog(page);
      const dialog = page.getByRole("dialog", { name: "Report preview" });
      await dialog.getByRole("button", { name: "Run preview" }).click();
      const frame = dialog.frameLocator('iframe[title="Report preview"]');
      await expect(frame.locator("div.layer-anchor.behind svg ellipse")).toHaveCount(1);
      await expect(frame.getByText("Over the plate.")).toBeVisible();
      await dialog.getByRole("button", { name: "Close" }).click();
    });

    await test.step("saved, the text view writes the shape as one line and reports a bad one at its line", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.getByRole("tab", { name: "Text" }).click();
      const editor = page.getByRole("textbox", { name: "Layout text" });
      expect(await editor.inputValue()).toContain("@shape ellipse fill #475569 width 5 height 2 placement behind anchor page x 2 y 2");
      await editor.fill("@layout document\n\n@shape rectangle width wide\n");
      await expect(page.getByText(/Line 3/)).toBeVisible();
    });
  });

  test("an unsafe custom SVG is refused with a message and a safe one is drawn", async ({ page, request }) => {
    const { project, layoutName } = await setup(page, request);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await openSetupReport(page, layoutName);
    await page.getByRole("tab", { name: "Text" }).click();
    const editor = page.getByRole("textbox", { name: "Layout text" });

    await test.step("a link to another file is a problem on the shape's line", async () => {
      const bad = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect fill="url(http://evil/x)" width="1" height="1"/></svg>';
      await editor.fill(`@layout document\n\n@shape custom svg ${JSON.stringify(bad)} width 3\n`);
      await expect(page.getByText(/external reference/)).toBeVisible();
    });

    await test.step("a plain SVG has no problems and is drawn", async () => {
      const good = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="#cc3333"/></svg>';
      await editor.fill(`@layout document\n\n@shape custom svg ${JSON.stringify(good)} width 3 alt "A red dot"\n`);
      await expect(page.getByText("The text is valid.")).toBeVisible();
      await openDesignerPreviewDialog(page);
      const dialog = page.getByRole("dialog", { name: "Report preview" });
      await dialog.getByRole("button", { name: "Run preview" }).click();
      await expect(dialog.frameLocator('iframe[title="Report preview"]').locator("svg circle")).toHaveCount(1);
    });
  });

  test("the demo logo report draws the white logo in front of an accent plate", async ({ page, request }) => {
    const { headers, project } = await setup(page, request);
    // The same file and layout shape backend/scripts/seed_demo_data.py seeds into the demo organisation.
    const logo = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../../backend/scripts/data/logo.svg"));
    const upload = await request.post(`${API}/projects/${project.id}/report-images`, {
      headers, multipart: { file: { name: "logo.svg", mimeType: "image/svg+xml", buffer: logo } },
    });
    expect(upload.ok(), await upload.text()).toBeTruthy();
    const image = await upload.json();
    const layoutName = `E2E logo plate ${crypto.randomUUID().slice(0, 8)}`;
    const created = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: {
        name: layoutName, description: "E2E layout", family: "document",
        tree: {
          schema_version: 1, family: "document", orientation: "portrait",
          nodes: [
            { type: "shape", shape: "rounded", fill: "accent", width: 5, height: 2.5, alt: "", placement: "behind", anchor: "paragraph", offset_x: 12, offset_y: 0 },
            { type: "image", file: image.id, alt: "Product logo", height: 1.75, height_unit: "cm", placement: "front", anchor: "paragraph", offset_x: 12.75, offset_y: 0.375 },
            { type: "heading", text: "Overview" },
          ],
        },
      },
    });
    expect(created.ok(), await created.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await openSetupReport(page, layoutName);
    await openDesignerPreviewDialog(page);
    const dialog = page.getByRole("dialog", { name: "Report preview" });
    await dialog.getByRole("button", { name: "Run preview" }).click();
    const frame = dialog.frameLocator('iframe[title="Report preview"]');
    await expect(frame.locator("div.layer-anchor.behind svg")).toHaveCount(1);
    await expect(frame.locator("div.layer-anchor.front").getByLabel("Product logo").or(frame.locator("div.layer-anchor.front img[alt='Product logo']"))).toHaveCount(1);
    await expect(frame.getByRole("heading", { name: "Overview" })).toBeVisible();
  });
});
