import { expect, test } from "@playwright/test";

import { loginAs, logout, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: a stakeholder who spots a problem with an approved
 * (locked) requirement can propose a fix, but cannot approve their own
 * proposal — approval is a separate, project-manager-only action performed
 * by someone else. This is the core separation-of-duties guarantee behind
 * the whole change-request workflow (C-G-12).
 *
 * Personas: StakeholderAlphaOnly (submits, cannot approve) and
 * OrgAdminAlphaBeta (the project's PM by virtue of having created it —
 * approves).
 */
test("change request submitter cannot approve their own request; the project manager does", async ({ page }) => {
  const proposedName = `Respond within 30ms (E2E ${Date.now()})`;
  let crStatusAfterSubmit = "";

  await test.step("stakeholder submits a change request against the locked requirement", async () => {
    await loginAs(page, PERSONAS.stakeholderAlpha.email);
    await page.getByText(PROJECT_NAMES.alpha1).click();
    await page.getByRole("link", { name: "Change requests", exact: true }).click();
    await page.getByRole("button", { name: "New change request" }).click();
    // The create form is a `Modal` portalled to the end of `document.body`
    // — scope to it rather than an unscoped `getByRole("combobox").first()`,
    // which would otherwise resolve to the filter sidebar's own Status
    // select (it precedes the dialog in DOM order once the form is a
    // portal instead of an inline block).
    const dialog = page.getByRole("dialog", { name: "New change request" });
    // "Modify requirement" is the default radio and the requirement select
    // defaults to the first requirement in the project (the seed script
    // guarantees that's the locked one, HW-FN-001) once the async project
    // data finishes loading — wait for that before filling the rest, or a
    // fast click can submit with an empty requirement_id.
    await expect(dialog.getByRole("combobox").first()).toContainText("HW-FN-001");
    // Modify-requirement CRs are field-toggle driven: a field's proposed
    // value is only editable (and only becomes part of `changed_fields`)
    // once its "Fields to change" checkbox is ticked. Each checkbox and its
    // (once checked) inline editor live in the same field-row container
    // (checkbox -> label -> field-row div), so scope the fill to that row
    // rather than a page-wide input query.
    const nameCheckbox = page.getByRole("checkbox", { name: "Name", exact: true });
    await nameCheckbox.check();
    await nameCheckbox.locator("xpath=../..").locator("input.input").fill(proposedName);
    const reasoningCheckbox = page.getByRole("checkbox", { name: "Reasoning", exact: true });
    await reasoningCheckbox.check();
    await reasoningCheckbox.locator("xpath=../..").locator("textarea.input").fill("Tighter latency target after field testing.");
    await page.getByPlaceholder("Reason for change").fill("Customer escalation on response time.");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText(proposedName)).toBeVisible();
  });

  await test.step("stakeholder submits it for review and sees no approve/reject controls", async () => {
    await page.getByText(proposedName).click();
    await page.getByRole("button", { name: "Submit" }).click();
    await expect(page.getByText("Submitted", { exact: true })).toBeVisible();
    // Exact match: a stakeholder can cast an advisory "Vote to approve" /
    // "Vote to reject" (C-R-03, doesn't touch the CR's real status), which
    // would otherwise substring-match a loose "Approve"/"Reject" query —
    // the actual decision controls this asserts are absent are the exact-
    // labelled "Approve"/"Reject" buttons gated to project managers.
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
    await page.getByText(PROJECT_NAMES.alpha1).click();
    await page.getByRole("link", { name: "Change requests", exact: true }).click();
    await page.getByText(proposedName).click();
    // React Router 7 wraps navigation in React's startTransition by
    // default (a behavior change from 6): the URL updates immediately,
    // but the previous page's own content can stay mounted for a beat
    // longer. Right after this click, that's the change requests *list*
    // — whose filter sidebar has a "Submitted" status option in its
    // (closed) Status <select> — coexisting with this CR's own detail
    // view, which is ambiguous for `crStatusAfterSubmit`'s exact text
    // match. Waiting for this CR's own heading first (unambiguous: the
    // list has no such heading) proves the transition has actually
    // landed before checking the — otherwise possibly-transient —
    // status text.
    await expect(page.getByRole("heading", { name: proposedName, level: 1 })).toBeVisible();
    await expect(page.getByText(crStatusAfterSubmit, { exact: true })).toBeVisible();
    await page.getByPlaceholder("Decision note").fill("Approved — matches the new latency budget.");
    // Exact match: the PM also sees the advisory "Vote to approve" button
    // (project managers inherit stakeholder voting rights), which a loose
    // "Approve" query would ambiguously match alongside the real decision button.
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();
  });

  await test.step("the requirement now reflects the approved change", async () => {
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    // Role-scoped, not a page-wide getByText: same React Router 7
    // startTransition timing as above — the just-left change request
    // detail view's own "Name: {proposedName}" changed-field summary can
    // transiently coexist with the requirements list underneath as it
    // settles in. The requirement card's link has no such ambiguity (see
    // the identical fix in golden-path.spec.ts).
    await expect(page.getByRole("link", { name: proposedName })).toBeVisible();
  });
});
