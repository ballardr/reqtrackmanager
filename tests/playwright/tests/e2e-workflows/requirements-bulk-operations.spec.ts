import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: `RequirementsPage`'s list/table view supports selecting
 * several requirements at once and applying a bulk action to all of them —
 * the first pilot of style guide "Pattern: bulk operations on a list"
 * (2026-08 UX audit roadmap: bulk operations on list pages). Covers the
 * golden path for both bulk actions: archive and move-to-stage. No new
 * backend endpoint exists for either — the page loops over the existing
 * single-requirement archive/update endpoints client-side — so this spec
 * is also the end-to-end proof that loop actually reaches the server for
 * every selected row, not just the first.
 *
 * Uses Alpha-1, logged in as its project manager (orgAdminAlphaBeta).
 * Every fixture this spec touches is created by the spec itself with a
 * per-run timestamp — a throwaway project stage (Project Admin has no
 * delete-free way to guarantee a second stage exists otherwise, since a
 * freshly created project only seeds one "Scoping" stage) and four
 * throwaway requirements — rather than reusing or mutating any seeded
 * data, per this repo's test-independence rule: this spec must pass
 * standalone or repeated back-to-back against the same database.
 */
test.describe("requirements list: bulk operations", () => {
  test("select multiple requirements, bulk-archive, and bulk-move to a stage", async ({ page }) => {
    const stamp = Date.now();
    const stageName = `E2E Bulk Target ${stamp}`;
    const names = [
      `E2E Bulk Req A ${stamp}`,
      `E2E Bulk Req B ${stamp}`,
      `E2E Bulk Req C ${stamp}`,
      `E2E Bulk Req D ${stamp}`,
    ];

    function rowCheckbox(name: string) {
      return page.locator("tr").filter({ hasText: name }).getByRole("checkbox");
    }

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await page.getByRole("link", { name: PROJECT_NAMES.alpha1, exact: true }).click();

    await test.step("add a second stage to move requirements into later", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("tab", { name: "Structure" }).click();
      await page.getByPlaceholder("Name", { exact: true }).first().fill(stageName);
      // The new stage's name renders into an editable rename `<input>`'s
      // current *value* once created, not as plain text — no DOM text
      // matcher (`getByText`) can see it, and a React-controlled input's
      // `value` attribute doesn't stay in sync with its live value either,
      // so this asserts on the `POST /stages` response itself instead of
      // fighting the DOM for a value-only check.
      const [stageResponse] = await Promise.all([
        page.waitForResponse((res) => res.url().includes("/stages") && res.request().method() === "POST"),
        page.getByRole("button", { name: "New stage" }).click(),
      ]);
      expect(stageResponse.ok()).toBeTruthy();
    });

    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "List view" }).click();

    await test.step("create four throwaway requirements", async () => {
      for (const name of names) {
        await page.getByRole("button", { name: "New requirement" }).click();
        await page.getByRole("button", { name: "Add one" }).click();
        await page.getByPlaceholder("Name", { exact: true }).fill(name);
        await page.getByRole("button", { name: "Create", exact: true }).click();
        await expect(page.getByText(name)).toBeVisible();
      }
    });

    await test.step("select two rows via their own checkboxes and bulk-archive them", async () => {
      await rowCheckbox(names[0]).check();
      await rowCheckbox(names[1]).check();
      await expect(page.getByText("2 selected")).toBeVisible();

      await page.getByRole("button", { name: "Archive selected" }).click();
      const dialog = page.getByRole("dialog", { name: "Archive 2 requirements?" });
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Archive selected" }).click();

      await expect(page.getByText("2 updated")).toBeVisible();
      await expect(page.getByText(names[0])).not.toBeVisible();
      await expect(page.getByText(names[1])).not.toBeVisible();
      // The selection and toolbar are gone once the batch completes.
      await expect(page.getByText(/\d+ selected/)).not.toBeVisible();
      await expect(page.getByRole("button", { name: "Archive selected" })).not.toBeVisible();
    });

    await test.step("select the remaining two rows and bulk-move them to the new stage", async () => {
      // Selects the two remaining fixtures via their own row checkboxes,
      // the same way the archive step above does — not the search box +
      // header "Select all" combination, which races this page's own
      // documented fetch effect (no request-cancellation guard: a fresh
      // reload still in flight from the archive step above can resolve
      // after a newly-filtered one and silently overwrite it). Header-
      // checkbox "select all loaded rows" behaviour has its own dedicated
      // Storybook coverage (`SelectAllHeaderCheckbox`); this spec only
      // needs the golden path.
      await expect(page.getByText(names[2])).toBeVisible();
      await expect(page.getByText(names[3])).toBeVisible();
      await rowCheckbox(names[2]).check();
      await rowCheckbox(names[3]).check();
      await expect(page.getByText("2 selected")).toBeVisible();

      await page.getByRole("button", { name: "Move to stage" }).click();
      const popover = page.getByRole("dialog", { name: "Move to stage" });
      await popover.getByLabel("Target version").selectOption({ label: stageName });
      await popover.getByRole("button", { name: "Move" }).click();

      const dialog = page.getByRole("dialog", { name: `Move 2 requirements to "${stageName}"?` });
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Move" }).click();

      await expect(page.getByText("2 updated")).toBeVisible();
      await expect(page.locator("tr").filter({ hasText: names[2] })).toContainText(stageName);
      await expect(page.locator("tr").filter({ hasText: names[3] })).toContainText(stageName);
    });

    await test.step("clean up the throwaway stage (reassigning its requirements back to Scoping)", async () => {
      // Unlike the four throwaway requirements above (dynamically named,
      // harmless to leave behind — same tolerance
      // project-admin-groups-and-fields.spec.ts's own custom fields get), a
      // project *stage* is a small, shared, enumerable resource other specs
      // query by role/count rather than by name — found the hard way:
      // workflow-bypass-attempts.spec.ts's `getByRole("button", { name:
      // "Start review" })` assumes exactly one "scoping"-status stage on
      // Alpha-1 and hit a strict-mode violation once this spec's own extra
      // stage was left behind uncleaned. Deleting with `reassign_to` moves
      // both fixture requirements currently on it back to Scoping first.
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("tab", { name: "Structure" }).click();
      const deleteButtons = page.getByRole("button", { name: "Delete this stage" });
      const targetDeleteButton = deleteButtons.last();
      const stageRow = targetDeleteButton.locator(
        "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' stack ')][1]"
      );
      await targetDeleteButton.click();
      await stageRow.getByRole("combobox").selectOption({ label: "Scoping" });
      await stageRow.getByRole("button", { name: "Confirm delete" }).click();
      await expect(page.getByRole("button", { name: "Delete this stage" })).toHaveCount(0);
    });
  });
});
