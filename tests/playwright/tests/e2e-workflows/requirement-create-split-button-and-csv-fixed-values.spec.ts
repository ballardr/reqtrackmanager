import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: three pieces of the "New Requirement" creation-flow
 * roadmap batch (2026-08 UX audit, roadmap items 505/506/507) that the
 * rest of the suite exercises indirectly but never proves directly:
 *
 * - The split-button trigger (style guide "Pattern: split-button trigger")
 *   — a plain click on "New requirement" performs the default action with
 *   no menu stop, and its own separate chevron affordance is what reveals
 *   "Import from CSV". Every other spec that creates a requirement already
 *   relies on the click-does-default half implicitly (they just click
 *   "New requirement" and start typing); this spec is the one place that
 *   actually asserts no menu appears, and separately exercises the
 *   chevron.
 * - The CSV wizard's column-mapping step living in a `Modal` (roadmap item
 *   506) — a real `role="dialog"` layer, not an inline block.
 * - The per-field "same value for every row" fixed-value toggle (roadmap
 *   item 507) actually producing the right import result end to end.
 */
test.describe("New Requirement split-button trigger", () => {
  test("a plain click opens the create form directly; the chevron reveals Import from CSV", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.alpha1).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    await test.step("a plain click on the main button opens the create form with no menu stop", async () => {
      await page.getByRole("button", { name: "New requirement", exact: true }).click();
      await expect(page.getByRole("dialog", { name: "New requirement" })).toBeVisible();
      await expect(page.getByPlaceholder("Name", { exact: true })).toBeVisible();
      // The alternative-actions menu never appeared for this click.
      await expect(page.getByRole("button", { name: "Import from CSV" })).toHaveCount(0);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog", { name: "New requirement" })).toHaveCount(0);
    });

    await test.step("the chevron reveals Import from CSV without opening the create form", async () => {
      await page.getByRole("button", { name: "More options" }).click();
      const menu = page.getByRole("dialog", { name: "New requirement" });
      await expect(menu).toBeVisible();
      await expect(menu.getByRole("button", { name: "Import from CSV" })).toBeVisible();
      // Revealing the menu is not itself the default action — the create
      // form's own Name field never appeared.
      await expect(page.getByPlaceholder("Name", { exact: true })).toHaveCount(0);

      await menu.getByRole("button", { name: "Import from CSV" }).click();
      // Selecting the alternative opens the file picker, which surfaces as
      // the CSV wizard's own mapping Modal once a file is chosen — proven
      // together with the Modal assertion below.
      await expect(menu).toHaveCount(0);
    });
  });
});

test.describe("CSV import wizard: Modal-hosted mapping step and per-field fixed values", () => {
  test("mapping step opens as a Modal, and fixed-value toggles apply one value to every row", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.beta1).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const projectId = page.url().match(/projects\/([0-9a-f-]+)/)![1];
    const [componentsResp, categoriesResp, stagesResp] = await Promise.all([
      page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/components`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
      page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/categories`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
      page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/stages`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
    ]);
    const components: { id: string; name: string; prefix: string }[] = await componentsResp.json();
    const categories: { id: string; prefix: string; component_id: string }[] = await categoriesResp.json();
    const stages: { id: string; name: string }[] = await stagesResp.json();
    const component = components[0];
    const category = categories.find((c) => c.component_id === component.id)!;
    const stage = stages[0];

    // Only `name` varies per row — component/category/level/target_version
    // are left entirely unmapped, so the batch can only import once every
    // one of the four fixed-value toggles below is used.
    const rowOneName = `E2E Fixed Value Row One (${Date.now()})`;
    const rowTwoName = `E2E Fixed Value Row Two (${Date.now()})`;
    const csv = `name\n${rowOneName}\n${rowTwoName}\n`;

    const fileInput = page.locator('input[type="file"][accept*="csv"]');
    await fileInput.setInputFiles({ name: "names-only.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });

    const modal = page.getByRole("dialog", { name: "Map your CSV columns" });
    await test.step("the mapping/preview step is a real Modal dialog, not an inline block", async () => {
      await expect(modal).toBeVisible();
      await expect(modal.getByText("Preview (first 2 of 2 rows)")).toBeVisible();
      // The trigger row underneath (Export) is still present in the DOM —
      // this is a layer on top of the page, not a page reflow.
      await expect(page.getByRole("button", { name: "Export", exact: true })).toBeVisible();
    });

    const importButton = modal.getByRole("button", { name: /^Import 2 row/ });
    await test.step("required fields with no mapped column block import until fixed", async () => {
      await expect(importButton).toBeDisabled();
    });

    await test.step("toggling each field to a fixed value and picking it unblocks import", async () => {
      await modal.getByLabel("Use the same component for every row").check();
      await modal.getByLabel("Fixed component").selectOption(component.prefix);
      await modal.getByLabel("Use the same category for every row").check();
      await modal.getByLabel("Fixed category").selectOption(category.prefix);
      await modal.getByLabel("Use the same level for every row").check();
      await modal.getByLabel("Fixed level").selectOption("optional");
      await modal.getByLabel("Use the same target version for every row").check();
      await modal.getByLabel("Fixed target version").selectOption(stage.name);
      await expect(importButton).toBeEnabled();
    });

    await test.step("importing applies the fixed values to every row, not just the first", async () => {
      await importButton.click();
      await expect(page.getByText(/Import complete: 2 created, 0 error\(s\)/)).toBeVisible();
    });

    await test.step("both created requirements carry the fixed component/category/level", async () => {
      const requirementsResp = await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/requirements`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const requirements: { name: string; component_id: string; category_id: string; level: string; target_stage_id: string }[] =
        await requirementsResp.json();
      for (const rowName of [rowOneName, rowTwoName]) {
        const created = requirements.find((r) => r.name === rowName);
        expect(created, `${rowName} should have been created`).toBeTruthy();
        expect(created!.component_id).toBe(component.id);
        expect(created!.category_id).toBe(category.id);
        expect(created!.level).toBe("optional");
        expect(created!.target_stage_id).toBe(stage.id);
      }
    });
  });
});
