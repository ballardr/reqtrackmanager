import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import {
  closeDesignerPreview, deleteOrgOnCleanup, designerPreviewPanel, ensureExpanded, installCleanupHook, loginAs, openDesignerPreview, openSetupReport, PASSWORD,
  selectProjectAdminGroup,
} from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: change the look of a custom table without wading through every setting. The block's form shows what is set
 * on nearly every table (columns, rows, header rows), keeps the rest in groups that fold away, and
 * says on a closed group's bar when it holds a setting that is not at its default.
 *
 * The test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout block form groups", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** Signs in as a fresh organisation administrator and opens a new, empty document layout in the designer. */
  async function openNewLayout(page: Page, request: APIRequestContext, slug: string) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-${slug}-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Block groups ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Block Groups Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Block groups ${suffix}`, summary: "" } })).json();
    const name = `E2E block groups ${suffix}`;
    const created = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: { name, description: "", family: "document", tree: { schema_version: 1, family: "document", nodes: [] } },
    });
    expect(created.ok(), await created.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await openSetupReport(page, name);
  }

  test("a custom table's settings sit in closed groups, and a change is counted on the bar and shows in the preview", async ({ page, request }) => {
    await openNewLayout(page, request, "block-groups");
    await page.getByRole("tab", { name: "Blocks" }).click();
    await page.getByRole("button", { name: "Add block" }).click();
    await page.getByRole("menuitem", { name: "Table (custom)", exact: true }).click();
    const inspector = page.getByLabel("Block details");

    await test.step("the basic fields are visible and the groups are closed", async () => {
      await expect(inspector.getByRole("spinbutton", { name: "Header rows" })).toBeVisible();
      for (const group of ["Borders", "Cell style", "Look"]) {
        await expect(inspector.getByRole("button", { name: `${group} section` })).toHaveAttribute("aria-expanded", "false");
      }
      await expect(inspector.getByRole("radiogroup", { name: "Alignment" })).toHaveCount(0);
    });

    await test.step("aligning the cells right in Cell style is counted on the closed bar", async () => {
      await inspector.getByRole("button", { name: "Cell style section" }).click();
      await inspector.getByRole("radio", { name: "Right" }).click();
      await expect(inspector.getByRole("radio", { name: "Right" })).toHaveAttribute("aria-checked", "true");
      await inspector.getByRole("button", { name: "Cell style section" }).click();
      await expect(inspector.getByRole("button", { name: "Cell style section" })).toHaveAccessibleDescription("1 changed");
    });

    await test.step("the preview prints the cells right-aligned", async () => {
      await openDesignerPreview(page);
      const preview = designerPreviewPanel(page);
      await preview.getByRole("button", { name: "Run preview" }).click();
      await expect(preview.frameLocator('iframe[title="Report preview"]').locator("table.grid td.a-right").first()).toBeVisible();
      await closeDesignerPreview(page);
    });
  });

  test("a shape's position sits in a closed group, is counted on the bar and moves the shape in the preview", async ({ page, request }) => {
    await openNewLayout(page, request, "shape-groups");
    await page.getByRole("tab", { name: "Blocks" }).click();
    await page.getByRole("button", { name: "Add block" }).click();
    await page.getByRole("menuitem", { name: "Shape", exact: true }).click();
    const inspector = page.getByLabel("Block details");

    await test.step("the kind and fill are in view and the other settings are in closed groups", async () => {
      await expect(inspector.getByRole("combobox", { name: "Shape" })).toBeVisible();
      for (const group of ["Outline", "Size", "Position", "SVG"]) {
        await expect(inspector.getByRole("button", { name: `${group} section` })).toHaveAttribute("aria-expanded", "false");
      }
      await expect(inspector.getByRole("combobox", { name: "Placement" })).toHaveCount(0);
    });

    await test.step("placing it behind the text in Position is counted on the closed bar", async () => {
      await ensureExpanded(page, "Position");
      await inspector.getByRole("combobox", { name: "Placement" }).selectOption({ label: "Behind the text" });
      await inspector.getByRole("button", { name: "Position section" }).click();
      await expect(inspector.getByRole("button", { name: "Position section" })).toHaveAccessibleDescription("1 changed");
    });

    await test.step("the preview draws the shape behind the text", async () => {
      await openDesignerPreview(page);
      const preview = designerPreviewPanel(page);
      await preview.getByRole("button", { name: "Run preview" }).click();
      await expect(preview.frameLocator('iframe[title="Report preview"]').locator("div.layer-anchor.behind svg").first()).toBeVisible();
      await closeDesignerPreview(page);
    });
  });
});
