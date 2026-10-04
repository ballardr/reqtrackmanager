import { expect, type Page, test } from "@playwright/test";

import { loginAs, PERSONAS, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: a project's structural admin — stages, and the
 * component/category tree — supports renaming and deleting existing items,
 * with deletion requiring reassignment of whatever the item currently
 * governs to another existing one (C-G-07/C-E-01/C-E-02), except a stage
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
 * Component/category/stage names are rendered as editable `<input>` value
 * attributes (the rename form), not text nodes — every locator below
 * matches `input[value="..."]` rather than using `getByText` for them.
 *
 * Split into three independent tests (2026-10-04), each with its own
 * disposable project created via the API: as one test it ran ~25s of the
 * 30s default budget and timed out intermittently under load.
 */

/**
 * Creates a disposable project (as `orgAdminAlphaBeta`, in their first
 * organisation) seeded with the Hardware/Software + Functional/Performance
 * shape `seed_e2e_dataset.py::seed_project_content` gives every seeded
 * project, then opens its Project Admin "Structure" group.
 *
 * Returns the project id/name and the session's auth headers. Each test
 * archives its project in `afterEach` (archived projects drop off every
 * project list), so repeated runs don't push the org's seeded projects off
 * a paginated list.
 */
/** The current test's disposable project, archived by `afterEach`. */
let created: { projectId: string; authHeaders: Record<string, string> } | null = null;

async function openStructuralProject(page: Page, label: string) {
  const projectName = `Structural ${label} ${Date.now()}`;
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const authHeaders = { Authorization: `Bearer ${token}` };
  const api = "http://localhost:8000/api/v1";
  const orgs: { id: string }[] = await (await page.request.get(`${api}/orgs`, { headers: authHeaders })).json();
  const project = await (await page.request.post(`${api}/projects`, {
    headers: authHeaders, data: { organization_id: orgs[0].id, name: projectName, summary: "" },
  })).json();
  const projectId: string = project.id;
  const hw = await (await page.request.post(`${api}/projects/${projectId}/components`, {
    data: { name: "Hardware", prefix: "HW" }, headers: authHeaders,
  })).json();
  const sw = await (await page.request.post(`${api}/projects/${projectId}/components`, {
    data: { name: "Software", prefix: "SW" }, headers: authHeaders,
  })).json();
  await page.request.post(`${api}/projects/${projectId}/categories`, {
    data: { name: "Functional", prefix: "FN", component_id: hw.id }, headers: authHeaders,
  });
  await page.request.post(`${api}/projects/${projectId}/categories`, {
    data: { name: "Performance", prefix: "PERF", component_id: sw.id }, headers: authHeaders,
  });
  await page.goto(`/projects/${projectId}/admin`);
  await selectProjectAdminGroup(page, "Structure");
  created = { projectId, authHeaders };
  return { projectId, projectName, authHeaders };
}

/** Picks the reassignment target in `DefinitionList`-style delete flows and confirms. */
async function reassignTo(page: Page, label: string) {
  await page.getByText("Reassign existing items to").locator("xpath=..").getByRole("combobox").selectOption({ label });
  await page.getByRole("button", { name: "Confirm delete" }).click();
}

// Stages and Categories live together on the "Structure" group, each in its
// own `CollapsibleSection`; locators are scoped to one section so the two
// sections' "Name"-placeholder fields never cross-hit.
const stagesSectionOf = (page: Page) =>
  page.locator(".card", { has: page.getByRole("button", { name: "Project stages section" }) });
const componentsSectionOf = (page: Page) =>
  page.locator(".card", { has: page.getByRole("button", { name: "Components & categories section" }) });

test.describe("project admin: structural rename/delete and archiving", () => {
  test.afterEach(async ({ request }) => {
    if (!created) return;
    await request
      .post(`http://localhost:8000/api/v1/projects/${created.projectId}/archive`, { headers: created.authHeaders })
      .catch(() => {});
    created = null;
  });

  test("components and categories can be renamed and deleted with reassignment", async ({ page }) => {
    await openStructuralProject(page, "Components");
    const componentsSection = componentsSectionOf(page);

    // Before any additions there are 3 "Name"-placeholder fields in
    // "Components & categories" (Hardware's and Software's inline
    // add-category forms, plus the bottom add-component form) and 2 "New
    // category" buttons; each added component appends one more of each
    // just before the bottom form, so its own form/button sits at a fixed
    // index (2, then 3).
    await test.step("build a two-component tree", async () => {
      await selectProjectAdminGroup(page, "Structure");

      await componentsSection.getByPlaceholder("Name", { exact: true }).last().fill("Firmware");
      await componentsSection.getByPlaceholder("Prefix").last().fill("FW");
      await componentsSection.getByRole("button", { name: "New component" }).click();
      await expect(page.locator('input.input[value="Firmware"]:not([placeholder])')).toBeVisible();

      const firmwareCategoryName = componentsSection.getByPlaceholder("Name", { exact: true }).nth(2);
      const firmwareCategoryPrefix = componentsSection.getByPlaceholder("Prefix").nth(2);
      const firmwareNewCategoryButton = componentsSection.getByRole("button", { name: "New category" }).nth(2);
      await firmwareCategoryName.fill("Timing");
      await firmwareCategoryPrefix.fill("TIM");
      await firmwareNewCategoryButton.click();
      await expect(page.locator('input.input[value="Timing"]:not([placeholder])')).toBeVisible();

      await firmwareCategoryName.fill("Safety");
      await firmwareCategoryPrefix.fill("SAF");
      await firmwareNewCategoryButton.click();
      await expect(page.locator('input.input[value="Safety"]:not([placeholder])')).toBeVisible();

      await componentsSection.getByPlaceholder("Name", { exact: true }).last().fill("Sensors");
      await componentsSection.getByPlaceholder("Prefix").last().fill("SEN");
      await componentsSection.getByRole("button", { name: "New component" }).click();
      // Wait for Sensors' own row (and its add-category form) to actually
      // render before computing fixed-index locators below — without this,
      // .nth(3) can still resolve to the bottom add-component form (the
      // pre-Sensors 4th "Name" field) if the creation request hasn't
      // resolved yet, silently filling the wrong inputs.
      await expect(page.locator('input.input[value="Sensors"]:not([placeholder])')).toBeVisible();
      const sensorsCategoryName = componentsSection.getByPlaceholder("Name", { exact: true }).nth(3);
      const sensorsCategoryPrefix = componentsSection.getByPlaceholder("Prefix").nth(3);
      await sensorsCategoryName.fill("Calibration");
      await sensorsCategoryPrefix.fill("CAL");
      await componentsSection.getByRole("button", { name: "New category" }).nth(3).click();
      await expect(page.locator('input.input[value="Calibration"]:not([placeholder])')).toBeVisible();
    });

    // Component order is Hardware(0)/Software(1)/Firmware(2)/Sensors(3);
    // Hardware and Software each still have their own single seeded
    // category, so all four currently show the *blocked* delete title —
    // Firmware is nth(2) among those.
    await test.step("deleting a component with categories is blocked in the UI", async () => {
      await expect(componentsSection.getByTitle("Delete or reassign this component's categories first.").nth(2)).toBeDisabled();
    });

    // Category order is Functional(HW,0)/Performance(SW,1)/Timing(FW,2)/
    // Safety(FW,3)/Calibration(SEN,4) — every category's delete button is
    // enabled (the "at least one other category exists" check is
    // project-wide, not per-component), so this needs explicit indices too.
    await test.step("deleting a category reassigns whatever it governs, first within then across components", async () => {
      await componentsSection.getByTitle("Delete this category").nth(2).click(); // Timing
      // The reassign dropdown always prefixes a category option with its
      // owning component's name ("ComponentName / CategoryName"), even
      // within the same component.
      await reassignTo(page, "Firmware / Safety");
      await expect(page.locator('input.input[value="Timing"]:not([placeholder])')).toHaveCount(0);

      // Timing's removal shifted Safety from index 3 to index 2.
      await componentsSection.getByTitle("Delete this category").nth(2).click(); // Safety
      await reassignTo(page, "Sensors / Calibration");
      await expect(page.locator('input.input[value="Safety"]:not([placeholder])')).toHaveCount(0);
    });

    await test.step("with no categories left, the now-empty component can be deleted", async () => {
      // Firmware is now the only component with zero categories, so its
      // delete button is uniquely titled "Delete this component" (not the
      // blocked variant) — no index needed.
      await componentsSection.getByTitle("Delete this component").click();
      await page.getByRole("button", { name: "Confirm delete" }).click();
      await expect(page.locator('input.input[value="Firmware"]:not([placeholder])')).toHaveCount(0);
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
      await page.request.post(
        `http://localhost:8000/api/v1/projects/${projectId}/stages/${milestone1.id}/transition?new_status=review`,
        { headers: authHeaders }
      );
      await page.request.post(
        `http://localhost:8000/api/v1/projects/${projectId}/stages/${milestone1.id}/transition?new_status=approved`,
        { headers: authHeaders }
      );
      // ProjectAdminPage's group is now a real route segment
      // (`ResourceMenu`, converted from `Tabs`), so a full page reload no
      // longer resets it to the default (Overview) the way client-only tab
      // state used to — the reselect below is now a harmless no-op
      // (`selectProjectAdminGroup` only clicks if not already active),
      // kept for robustness against a future reversion.
      await page.reload();
      await selectProjectAdminGroup(page, "Structure");

      // Stage order is Milestone 1(0)/Milestone 2(1).
      await stagesSection.getByTitle("Delete this stage").nth(0).click();
      await reassignTo(page, "Milestone 2");
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
