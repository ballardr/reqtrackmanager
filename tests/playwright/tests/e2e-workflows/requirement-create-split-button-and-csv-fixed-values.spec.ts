import { expect, test } from "@playwright/test";

import { loginAs, openProject, PERSONAS, PROJECT_NAMES } from "./helpers";
import { expectListAction } from "../listActions";

/**
 * Job to be done: two pieces of the requirement list's creation and bulk flow that the rest of the suite
 * exercises indirectly but never proves directly:
 *
 * - "New requirement" is a plain button: one click opens the create form with no menu stop, and the list's
 *   shared Export and Import controls sit beside it (not behind a chevron).
 * - The import wizard is a real `role="dialog"` layer, and a column with a closed list of values (component,
 *   category, level, target version) can take one fixed value for every row, producing the right import result
 *   end to end.
 */
test.describe("New Requirement trigger and the list's Export and Import", () => {
  test("a plain click opens the create form directly; Export and Import sit beside it, not behind it", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    await test.step("Export and Import are on the title row, with no hidden alternatives menu", async () => {
      await expect(page.getByRole("button", { name: "List actions", exact: true })).toBeVisible();
      await expectListAction(page, "Import from CSV");
      await expect(page.getByRole("button", { name: "More options" })).toHaveCount(0);
    });

    await test.step("a plain click on the main button opens the create form with no menu stop", async () => {
      await page.getByRole("button", { name: "New requirement", exact: true }).click();
      await expect(page.getByRole("dialog", { name: "New requirement" })).toBeVisible();
      await expect(page.getByPlaceholder("Name", { exact: true })).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog", { name: "New requirement" })).toHaveCount(0);
    });
  });
});

test.describe("CSV import wizard: Modal-hosted mapping step and per-column fixed values", () => {
  test("mapping step opens as a Modal, and fixed-value toggles apply one value to every row", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.beta1);
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
    await expect(fileInput).toBeAttached();
    await fileInput.setInputFiles({ name: "names-only.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });

    const modal = page.getByRole("dialog", { name: "Import Requirements" });
    await test.step("the wizard is a real Modal dialog on top of the page, not an inline block", async () => {
      await expect(modal).toBeVisible();
      await expect(modal.getByLabel("Map Name")).toHaveValue("name");
      await expect(page.getByRole("button", { name: "List actions", exact: true })).toBeVisible();
    });

    const previewButton = modal.getByRole("button", { name: "Preview" });
    await test.step("required columns with no source block the preview until fixed", async () => {
      await expect(previewButton).toBeDisabled();
    });

    await test.step("toggling each column to a fixed value and picking it unblocks the preview", async () => {
      await modal.getByLabel("Use the same component for every row").check();
      await modal.getByLabel("Fixed component").selectOption(component.prefix);
      await modal.getByLabel("Use the same category for every row").check();
      await modal.getByLabel("Fixed category").selectOption(category.prefix);
      await modal.getByLabel("Use the same level for every row").check();
      await modal.getByLabel("Fixed level").selectOption("Optional");
      await modal.getByLabel("Use the same target version for every row").check();
      await modal.getByLabel("Fixed target version").selectOption(stage.name);
      await expect(previewButton).toBeEnabled();
    });

    await test.step("the preview and apply cover every row, not just the first", async () => {
      await previewButton.click();
      await expect(modal.getByText("2 to create, 0 to update, 0 unchanged, 0 with errors.")).toBeVisible();
      await modal.getByRole("button", { name: "Apply 2 change(s)" }).click();
      await expect(page.getByText("2 created, 0 updated, 0 failed.")).toBeVisible();
      await expect(modal).toHaveCount(0);
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
