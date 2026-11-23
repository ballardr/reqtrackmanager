import { expect, test } from "@playwright/test";

import { approveRequirementFromDetail, loginAs, openProject, openRequirementByName, PERSONAS, PROJECT_NAMES, searchChangeRequests, expectRecordLocked, promoteTo } from "./helpers";

/**
 * Once a requirement is locked (APPROVED/COMPLETED), adding an action to it follows the change-request-only-once-locked
 * rule its own fields follow (`services.requirements.LOCKED_STATUSES`): "Create and link a new action" requires a
 * reason and submits an `ADD_ACTION` change request, and the action appears only once a project manager approves it.
 *
 * The link-existing-action half of the gate (`proposed_action_link_id`) is covered by
 * `backend/tests/test_requirement_action_change_requests.py` and `RequirementDetailPage.stories.tsx`; this spec
 * proves the end-to-end round trip for create-and-link through the UI and API.
 *
 * Creates its own throwaway requirement and action type rather than approving seeded data (approving is not
 * reversible from the UI), as `requirement-approval.spec.ts` does.
 */
test.describe("requirement action change requests", () => {
  test("adding an action to a locked requirement requires an approved change request", async ({ page }) => {
    const reqName = `E2E Locked Requirement ${Date.now()}`;
    const actionTitle = `E2E Proposed Action ${Date.now()}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill(reqName);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await openRequirementByName(page, reqName);

    await test.step("approve the requirement, locking it", async () => {
      await approveRequirementFromDetail(page);
      await expectRecordLocked(page);
    });

    await test.step("Create and link a new action now requires a reason and creates nothing directly", async () => {
      await page.getByRole("button", { name: "Create and link a new action" }).click();
      const dialog = page.getByRole("dialog", { name: "Create and link a new action" });
      await dialog.getByLabel("Title").fill(actionTitle);
      await dialog.getByLabel("Type", { exact: true }).selectOption({ label: "Review" });
      const createButton = dialog.getByRole("button", { name: "Create", exact: true });
      await expect(createButton).toBeDisabled();
      await dialog.getByLabel("Reason for change").fill("found a gap during final review");
      await expect(createButton).toBeEnabled();
      await createButton.click();

      await expect(page.getByText(/Change request( \S+-\d+)? created/)).toBeVisible();
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
      // change request already relies on. Searched first: the list is
      // paginated, and its search matches the target requirement's name.
      await searchChangeRequests(page, reqName);
      await page.getByText(reqName).click();
      // `exact: true` — a bare substring match would also resolve against
      // the action's own generated title text below ("E2E Proposed Action
      // <ts>"), a strict-mode violation (Playwright's default `getByText`
      // match is a case-insensitive substring, not case-sensitive).
      await expect(page.getByText("Proposed action", { exact: true })).toBeVisible();
      await expect(page.getByText(actionTitle)).toBeVisible();
      await promoteTo(page, "Submitted");
      await expect(page.getByText("Change request submitted")).toBeVisible();
      await promoteTo(page, "Approved");
      await expect(page.getByText("Change request approved")).toBeVisible();
    });

    await test.step("the action now appears on the requirement", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByName(page, reqName);
      await expect(page.getByRole("link", { name: actionTitle })).toBeVisible();
    });
  });
});
