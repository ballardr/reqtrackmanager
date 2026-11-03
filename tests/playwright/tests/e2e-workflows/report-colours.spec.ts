import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { closeDesignerPreview, openDesignerPreview, deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, saveNewVersion, selectOrgAdminGroup, selectProjectAdminGroup, designerPreviewPanel } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: set a report's colours once, by name, and have every block that uses the name follow the organisation's
 * branding, with the layout able to override them.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report colours", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  async function newWorld(request: APIRequestContext, label: string) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-colours-${label}-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Colours ${label} ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Colours Admin", password: PASSWORD, role: "org_admin" },
    });
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Colours project ${suffix}`, summary: "" } })).json();
    return { suffix, adminEmail, headers, org, project };
  }

  async function newLayout(page: Page, projectId: string, name: string) {
    await page.goto(`/projects/${projectId}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
    const dialog = page.getByRole("dialog", { name: "New report layout" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await page.getByRole("tab", { name: "Blocks" }).click();
  }

  async function shapeFillInPreview(page: Page): Promise<string | null> {
    await openDesignerPreview(page);
    const preview = designerPreviewPanel(page);
    await preview.getByRole("button", { name: "Run preview" }).click();
    const fill = await preview.frameLocator('iframe[title="Report preview"]').locator("svg rect").first().getAttribute("fill");
    await closeDesignerPreview(page);
    return fill;
  }

  test("the organisation's colours are set on Branding, a block uses one by name, and the layout can override then follow it again", async ({ page, request }) => {
    const { adminEmail, org, project, suffix } = await newWorld(request, "scheme");
    await loginAs(page, adminEmail, PASSWORD);

    await test.step("an organisation admin adds a colour to the organisation's report colours and saves", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Branding & defaults");
      await ensureExpanded(page, "Branding");
      await page.getByRole("button", { name: "Add colour" }).click();
      const popover = page.getByRole("dialog", { name: "Colour settings: colour1" });
      await popover.getByRole("textbox", { name: "Colour colour1 (Custom colour) (hex code)" }).fill("#112233");
      await popover.getByRole("textbox", { name: "Name" }).fill("alert");
      await page.keyboard.press("Escape");
      await expect(page.getByRole("list", { name: "Colours in the scheme" })).toContainText("alert #112233");
      await page.getByRole("button", { name: "Save branding" }).click();
      await expect(page.getByText("Branding saved")).toBeVisible();
    });

    await newLayout(page, project.id, `E2E colours layout ${suffix}`);

    await test.step("a shape's fill offers the organisation's colour by name and the preview prints it", async () => {
      await page.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "Shape", exact: true }).click();
      const inspector = page.getByLabel("Block details");
      await inspector.getByRole("combobox", { name: "Width unit" }).waitFor();
      await inspector.getByRole("button", { name: /^Fill:/ }).click();
      await page.getByRole("dialog", { name: "Choose a colour for Fill" }).getByRole("button", { name: /^alert/ }).click();
      await expect(inspector.getByRole("button", { name: "Fill: alert" })).toContainText("#112233");
      await expect(page.getByText("No problems.")).toBeVisible();
      expect(await shapeFillInPreview(page)).toBe("#112233");
    });

    await test.step("the layout's own colour of the same name wins, and the block follows it", async () => {
      await page.locator(".blocklyText", { hasText: /^Layout$/ }).click();
      const inspector = page.getByLabel("Block details");
      await ensureExpanded(page, "Look");
      await inspector.getByRole("button", { name: "Add colour" }).click();
      const popover = page.getByRole("dialog", { name: "Colour settings: colour1" });
      await popover.getByRole("textbox", { name: "Colour colour1 (Custom colour) (hex code)" }).fill("#445566");
      await popover.getByRole("textbox", { name: "Name" }).fill("alert");
      await page.keyboard.press("Escape");
      await expect(page.getByText("No problems.")).toBeVisible();
      expect(await shapeFillInPreview(page)).toBe("#445566");
    });

    await test.step("a colour a block uses cannot be removed, and the text view writes the scheme", async () => {
      await page.locator(".blocklyText", { hasText: /^Layout$/ }).click();
      const inspector = page.getByLabel("Block details");
      await inspector.getByRole("button", { name: "Remove colour alert" }).click();
      await expect(inspector.getByRole("alert")).toContainText("alert is used by a block");
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Text" }).click();
      const text = page.getByRole("textbox", { name: "Layout text" });
      await expect(text).toHaveValue(/@palette alert=#445566/);
      await expect(text).toHaveValue(/@shape rectangle fill alert/);
    });

    await test.step("following the organisation's colours clears the layout's own, and the preview returns to the organisation's", async () => {
      await page.getByRole("tab", { name: "Blocks" }).click();
      await page.locator(".blocklyText", { hasText: /^Layout$/ }).click();
      await page.getByLabel("Block details").getByRole("button", { name: "Follow the organisation's colours" }).click();
      await expect(page.getByLabel("Block details")).toContainText("no colours of its own");
      await expect(page.getByText("No problems.")).toBeVisible();
      expect(await shapeFillInPreview(page)).toBe("#112233");
    });
  });

  test("a colour name no scheme defines is refused when a layout is saved, with the block's path", async ({ request }) => {
    const { headers, project, suffix } = await newWorld(request, "unknown");
    const tree = {
      schema_version: 1, family: "document",
      nodes: [{ type: "shape", shape: "rectangle", width: 5, height: 2, fill: "ghost" }],
    };
    const resp = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: { name: `E2E ghost ${suffix}`, description: "", family: "document", tree },
    });
    expect(resp.status()).toBe(422);
    expect(await resp.text()).toContain("There is no colour called ghost");
    expect(await resp.text()).toContain("nodes[0].fill");
  });

  test("a layout starts from a ready-made set of colours, and the standard four always resolve", async ({ page, request }) => {
    const { adminEmail, project, suffix } = await newWorld(request, "start");
    await loginAs(page, adminEmail, PASSWORD);
    await newLayout(page, project.id, `E2E colours start ${suffix}`);
    await page.locator(".blocklyText", { hasText: /^Layout$/ }).click();
    const inspector = page.getByLabel("Block details");
    await ensureExpanded(page, "Look");
    await inspector.getByRole("combobox", { name: "Start from" }).selectOption({ label: "Cool" });
    await expect(inspector.getByRole("list", { name: "Colours in the scheme" })).toContainText("primary #1d4ed8");
    await page.getByRole("button", { name: "Add block" }).click();
    await page.getByRole("menuitem", { name: "Shape", exact: true }).click();
    await page.getByLabel("Block details").getByRole("button", { name: /^Fill:/ }).click();
    await page.getByRole("dialog", { name: "Choose a colour for Fill" }).getByRole("button", { name: /^primary/ }).click();
    await expect(page.getByText("No problems.")).toBeVisible();
    expect(await shapeFillInPreview(page)).toBe("#1d4ed8");
  });
});
