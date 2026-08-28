import { expect, test } from "@playwright/test";

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
 */
test.describe("project admin: structural rename/delete and archiving", () => {
  test("stages, components, and categories can be renamed and deleted with reassignment", async ({ page }) => {
    let projectId = "";
    const projectName = `Structural Test ${Date.now()}`;

    await test.step("PM creates a disposable project and seeds its starting structure", async () => {
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.goto("/projects");
      await page.getByRole("button", { name: "New project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      // Which org this lands in doesn't matter to anything below — left on
      // the dialog's own default (orgAdminAlphaBeta manages both Alpha and
      // Beta) rather than explicitly switched, since switching away from
      // the default here triggers a dependent Parent-project-list refetch
      // that intermittently outraces Playwright's own selectOption action on
      // a slower run (the org does end up correctly selected either way —
      // this is a test-interaction timing quirk, not a product bug: a human
      // clicking the dropdown at normal speed never hits it).
      await dialog.getByLabel("Name", { exact: true }).fill(projectName);
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
      projectId = page.url().match(/projects\/([0-9a-f-]+)/)![1];

      // Same Hardware/Software + Functional/Performance starting shape
      // `seed_e2e_dataset.py::seed_project_content` gives every seeded
      // project (Beta-2 included) — created directly via API rather than
      // through the UI form this spec's own "build a two-component tree"
      // step already exercises below, so this setup step isn't itself
      // duplicating the behaviour under test.
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const authHeaders = { Authorization: `Bearer ${token}` };
      const hwResp = await page.request.post(`http://localhost:8000/api/v1/projects/${projectId}/components`, {
        data: { name: "Hardware", prefix: "HW" }, headers: authHeaders,
      });
      const hw = await hwResp.json();
      const swResp = await page.request.post(`http://localhost:8000/api/v1/projects/${projectId}/components`, {
        data: { name: "Software", prefix: "SW" }, headers: authHeaders,
      });
      const sw = await swResp.json();
      await page.request.post(`http://localhost:8000/api/v1/projects/${projectId}/categories`, {
        data: { name: "Functional", prefix: "FN", component_id: hw.id }, headers: authHeaders,
      });
      await page.request.post(`http://localhost:8000/api/v1/projects/${projectId}/categories`, {
        data: { name: "Performance", prefix: "PERF", component_id: sw.id }, headers: authHeaders,
      });

      await page.reload();
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
    });

    // Stages and Categories now live together on one merged "Structure"
    // tab (2026-08 UX audit roadmap: Project Admin's 8 tabs -> 5), each as
    // its own `CollapsibleSection` — both mounted simultaneously, unlike
    // the old separate tabs. "Project stages" has its own "Name"-
    // placeholder "add stage" field, so every Name/Prefix/rename-adjacent
    // locator below is scoped to "Components & categories" specifically
    // rather than page-wide, to avoid cross-hitting it (or vice versa).
    const stagesSection = page.locator(".card", { has: page.getByRole("button", { name: "Project stages section" }) });
    const componentsSection = page.locator(".card", { has: page.getByRole("button", { name: "Components & categories section" }) });

    // Beta-2 seeds with exactly 2 components (Hardware, Software), each with
    // 1 category — so before any additions there are 3 "Name"-placeholder
    // fields within the "Components & categories" section (Hardware's and
    // Software's own inline add-category forms, plus the bottom-level
    // add-component form) and 2 "New category" buttons. Every component we
    // add below appends one more of each, always immediately before the
    // bottom add-component form — so a new component's own add-category
    // form/button sits at a *fixed, known* index (2, then 3) for the rest
    // of the test, unaffected by how many categories get created under it
    // afterward (a created category renders as a plain rename `<input>`
    // with no placeholder, not an additional "Name"-placeholder match).
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

    async function reassignTo(label: string) {
      await page.getByText("Reassign existing items to").locator("xpath=..").getByRole("combobox").selectOption({ label });
      await page.getByRole("button", { name: "Confirm delete" }).click();
    }

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
      await reassignTo("Firmware / Safety");
      await expect(page.locator('input.input[value="Timing"]:not([placeholder])')).toHaveCount(0);

      // Timing's removal shifted Safety from index 3 to index 2.
      await componentsSection.getByTitle("Delete this category").nth(2).click(); // Safety
      await reassignTo("Sensors / Calibration");
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

    await test.step("a stage with an approved baseline cannot be deleted, even with a reassignment target", async () => {
      // Already on the "Structure" tab (Stages and Categories are now
      // siblings there, not separate tabs) — no tab click needed here.
      await stagesSection.locator('input[value="Scoping"]').fill("Milestone 1");
      await page.getByRole("button", { name: "Rename" }).click();
      await expect(page.locator('input.input[value="Milestone 1"]:not([placeholder])')).toBeVisible();

      await stagesSection.getByPlaceholder("Name", { exact: true }).fill("Milestone 2");
      await stagesSection.getByRole("button", { name: "New stage" }).click();
      await expect(page.locator('input.input[value="Milestone 2"]:not([placeholder])')).toBeVisible();

      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const stagesResp = await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}/stages`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const stages: { id: string; name: string }[] = await stagesResp.json();
      const milestone1 = stages.find((s) => s.name === "Milestone 1")!;
      await page.request.post(
        `http://localhost:8000/api/v1/projects/${projectId}/stages/${milestone1.id}/transition?new_status=review`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      await page.request.post(
        `http://localhost:8000/api/v1/projects/${projectId}/stages/${milestone1.id}/transition?new_status=approved`,
        { headers: { Authorization: `Bearer ${token}` } }
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
      await reassignTo("Milestone 2");
      await expect(page.locator('input.input[value="Milestone 1"]:not([placeholder])')).toBeVisible();
    });

    await test.step("a stage with no baseline can be deleted with reassignment", async () => {
      // Milestone 1 (baselined, undeletable) is still nth(0); Milestone 2 is nth(1).
      await stagesSection.getByTitle("Delete this stage").nth(1).click();
      await reassignTo("Milestone 1");
      await expect(page.locator('input.input[value="Milestone 2"]:not([placeholder])')).toHaveCount(0);
    });

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
