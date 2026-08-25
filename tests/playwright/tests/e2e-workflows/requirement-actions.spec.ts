import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: a requirement action (e.g. review, test) can be created
 * and linked to a requirement in one step, has its own outcome/comment/
 * attachment lifecycle independent of that requirement, can be shared by
 * being linked to a second requirement, and unlinking from one requirement
 * never affects the other or deletes the action itself (C-A-06 — actions
 * are archived, never hard-deleted, and unlinking is even lighter than
 * archiving).
 *
 * Uses two throwaway requirements created fresh by this run, not Alpha-1's
 * seeded HW-FN-005/SW-PERF-006 as this spec originally did — item 514
 * (actions gated behind a change request once a requirement is locked)
 * turned "untouched by any other spec" into a false assumption:
 * `workflow-bypass-attempts.spec.ts` approves Alpha-1's whole "Scoping"
 * stage baseline as part of its own scenario, which locks *every*
 * requirement in that stage as a side effect — including these two, even
 * though neither is touched by name. That's a one-way lock (no
 * "unapprove stage" action exists), so once that spec has run once against
 * a given database, HW-FN-005/SW-PERF-006 stay locked for good and this
 * spec's own direct create-and-link/link-existing calls would be — correctly,
 * post-514 — rejected with a 409. A throwaway, freshly-created requirement
 * starts `draft` and was never a target of any other spec's stage-baseline
 * approval, so it isn't exposed to this at all. Per this repo's own test-
 * independence rule, a spec must pass whether it runs alone, first, last,
 * or after `workflow-bypass-attempts.spec.ts` specifically — not just
 * once against a freshly seeded database before that spec has ever run.
 *
 * The action's title also appears as plain `<option>` text in every
 * "link existing action" picker on the project (including its own card,
 * once unlinked) — every presence/absence check below is scoped to the
 * `link` role (its actual rendered `<a>`) rather than a bare `getByText`,
 * so it can never resolve to a dropdown option instead.
 *
 * 2026-08 UX audit, sixth pass: "Link existing action" now opens a
 * `Popover` and "Create and link a new action" now opens a `Modal`
 * (previously a permanently-visible inline select+button row and an
 * inline-reveal block, respectively — the latter briefly a `SidePanel`
 * before the Principle 3 revision moved every entity-create flow onto
 * `Modal`), and unlinking now goes through a `ConfirmDialog` (Tier 1)
 * instead of firing immediately.
 *
 * The action title is timestamped (`E2E Action Flow Test <ts>`), not a
 * fixed string — this spec creates one via `createAndLinkAction` and
 * asserts on it by name throughout, so a fixed title would collect
 * duplicate actions across repeated runs against the same database and
 * break the strict-mode-unique locators below (found exactly this way:
 * two stale same-titled actions from earlier runs made
 * `getByRole("link", { name: /E2E Action Flow Test/ })` resolve to two
 * elements). Per this repo's own test-independence rule, a spec must pass
 * standalone or repeated back-to-back against the same database, not just
 * once against a freshly seeded one.
 */
test.describe("requirement actions", () => {
  test("create-and-link, transition outcome, comment/attach, link to a second requirement, unlink from one only", async ({ page }) => {
    const actionTitle = `E2E Action Flow Test ${Date.now()}`;
    const ts = Date.now();
    const req1Name = `E2E Action Target 1 ${ts}`;
    const req2Name = `E2E Action Target 2 ${ts}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.alpha1).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    await test.step("create two throwaway target requirements", async () => {
      for (const name of [req1Name, req2Name]) {
        await page.getByRole("button", { name: "New Requirement" }).click();
        const createPanel = page.getByRole("dialog", { name: "New Requirement" });
        await createPanel.getByPlaceholder("Name", { exact: true }).fill(name);
        await createPanel.getByRole("button", { name: "Create", exact: true }).click();
        await expect(createPanel).not.toBeVisible();
      }
    });

    await test.step("create and link a new action from the first requirement's Actions card", async () => {
      await page.getByText(req1Name).click();
      await page.getByRole("button", { name: "Create and link a new action" }).click();
      const panel = page.getByRole("dialog", { name: "Create and link a new action" });
      await panel.getByPlaceholder("Title").fill(actionTitle);
      await panel.getByLabel("Type", { exact: true }).selectOption({ label: "Review" });
      await panel.getByRole("button", { name: "Create", exact: true }).click();
      await expect(panel).not.toBeVisible();
      await expect(page.getByRole("link", { name: actionTitle })).toBeVisible();
      await expect(page.getByText("Pending", { exact: true })).toBeVisible();
    });

    await test.step("open the action detail page and transition its outcome to Failed", async () => {
      await page.getByRole("link", { name: actionTitle }).click();
      await expect(page.getByRole("heading", { name: new RegExp(actionTitle) })).toBeVisible();
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

    await test.step("the first requirement shows the action with its Failed outcome", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByText(req1Name).click();
      await expect(page.getByRole("link", { name: actionTitle })).toBeVisible();
      await expect(page.getByText("Failed", { exact: true })).toBeVisible();
    });

    await test.step("link the same action to the second requirement via 'link existing action'", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByText(req2Name).click();
      // The trigger button, the popover's own dialog aria-label, its
      // `<select>`, and its confirm button all carry the same accessible
      // text ("Link existing action") — the trigger click is unambiguous
      // since the popover doesn't exist yet, and every lookup after that
      // is scoped to the opened `dialog` so it can't match the trigger.
      await page.getByRole("button", { name: "Link existing action", exact: true }).click();
      const popover = page.getByRole("dialog", { name: "Link existing action" });
      const existingSelect = popover.getByRole("combobox", { name: "Link existing action" });
      const actionValue = await existingSelect.locator("option", { hasText: actionTitle }).last().getAttribute("value");
      await existingSelect.selectOption(actionValue!);
      await popover.getByRole("button", { name: "Link existing action" }).click();
      await expect(popover).not.toBeVisible();
      await expect(page.getByRole("link", { name: actionTitle })).toBeVisible();
    });

    await test.step("unlinking from the first requirement (confirming the ConfirmDialog) does not remove it from the second", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByText(req1Name).click();
      const actionRow = page.locator(".row", { hasText: actionTitle }).last();
      await actionRow.getByTitle("Unlink").click();
      const dialog = page.getByRole("dialog", { name: "Unlink this action?" });
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Unlink" }).click();
      await expect(dialog).not.toBeVisible();
      // Not `getByText`: the now-unlinked (but still existing) action
      // reappears as an `<option>` in this same card's "link existing
      // action" picker, which also contains this substring — the `link`
      // role only matches its actual rendered `<a>`.
      await expect(page.getByRole("link", { name: actionTitle })).toHaveCount(0);

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByText(req2Name).click();
      await expect(page.getByRole("link", { name: actionTitle })).toBeVisible();
    });

    await test.step("the action is still reachable and intact from the project's Actions list", async () => {
      await page.getByRole("link", { name: "Actions", exact: true }).click();
      await expect(page.getByRole("link", { name: actionTitle })).toBeVisible();
      await expect(page.locator("tr", { hasText: actionTitle }).getByText("Failed")).toBeVisible();
    });
  });
});
