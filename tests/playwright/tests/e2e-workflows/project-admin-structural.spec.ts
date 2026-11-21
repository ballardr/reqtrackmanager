import { expect, type Page, test } from "@playwright/test";

import { addStructureCategory, addStructureComponent, clickAndAwaitSave, createDisposableProject, installCleanupHook, loginAs, moveStageToPhase, PERSONAS, selectProjectAdminGroup, closeDialogWithoutSaving, structureRow } from "./helpers";

/**
 * Job to be done: a project's structural admin — stages, and the
 * component/category tree — supports renaming and deleting existing items,
 * with deletion requiring reassignment of whatever the item currently
 * governs to another existing one (C-G-07/C-E-01/C-E-02; a category that
 * governs nothing is deleted with no target), except a stage
 * with an approved baseline, which is refused outright rather than
 * reassigned (a baseline is an immutable historical snapshot, C-G-10).
 * Also covers project archiving (C-P-01).
 *
 * Uses its own disposable, uniquely-named project (created fresh each run,
 * seeded via direct API calls with the same Hardware/Software + Functional/
 * Performance starting shape `seed_e2e_dataset.py`'s own `seed_project_content`
 * gives every seeded project) rather than the shared "Beta-2" fixture this
 * spec used to mutate in place. Found and fixed during a branch hardening
 * pass, not part of that branch's own diff: this test renamed Beta-2's
 * default "Scoping" stage to "Milestone 1" and deleted/recreated its
 * components, so a second run — standalone or repeated, without a fresh
 * reseed in between — could no longer find "Scoping" at all, violating this
 * project's own rule that a test must pass "whether it runs alone, first,
 * last, or repeated back-to-back against the same database". Mutating a
 * shared, non-dedicated seed fixture like this is exactly the anti-pattern
 * that rule calls out; every other spec in this suite that needs full
 * control over a project's structure already uses a project dedicated to it
 * alone (see PROJECT_NAMES.delta1/gamma3/gamma4 in ./helpers.ts) rather than
 * repurposing one shared across many specs.
 *
 * Stage names are rendered as editable `<input>` value attributes (the rename form), not text nodes — the stage
 * locators below match `input[value="..."]`. Components and categories are the rows of the Structure tree, edited in a
 * side panel (`addStructureComponent`, `structureRow` in ./helpers).
 *
 * Split into three independent tests (2026-10-04), each with its own
 * disposable project created via the API: as one test it ran ~25s of the
 * 30s default budget and timed out intermittently under load.
 */

/** Creates this test's disposable project (archived afterwards by
 * `createDisposableProject`'s own cleanup) and opens its Project Admin
 * "Structure" group. */
async function openStructuralProject(page: Page, label: string) {
  const { projectId, projectName, headers: authHeaders } = await createDisposableProject(
    page.request, PERSONAS.orgAdminAlphaBeta.email, `Structural ${label}`,
  );
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await page.goto(`/projects/${projectId}/admin`);
  // Stages are under "Workflows and phases"; components and categories stay under "Structure".
  await selectProjectAdminGroup(page, label === "Stages" ? "Workflows and phases" : "Structure");
  return { projectId, projectName, authHeaders };
}

/** Confirms the plain delete's confirmation (the first step of every category delete). */
async function confirmDelete(page: Page) {
  await page.getByRole("dialog", { name: "Delete this category" }).getByRole("button", { name: "Confirm delete" }).click();
}

/** Picks the reassignment target in the in-use delete dialog (`DeleteInUseDialog`) and confirms. */
async function reassignTo(page: Page, label: string) {
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "Reassign existing items to" }).selectOption({ label });
  await dialog.getByRole("button", { name: "Confirm delete" }).click();
}

// Stages and Categories live together on the "Structure" group, each in its
// own `CollapsibleSection`; locators are scoped to one section so the two
// sections' "Name"-placeholder fields never cross-hit.
const stagesSectionOf = (page: Page) =>
  page.locator(".card", { has: page.getByRole("button", { name: "Project stages section" }) });

test.describe("project admin: structural rename/delete and archiving", () => {
  installCleanupHook();

  test("components and categories can be renamed and deleted with reassignment", async ({ page }) => {
    const { projectId, authHeaders } = await openStructuralProject(page, "Components");

    await test.step("build a two-component tree", async () => {
      await selectProjectAdminGroup(page, "Structure");
      await addStructureComponent(page, "Firmware", "FW");
      await addStructureCategory(page, "Firmware", "Timing", "TIM");
      await addStructureCategory(page, "Firmware", "Safety", "SAF");
      await addStructureComponent(page, "Sensors", "SEN");
      await addStructureCategory(page, "Sensors", "Calibration", "CAL");
      await expect(structureRow(page, "Timing")).toBeVisible();
      await expect(structureRow(page, "Calibration")).toBeVisible();
    });

    await test.step("deleting a component with categories is blocked in the UI", async () => {
      await page.getByRole("button", { name: "Actions for Firmware", exact: true }).click();
      await expect(page.getByRole("menuitem", { name: "Delete", exact: true })).toBeDisabled();
      await page.keyboard.press("Escape");
    });

    // A delete is plain first: only a category that still governs something opens the reassignment dialog.
    await test.step("deleting a category that governs a requirement offers a reassignment, first within then across components", async () => {
      const base = `http://localhost:8000/api/v1/projects/${projectId}`;
      const components: { id: string; prefix: string }[] = await (await page.request.get(`${base}/components`, { headers: authHeaders })).json();
      const categories: { id: string; prefix: string }[] = await (await page.request.get(`${base}/categories`, { headers: authHeaders })).json();
      const created = await page.request.post(`${base}/requirements`, {
        headers: authHeaders,
        data: {
          name: "Governed by Timing",
          component_id: components.find((c) => c.prefix === "FW")!.id,
          category_id: categories.find((c) => c.prefix === "TIM")!.id,
        },
      });
      expect(created.ok()).toBeTruthy();
      await page.reload();
      await selectProjectAdminGroup(page, "Structure");

      await page.getByRole("button", { name: "Actions for Timing", exact: true }).click();
      await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
      await confirmDelete(page);
      // The reassign dropdown always prefixes a category option with its owning component's name
      // ("ComponentName / CategoryName"), even within the same component.
      await reassignTo(page, "Firmware / Safety");
      await expect(structureRow(page, "Timing")).toHaveCount(0);

      await page.getByRole("button", { name: "Actions for Safety", exact: true }).click();
      await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
      await confirmDelete(page);
      await reassignTo(page, "Sensors / Calibration");
      await expect(structureRow(page, "Safety")).toHaveCount(0);
    });

    await test.step("with no categories left, the now-empty component can be deleted", async () => {
      await page.getByRole("button", { name: "Actions for Firmware", exact: true }).click();
      await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
      await page.getByRole("dialog", { name: "Delete this component" }).getByRole("button", { name: "Confirm delete" }).click();
      await expect(structureRow(page, "Firmware")).toHaveCount(0);
    });

    await test.step("an empty category is deleted with no replacement to choose", async () => {
      // Hardware's seeded Functional category holds nothing.
      await page.getByRole("button", { name: "Expand Hardware", exact: true }).click();
      await page.getByRole("button", { name: "Actions for Functional", exact: true }).click();
      await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
      await confirmDelete(page);
      await expect(structureRow(page, "Functional")).toHaveCount(0);
      await expect(page.getByRole("dialog")).toHaveCount(0);
    });
  });

  test("a prefix is suggested from the name, edited, reordered and a category moved to another component", async ({ page }) => {
    await openStructuralProject(page, "Suggestions");

    await test.step("the suggestion fills the prefix and numbers a collision", async () => {
      expect(await addStructureComponent(page, "Power Supply")).toBe("PS");
      expect(await addStructureComponent(page, "Pressure Sensors")).toBe("PS2");
      expect(await addStructureCategory(page, "Power Supply", "Fuse Block")).toBe("FB");
      expect(await addStructureCategory(page, "Power Supply", "Fan Bay")).toBe("FB2");
    });

    await test.step("a typed prefix stays while the name changes", async () => {
      await page.getByRole("button", { name: "Add component" }).click();
      const panel = page.getByRole("dialog", { name: "Add component" });
      await panel.getByRole("textbox", { name: "Name" }).fill("Cooling Loop");
      await expect(panel.getByRole("textbox", { name: "Prefix" })).toHaveValue("CL");
      await panel.getByRole("textbox", { name: "Prefix" }).fill("CLOOP");
      await panel.getByRole("textbox", { name: "Name" }).fill("Cooling Loops");
      await page.waitForTimeout(600);
      await expect(panel.getByRole("textbox", { name: "Prefix" })).toHaveValue("CLOOP");
      await clickAndAwaitSave(page, panel.getByRole("button", { name: "Save" }), "/components");
      await expect(panel).toBeHidden();
    });

    await test.step("edit changes the name and prefix", async () => {
      await page.getByRole("button", { name: "Actions for Cooling Loops", exact: true }).click();
      await page.getByRole("menuitem", { name: "Edit", exact: true }).click();
      const panel = page.getByRole("dialog", { name: "Edit component Cooling Loops" });
      await panel.getByRole("textbox", { name: "Name" }).fill("Thermal Loops");
      await expect(panel.getByRole("textbox", { name: "Prefix" })).toHaveValue("CLOOP");
      await clickAndAwaitSave(page, panel.getByRole("button", { name: "Save" }), "/components/");
      await expect(structureRow(page, "Thermal Loops")).toBeVisible();
    });

    await test.step("a component moves down and keeps its place after a reload", async () => {
      await page.getByRole("button", { name: "Actions for Power Supply", exact: true }).click();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/move") && r.request().method() === "POST"),
        page.getByRole("menuitem", { name: "Move down", exact: true }).click(),
      ]);
      await page.reload();
      await selectProjectAdminGroup(page, "Structure");
      await expect(structureRow(page, "Pressure Sensors")).toBeVisible();
      const names = await page.getByRole("treegrid", { name: "Components and categories" }).getByRole("button", { name: /^(Expand|Collapse) / }).allTextContents();
      expect(names.indexOf("Pressure Sensors")).toBeLessThan(names.indexOf("Power Supply"));
    });

    await test.step("a category moves to another component and takes it there", async () => {
      await page.getByRole("button", { name: "Actions for Fuse Block", exact: true }).click();
      await page.getByRole("menuitem", { name: "Move to another component…", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Move Fuse Block to another component" });
      await dialog.getByRole("combobox", { name: /New component/ }).selectOption({ label: "Pressure Sensors (PS2)" });
      await clickAndAwaitSave(page, dialog.getByRole("button", { name: "Move" }), "/move-to");
      await expect(dialog).toBeHidden();
      await expect(structureRow(page, "Fuse Block")).toBeVisible();
    });

    await test.step("a search opens the components that hold a match", async () => {
      await page.getByRole("textbox", { name: "Search components and categories" }).fill("fan");
      await expect(structureRow(page, "Fan Bay")).toBeVisible();
      await expect(structureRow(page, "Thermal Loops")).toHaveCount(0);
    });
  });

  test("stages can be renamed, and deleted with reassignment unless baselined", async ({ page }) => {
    const { projectId, authHeaders } = await openStructuralProject(page, "Stages");
    const stagesSection = stagesSectionOf(page);

    await test.step("a stage with an approved baseline cannot be deleted, even with a reassignment target", async () => {
      // Already on the "Structure" tab (Stages and Categories are now
      // siblings there, not separate tabs) — no tab click needed here.
      await stagesSection.locator('input[value="Scoping"]').fill("Milestone 1");
      await page.getByRole("button", { name: "Rename" }).click();
      await expect(page.locator('input.input[value="Milestone 1"]:not([placeholder])')).toBeVisible();

      await stagesSection.getByPlaceholder("Name", { exact: true }).fill("Milestone 2");
      await stagesSection.getByRole("button", { name: "New stage" }).click();
      await expect(page.locator('input.input[value="Milestone 2"]:not([placeholder])')).toBeVisible();

      const stagesResp = await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/stages`, {
        headers: authHeaders,
      });
      const stages: { id: string; name: string }[] = await stagesResp.json();
      const milestone1 = stages.find((s) => s.name === "Milestone 1")!;
      await moveStageToPhase(page.request, authHeaders, projectId, milestone1.id, "Review");
      await moveStageToPhase(page.request, authHeaders, projectId, milestone1.id, "Approved");
      // ProjectAdminPage's group is now a real route segment
      // (`ResourceMenu`, converted from `Tabs`), so a full page reload no
      // longer resets it to the default (Overview) the way client-only tab
      // state used to — the reselect below is now a harmless no-op
      // (`selectProjectAdminGroup` only clicks if not already active),
      // kept for robustness against a future reversion.
      await page.reload();
      await selectProjectAdminGroup(page, "Workflows and phases");

      // Stage order is Milestone 1(0)/Milestone 2(1).
      await stagesSection.getByTitle("Delete this stage").nth(0).click();
      await reassignTo(page, "Milestone 2");
      // The refusal is shown inside the dialog, which stays open; cancel it, and the stage is still there.
      await expect(page.getByRole("dialog").getByRole("alert")).toBeVisible();
      await closeDialogWithoutSaving(page.getByRole("dialog"), { unsaved: false });
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await expect(page.locator('input.input[value="Milestone 1"]:not([placeholder])')).toBeVisible();
    });

    await test.step("a stage with no baseline can be deleted with reassignment", async () => {
      // Milestone 1 (baselined, undeletable) is still nth(0); Milestone 2 is nth(1).
      await stagesSection.getByTitle("Delete this stage").nth(1).click();
      await reassignTo(page, "Milestone 1");
      await expect(page.locator('input.input[value="Milestone 2"]:not([placeholder])')).toHaveCount(0);
    });
  });

  test("the project can be archived then unarchived", async ({ page }) => {
    const { projectId, projectName } = await openStructuralProject(page, "Archive");

    await test.step("the project can be archived then unarchived", async () => {
      await selectProjectAdminGroup(page, "Project settings");
      await page.getByRole("button", { name: "Archive project" }).click();
      await expect(page.getByRole("button", { name: "Unarchive project" })).toBeVisible();
      await page.goto("/projects");
      await expect(page.getByText(projectName)).toHaveCount(0);

      await page.goto(`/projects/${projectId}/admin`);
      await page.getByRole("button", { name: "Unarchive project" }).click();
      await expect(page.getByRole("button", { name: "Archive project" })).toBeVisible();
    });
  });
});
