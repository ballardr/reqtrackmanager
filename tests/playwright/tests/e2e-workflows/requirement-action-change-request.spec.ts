import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * 2026-08 UX audit roadmap item 514: once a requirement is locked
 * (APPROVED/COMPLETED), adding an action to it no longer bypasses the
 * change-request-only-once-locked rule its own fields already follow
 * (`services.requirements.LOCKED_STATUSES`) — "Create and link a new
 * action" now requires a reason and submits an `ADD_ACTION` change request
 * instead of creating the action directly, and the action only actually
 * appears once a project manager approves that change request.
 *
 * The link-existing-action half of the same gate (`proposed_action_link_id`)
 * is covered by `backend/tests/test_requirement_action_change_requests.py`
 * and `RequirementDetailPage.stories.tsx`'s own interaction tests, not
 * duplicated here — this spec proves the one real end-to-end round trip
 * (create-and-link, the more common path) through the actual UI and API.
 *
 * Creates its own throwaway requirement + action type rather than
 * approving seeded data (approving isn't reversible from the UI), matching
 * `requirement-approval.spec.ts`'s own established pattern.
 */
test.describe("requirement action change requests", () => {
  test("adding an action to a locked requirement requires an approved change request", async ({ page }) => {
    const reqName = `E2E Locked Requirement ${Date.now()}`;
    const actionTitle = `E2E Proposed Action ${Date.now()}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await page.getByText(PROJECT_NAMES.alpha1).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill(reqName);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await page.getByText(reqName).click();

    await test.step("approve the requirement, locking it", async () => {
      await page.getByRole("button", { name: "Approve", exact: true }).click();
      await expect(page.getByText("Locked (approved)")).toBeVisible();
    });

    await test.step("Create and link a new action now requires a reason and creates nothing directly", async () => {
      await page.getByRole("button", { name: "Create and link a new action" }).click();
      const dialog = page.getByRole("dialog", { name: "Create and link a new action" });
      await dialog.getByPlaceholder("Title").fill(actionTitle);
      await dialog.getByLabel("Type", { exact: true }).selectOption({ label: "Review" });
      const createButton = dialog.getByRole("button", { name: "Create", exact: true });
      await expect(createButton).toBeDisabled();
      await dialog.getByLabel("Reason for change").fill("found a gap during final review");
      await expect(createButton).toBeEnabled();
      await createButton.click();

      await expect(page.getByText("Change request created")).toBeVisible();
      await expect(dialog).not.toBeVisible();
      await expect(page.getByText("No actions linked yet.")).toBeVisible();
      await expect(page.getByRole("link", { name: actionTitle })).toHaveCount(0);
    });

    await test.step("approving the resulting change request creates and links the action", async () => {
      await page.getByRole("link", { name: "Change requests", exact: true }).click();
      // The CR list falls back to the target requirement's own name when
      // `proposed_name` is null (`ChangeRequestsPage.tsx::crTitle` — true
      // for every ADD_ACTION change request, which never sets
      // `proposed_name`), the same fallback a field-only MODIFY_REQUIREMENT
      // change request already relies on.
      await page.getByText(reqName).click();
      // `exact: true` — a bare substring match would also resolve against
      // the action's own generated title text below ("E2E Proposed Action
      // <ts>"), a strict-mode violation (Playwright's default `getByText`
      // match is a case-insensitive substring, not case-sensitive).
      await expect(page.getByText("Proposed action", { exact: true })).toBeVisible();
      await expect(page.getByText(actionTitle)).toBeVisible();
      await page.getByRole("button", { name: "Submit", exact: true }).click();
      await expect(page.getByText("Change request submitted")).toBeVisible();
      await page.getByRole("button", { name: "Approve", exact: true }).click();
      await expect(page.getByText("Change request approved")).toBeVisible();
    });

    await test.step("the action now appears on the requirement", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByText(reqName).click();
      await expect(page.getByRole("link", { name: actionTitle })).toBeVisible();
    });
  });
});
