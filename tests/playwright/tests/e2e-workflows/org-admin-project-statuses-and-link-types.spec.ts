import { expect, type Page, test } from "@playwright/test";

import { ensureExpanded, loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: an organisation's project statuses and requirement link
 * types are both org-wide definition lists sharing the same
 * add/rename/reorder/delete-with-reassignment contract (§4.0 of the
 * traceability plan). Covers, for project statuses: deleting a status
 * currently assigned to real projects 409s and opens a reassignment
 * picker, reassigning moves those projects, an unused status deletes
 * immediately with no prompt, and once a single status remains its delete
 * control is disabled outright. Link types get lighter add/rename/delete-
 * unused coverage — the identical shared reassignment/last-row-disabled
 * code path is already exercised end-to-end above (statuses) and unit-
 * tested directly against link types in OrgAdminPage.stories.tsx.
 *
 * Uses the "E2E Beta Software" organisation (via Preferences > Your access
 * > Manage organisation), not Alpha, since Alpha carries the fixed custom
 * link type/requirement link `seed_e2e_dataset.py` seeds specifically for
 * requirement-links.spec.ts — this spec must not disturb those.
 */

/** Status/link-type names render as editable `<input>` value attributes
 * (the rename form), not plain text nodes — matches
 * project-admin-structural.spec.ts's own convention. */
function inputWithValue(page: Page, value: string) {
  // `:not([placeholder])`: the "add a new status/link type" row's own
  // input shares the `input.input` class and can transiently hold the
  // same text the test just typed into it — only a *rename* input for an
  // existing row is ever placeholder-less.
  return page.locator(`input.input[value="${value}"]:not([placeholder])`);
}

test.describe("org admin: project statuses and link types", () => {
  test("statuses: reassign-on-delete, plain delete, last-remaining-blocked; link types: add/rename/delete", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await test.step("navigate to Beta's org admin page via Preferences > Your access", async () => {
      await page.goto("/preferences");
      await page.getByRole("tab", { name: "Your access" }).click();
      const betaRow = page.locator(".stack", { hasText: "E2E Beta Software" }).last();
      await betaRow.getByRole("link", { name: "Manage organisation" }).click();
      await expect(page.getByRole("heading", { name: "E2E Beta Software" })).toBeVisible();
    });

    await test.step("Project statuses: the 4 seeded defaults are present", async () => {
      await ensureExpanded(page, "Project statuses");
      for (const name of ["Proposed", "Active", "Abandoned", "Completed"]) {
        await expect(inputWithValue(page, name)).toBeVisible();
      }
    });

    await test.step("rename Active, then delete Proposed (in use by Beta-1/Beta-2) with reassignment to it", async () => {
      // Not chained off `activeInput`: once filled, its own selector
      // (matched by the *old* value) no longer resolves to anything — only
      // one row is ever "dirty" at a time, so the plain, page-wide Rename
      // button is unambiguous here (same pattern as
      // project-admin-structural.spec.ts).
      await inputWithValue(page, "Active").fill("Active (E2E)");
      await page.getByRole("button", { name: "Rename" }).click();
      await expect(inputWithValue(page, "Active (E2E)")).toBeVisible();

      const proposedRow = inputWithValue(page, "Proposed").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await proposedRow.getByTitle("Delete this status").click();
      await expect(page.getByText(/used by \d+ project\(s\)/)).toBeVisible();
      await page.getByText("Reassign existing items to").locator("xpath=..").getByRole("combobox").selectOption({ label: "Active (E2E)" });
      await page.getByRole("button", { name: "Confirm delete" }).click();
      await expect(inputWithValue(page, "Proposed")).toHaveCount(0);
    });

    await test.step("Beta-1's own settings tab now shows the reassigned status", async () => {
      await page.goto("/projects");
      await page.getByText(PROJECT_NAMES.beta1).click();
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await expect(page.getByLabel("Status").locator("option:checked")).toHaveText("Active (E2E)");
    });

    await test.step("an unused status (Abandoned) deletes immediately, with no reassignment prompt", async () => {
      await page.goto("/preferences");
      await page.getByRole("tab", { name: "Your access" }).click();
      const betaRow = page.locator(".stack", { hasText: "E2E Beta Software" }).last();
      await betaRow.getByRole("link", { name: "Manage organisation" }).click();
      await ensureExpanded(page, "Project statuses");

      const abandonedRow = inputWithValue(page, "Abandoned").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await abandonedRow.getByTitle("Delete this status").click();
      await expect(inputWithValue(page, "Abandoned")).toHaveCount(0);
      await expect(page.getByText("Reassign existing items to")).toHaveCount(0);

      const completedRow = inputWithValue(page, "Completed").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await completedRow.getByTitle("Delete this status").click();
      await expect(inputWithValue(page, "Completed")).toHaveCount(0);
    });

    await test.step("with only 'Active (E2E)' left, its delete control is disabled", async () => {
      await expect(inputWithValue(page, "Active (E2E)")).toBeVisible();
      await expect(page.getByTitle("This is the only one — create another first so there's something to reassign to.")).toBeDisabled();
    });

    await test.step("Link types: add a new type, rename it, then delete it (unused, no prompt)", async () => {
      await ensureExpanded(page, "Link types");
      await expect(inputWithValue(page, "Depends on")).toBeVisible();

      const newForward = page.getByPlaceholder("Forward name").last();
      const newReverse = page.getByPlaceholder("Reverse name").last();
      await newForward.fill("E2E Precedes");
      await newReverse.fill("E2E Is preceded by");
      await page.getByRole("button", { name: "New link type" }).click();
      await expect(inputWithValue(page, "E2E Precedes")).toBeVisible();

      await inputWithValue(page, "E2E Precedes").fill("E2E Precedes v2");
      await page.getByRole("button", { name: "Rename" }).click();
      await expect(inputWithValue(page, "E2E Precedes v2")).toBeVisible();

      const row = inputWithValue(page, "E2E Precedes v2").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await row.getByTitle("Delete this link type").click();
      await expect(inputWithValue(page, "E2E Precedes v2")).toHaveCount(0);
      await expect(page.getByText("Reassign existing items to")).toHaveCount(0);
    });
  });
});
