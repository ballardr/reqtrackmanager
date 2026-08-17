import { expect, test } from "@playwright/test";

import { loginAs, openRequirementByCode, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: a requirement action (e.g. review, test) can be created
 * and linked to a requirement in one step, has its own outcome/comment/
 * attachment lifecycle independent of that requirement, can be shared by
 * being linked to a second requirement, and unlinking from one requirement
 * never affects the other or deletes the action itself (C-A-06 — actions
 * are archived, never hard-deleted, and unlinking is even lighter than
 * archiving).
 *
 * Uses Alpha-1's HW-FN-005/SW-PERF-006 (untouched by any other spec) for
 * the create/link/transition/unlink flow below, rather than the fixed "E2E
 * Review Action"/"E2E Test Action" fixtures `seed_e2e_dataset.py` already
 * attaches to HW-FN-003/SW-PERF-004 for other specs' read-only use.
 *
 * The action's title also appears as plain `<option>` text in every
 * "link existing action" picker on the project (including its own card,
 * once unlinked) — every presence/absence check below is scoped to the
 * `link` role (its actual rendered `<a>`) rather than a bare `getByText`,
 * so it can never resolve to a dropdown option instead.
 */
test.describe("requirement actions", () => {
  test("create-and-link, transition outcome, comment/attach, link to a second requirement, unlink from one only", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.alpha1).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    await test.step("create and link a new action from HW-FN-005's Actions card", async () => {
      await openRequirementByCode(page, "HW-FN-005");
      await page.getByRole("button", { name: "Create and link a new action" }).click();
      await page.getByPlaceholder("Title").fill("E2E Action Flow Test");
      await page.getByLabel("Type", { exact: true }).selectOption({ label: "Review" });
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("link", { name: /E2E Action Flow Test/ })).toBeVisible();
      await expect(page.getByText("Pending", { exact: true })).toBeVisible();
    });

    await test.step("open the action detail page and transition its outcome to Failed", async () => {
      await page.getByRole("link", { name: /E2E Action Flow Test/ }).click();
      await expect(page.getByRole("heading", { name: /E2E Action Flow Test/ })).toBeVisible();
      await expect(page.getByLabel("Outcome", { exact: true })).toHaveValue("pending");
      await page.getByLabel("Outcome", { exact: true }).selectOption("failed");
      await expect(page.getByLabel("Outcome", { exact: true })).toHaveValue("failed");
      await expect(page.getByText(/Completed:/)).toBeVisible();
    });

    await test.step("add a comment on the action's own discussion thread", async () => {
      await page.getByPlaceholder("Add comment").fill("E2E: investigating the failure.");
      await page.getByRole("button", { name: "Add comment", exact: true }).click();
      await expect(page.getByText("E2E: investigating the failure.")).toBeVisible();
    });

    await test.step("attach a file directly to the action", async () => {
      // The Attachments card's own upload input renders before the
      // Discussion card's hidden "attach to a new comment" file input, in
      // that DOM order — `.first()` targets the direct action attachment,
      // not a comment attachment.
      const fileInput = page.locator('input[type="file"]').first();
      await fileInput.setInputFiles({ name: "failure-log.txt", mimeType: "text/plain", buffer: Buffer.from("E2E failure log") });
      await expect(page.getByText("failure-log.txt")).toBeVisible();
    });

    await test.step("HW-FN-005 shows the action with its Failed outcome", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-005");
      await expect(page.getByRole("link", { name: /E2E Action Flow Test/ })).toBeVisible();
      await expect(page.getByText("Failed", { exact: true })).toBeVisible();
    });

    await test.step("link the same action to SW-PERF-006 via 'link existing action'", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "SW-PERF-006");
      // The select and the confirm button both carry the same accessible
      // text ("Link existing action") — `combobox` role picks the <select>
      // unambiguously, leaving `button` role for the confirm click below.
      const existingSelect = page.getByRole("combobox", { name: "Link existing action" });
      const actionValue = await existingSelect.locator("option", { hasText: "E2E Action Flow Test" }).last().getAttribute("value");
      await existingSelect.selectOption(actionValue!);
      await page.getByRole("button", { name: "Link existing action" }).click();
      await expect(page.getByRole("link", { name: /E2E Action Flow Test/ })).toBeVisible();
    });

    await test.step("unlinking from HW-FN-005 does not remove it from SW-PERF-006", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-005");
      const actionRow = page.locator(".row", { hasText: "E2E Action Flow Test" }).last();
      await actionRow.getByTitle("Unlink").click();
      // Not `getByText`: the now-unlinked (but still existing) action
      // reappears as an `<option>` in this same card's "link existing
      // action" picker, which also contains this substring — the `link`
      // role only matches its actual rendered `<a>`.
      await expect(page.getByRole("link", { name: /E2E Action Flow Test/ })).toHaveCount(0);

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "SW-PERF-006");
      await expect(page.getByRole("link", { name: /E2E Action Flow Test/ })).toBeVisible();
    });

    await test.step("the action is still reachable and intact from the project's Actions list", async () => {
      await page.getByRole("link", { name: "Actions", exact: true }).click();
      await expect(page.getByRole("link", { name: /E2E Action Flow Test/ })).toBeVisible();
      await expect(page.locator("tr", { hasText: "E2E Action Flow Test" }).getByText("Failed")).toBeVisible();
    });
  });
});
