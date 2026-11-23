import { expect, test } from "@playwright/test";

import { approveRequirementFromDetail, chooseRecordAction, loginAs, logout, openProject, openRequirementByName, PERSONAS, PROJECT_NAMES, searchChangeRequests } from "./helpers";

/**
 * Job to be done: a stakeholder who spots a problem with an approved (locked) requirement can propose a fix but cannot
 * approve their own proposal; approval is a separate project-manager action by someone else. This is the
 * separation-of-duties guarantee of the change-request workflow (C-G-12).
 *
 * Personas: StakeholderAlphaOnly (submits, cannot approve) and OrgAdminAlphaBeta (the project's PM as its creator).
 */
test("change request submitter cannot approve their own request; the project manager does", async ({ page }) => {
  const proposedName = `Respond within 30ms (E2E ${Date.now()})`;
  let crStatusAfterSubmit = "";

  await test.step("stakeholder submits a change request against the locked requirement", async () => {
    await loginAs(page, PERSONAS.stakeholderAlpha.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Change requests", exact: true }).click();
    await page.getByRole("button", { name: "New change request" }).click();
    // The create form is a `Modal` portalled to the end of `document.body`; scope to it, because an unscoped
    // `getByRole("combobox").first()` resolves to the filter sidebar's Status select, which precedes it in DOM order.
    const dialog = page.getByRole("dialog", { name: "New change request" });
    // "Modify requirement" is the default radio and the select defaults to the project's first requirement (the locked
    // HW-FN-001 by the seed) once the project data loads; wait for that, or a fast click submits an empty requirement_id.
    await expect(dialog.getByRole("combobox").first()).toContainText("HW-FN-001");
    // A field's proposed value is editable (and part of `changed_fields`) only once its "Fields to change" checkbox is
    // ticked. The checkbox and its inline editor share a field-row container, so scope the fill to that row.
    const nameCheckbox = page.getByRole("checkbox", { name: "Name", exact: true });
    await nameCheckbox.check();
    await nameCheckbox.locator("xpath=../..").locator("input.input").fill(proposedName);
    const reasoningCheckbox = page.getByRole("checkbox", { name: "Reasoning", exact: true });
    await reasoningCheckbox.check();
    await reasoningCheckbox.locator("xpath=../..").locator("textarea.input").fill("Tighter latency target after field testing.");
    await page.getByLabel("Reason for change").fill("Customer escalation on response time.");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await searchChangeRequests(page, proposedName);
    await expect(page.getByText(proposedName)).toBeVisible();
  });

  await test.step("stakeholder submits it for review and sees no approve/reject controls", async () => {
    await page.getByText(proposedName).click();
    await page.getByRole("button", { name: "Submit", exact: true }).click();
    await expect(page.getByText("Submitted", { exact: true })).toBeVisible();
    // Exact match: the advisory "Vote to approve"/"Vote to reject" (C-R-03) would substring-match a loose query; the
    // decision controls asserted absent are the exact "Approve"/"Reject" buttons gated to project managers.
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reject", exact: true })).toHaveCount(0);
    crStatusAfterSubmit = "Submitted";
  });

  await test.step("a direct API call to decide it is rejected server-side, not just hidden client-side", async () => {
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const url = page.url();
    const match = url.match(/change-requests\/([0-9a-f-]+)/);
    const crId = match?.[1];
    const projectMatch = url.match(/projects\/([0-9a-f-]+)/);
    const projectId = projectMatch?.[1];
    const resp = await page.request.post(
      `http://localhost:8000/api/v1/projects/${projectId}/change-requests/${crId}/decide`,
      { headers: { Authorization: `Bearer ${token}` }, data: { approve: true, note: "self-approval attempt" } }
    );
    expect(resp.status()).toBe(403);
  });

  await test.step("logout, log back in as the project manager, and approve it through the real UI", async () => {
    await logout(page);
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Change requests", exact: true }).click();
    await searchChangeRequests(page, proposedName);
    await page.getByText(proposedName).click();
    // React Router 7 wraps navigation in startTransition, so the URL updates while the previous page stays mounted
    // briefly: the change requests list (its Status <select> has a "Submitted" option) can coexist with this detail
    // view and make the status text ambiguous. This CR's own heading, which the list lacks, proves the transition landed.
    await expect(page.getByRole("heading", { name: proposedName, level: 1 })).toBeVisible();
    await expect(page.getByText(crStatusAfterSubmit, { exact: true })).toBeVisible();
    await page.getByPlaceholder("Decision note").fill("Approved — matches the new latency budget.");
    // Exact match: the PM also sees the advisory "Vote to approve" button (managers inherit voting rights).
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();
  });

  await test.step("the requirement now reflects the approved change", async () => {
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    // Role-scoped, not a page-wide getByText: with the startTransition timing above, the change request's
    // "Name: {proposedName}" summary can briefly coexist with the list; the requirement link is unambiguous
    // (as in golden-path.spec.ts). Searched first: the list is paginated and shared Alpha-1 grows every run.
    await page.getByPlaceholder("Search by name or ID").fill(proposedName);
    await expect(page.getByRole("link", { name: proposedName })).toBeVisible();
  });
});

/**
 * C-G-11: a MODIFY_REQUIREMENT change request against a completed requirement gives the deciding project manager a
 * choice: plain "Approve" (keeps completion; pinned by backend pytest) or "Approve and clear completion" (this test),
 * which sends `clear_completion: true` and drops the requirement's `is_completed` overlay so it returns to the
 * due-for-review path. Creates its own requirement (approved, then completed), because completing a shared one would
 * leak state into other specs and runs.
 */
test("a project manager sees and can use 'Approve and clear completion' on a CR targeting a completed requirement", async ({ page }) => {
  const reqName = `E2E Completed Target ${Date.now()}`;
  const proposedName = `${reqName} (revised)`;

  await test.step("PM creates, approves, and completes a throwaway requirement", async () => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill(reqName);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await openRequirementByName(page, reqName);

    await approveRequirementFromDetail(page);
    await expect(page.getByText("Locked (approved)")).toBeVisible();
    await page.getByRole("button", { name: "Mark completed" }).click();
    await expect(page.getByText("Completed", { exact: true })).toBeVisible();
  });

  await test.step("PM submits a modify-requirement change request against it", async () => {
    await chooseRecordAction(page, "Requirement", "Make change request");
    const dialog = page.getByRole("dialog", { name: "New change request" });
    await expect(dialog.getByRole("combobox").first()).toContainText(reqName);
    const nameCheckbox = page.getByRole("checkbox", { name: "Name", exact: true });
    await nameCheckbox.check();
    await nameCheckbox.locator("xpath=../..").locator("input.input").fill(proposedName);
    await page.getByLabel("Reason for change").fill("Substantive rework, needs re-verifying.");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await searchChangeRequests(page, proposedName);
    await expect(page.getByText(proposedName)).toBeVisible();
    await page.getByText(proposedName).click();
    await page.getByRole("button", { name: "Submit", exact: true }).click();
    await expect(page.getByText("Submitted", { exact: true })).toBeVisible();
  });

  await test.step("the decision view offers both plain Approve and Approve and clear completion", async () => {
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeVisible();
    const clearCompletionButton = page.getByRole("button", { name: "Approve and clear completion" });
    await expect(clearCompletionButton).toBeVisible();
    await clearCompletionButton.click();
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();
  });

  await test.step("the requirement reflects the change and no longer shows as completed", async () => {
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await openRequirementByName(page, proposedName);
    await expect(page.getByText("Status: Approved")).toBeVisible();
    await expect(page.getByText("Completed", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Mark completed" })).toBeVisible();
  });
});
