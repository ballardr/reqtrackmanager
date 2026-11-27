import { expect, test } from "@playwright/test";

import { approveRequirementFromDetail, loginAs, openProject, openRequirementByName, PERSONAS, PROJECT_NAMES, expectCurrentStep, expectRecordLocked, promoteTo } from "./helpers";
import { openAddLinkDialog } from "../modules/linksPanel";

/**
 * Job to be done: once a requirement is approved (locked):
 * 1. Unlinking an action always requires a change request, in every project.
 * 2. Adding or removing a traceability link requires a change request only when the project opts in via
 *    `require_change_request_for_approved_links` (or an organisation-wide force applies).
 *
 * Uses "Epsilon-1 Link Lock Demo" (`PROJECT_NAMES.epsilon1`), seeded solely for this coverage. Every requirement,
 * link and action is created fresh by each run: approving and unlinking are one-way, so a seeded fixture would be
 * consumed after the first run.
 */
test.describe("action/link change-request locking", () => {
  test("unlinking an action, and adding/removing a link, all route through a change request once locked", async ({ page }) => {
    const ts = Date.now();
    const reqAName = `E2E Link Lock Source ${ts}`;
    const reqBName = `E2E Link Lock Target 1 ${ts}`;
    const reqCName = `E2E Link Lock Target 2 ${ts}`;
    const actionTitle = `E2E Link Lock Action ${ts}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.epsilon1);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    // The "Change requests" list is shared, cumulative state for the project, so a `tr:has-text("Draft")` match
    // breaks strict mode (or lands on the wrong row) once a second Draft row exists. Each created change request's id
    // is captured from its creating POST response and opened directly by URL, as `openRequirementByCode` does.
    const projectIdMatch = page.url().match(/\/projects\/([0-9a-f-]{36})/);
    if (!projectIdMatch) throw new Error(`Could not extract project id from URL: ${page.url()}`);
    const projectId = projectIdMatch[1];

    async function createsChangeRequest(action: () => Promise<void>): Promise<string> {
      const [response] = await Promise.all([
        page.waitForResponse(
          (resp) => resp.request().method() === "POST" && /\/change-requests$/.test(new URL(resp.url()).pathname)
        ),
        action(),
      ]);
      const body = (await response.json()) as { id: string };
      return body.id;
    }

    // Through the API: creating a requirement is not what this scenario tests, and doing it in the UI spends the time
    // the locked-record steps need.
    await test.step("create three throwaway requirements", async () => {
      const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem("reqtrack_token"))}` };
      const base = `http://localhost:8000/api/v1/projects/${projectId}`;
      const [category] = await (await page.request.get(`${base}/categories`, { headers })).json();
      for (const name of [reqAName, reqBName, reqCName]) {
        const created = await page.request.post(`${base}/requirements`, {
          headers, data: { name, component_id: category.component_id, category_id: category.id },
        });
        expect(created.status(), await created.text()).toBe(201);
      }
    });

    await test.step("link an action and a requirement to reqA directly (still draft, ungated), then approve it", async () => {
      await openRequirementByName(page, reqAName);

      await page.getByRole("button", { name: "Create and link a new action" }).click();
      const actionPanel = page.getByRole("dialog", { name: "Create and link a new action" });
      await actionPanel.getByLabel("Title").fill(actionTitle);
      await actionPanel.getByLabel("Type", { exact: true }).selectOption({ label: "Review" });
      await actionPanel.getByRole("button", { name: "Create", exact: true }).click();
      await expect(actionPanel).not.toBeVisible();
      await expect(page.getByRole("link", { name: actionTitle })).toBeVisible();

      await openAddLinkDialog(page, page.getByRole("region", { name: "Links", exact: true }));
      const linkModal = page.getByRole("dialog", { name: "Add a link" });
      // Still draft — no change-request notice, and Add link works directly.
      await expect(linkModal.getByText(/requires link changes to go through a change request/i)).toHaveCount(0);
      await linkModal.getByLabel("Link to").selectOption({ label: "Requirement" });
      await linkModal.getByLabel("Search").fill(reqBName);
      const targetSelect = linkModal.getByLabel("Record");
      await expect(targetSelect.locator("option", { hasText: reqBName })).toHaveCount(1);
      const targetValue = await targetSelect.locator("option", { hasText: reqBName }).getAttribute("value");
      await targetSelect.selectOption(targetValue!);
      await linkModal.getByLabel("Relationship").selectOption({ label: "Related to" });
      await linkModal.getByRole("button", { name: "Add link" }).click();
      await expect(linkModal).not.toBeVisible();
      await expect(page.getByRole("link", { name: reqBName })).toBeVisible();

      await approveRequirementFromDetail(page);
      await expect(page.getByText("Requirement approved")).toBeVisible();
      await expectRecordLocked(page);
    });

    let unlinkActionCrId = "";
    await test.step("unlinking the action now opens a change-request confirm, not a plain unlink", async () => {
      const actionRow = page.locator(".row", { hasText: actionTitle });
      await actionRow.getByTitle("Unlink").click();
      const dialog = page.getByRole("dialog", { name: "Unlink this action via change request?" });
      await expect(dialog).toBeVisible();
      const confirmButton = dialog.getByRole("button", { name: "Unlink" });
      await expect(confirmButton).toBeDisabled();
      await dialog.getByLabel("Reason for change").fill("Superseded by a new review pass.");
      await expect(confirmButton).toBeEnabled();
      unlinkActionCrId = await createsChangeRequest(() => confirmButton.click());
      await expect(dialog).not.toBeVisible();
      await expect(page.getByText(/Change request( \S+-\d+)? created/)).toBeVisible();
      // Not removed yet — only once the change request is approved.
      await expect(page.getByRole("link", { name: actionTitle })).toBeVisible();
    });

    await test.step("approving that change request actually unlinks the action", async () => {
      await page.goto(`/projects/${projectId}/change-requests/${unlinkActionCrId}`);
      await promoteTo(page, "Submitted");
      await expectCurrentStep(page, "Submitted");
      await promoteTo(page, "Approved");
      await expectCurrentStep(page, "Approved");

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByName(page, reqAName);
      await expect(page.getByRole("link", { name: actionTitle })).toHaveCount(0);
    });

    let removeLinkCrId = "";
    await test.step("removing the link now opens a change-request confirm, not a plain remove", async () => {
      await page.getByRole("region", { name: "Links", exact: true }).getByRole("button", { name: /^Remove link: Related to/ }).click();
      const dialog = page.getByRole("dialog", { name: "Remove this link?" });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText(/needs a change request/i)).toBeVisible();
      const confirmButton = dialog.getByRole("button", { name: "Request removal" });
      await expect(confirmButton).toBeDisabled();
      await dialog.getByLabel("Reason for change").fill("Link was recorded against the wrong requirement.");
      await expect(confirmButton).toBeEnabled();
      removeLinkCrId = await createsChangeRequest(() => confirmButton.click());
      await expect(dialog).not.toBeVisible();
      await expect(page.getByText(/Change request( \S+-\d+)? created/)).toBeVisible();
      // Not removed yet — the link is still there.
      await expect(page.getByRole("link", { name: reqBName })).toBeVisible();
    });

    await test.step("approving that change request actually removes the link", async () => {
      await page.goto(`/projects/${projectId}/change-requests/${removeLinkCrId}`);
      await promoteTo(page, "Submitted");
      await expectCurrentStep(page, "Submitted");
      await promoteTo(page, "Approved");
      await expectCurrentStep(page, "Approved");

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByName(page, reqAName);
      await expect(page.getByRole("link", { name: reqBName })).toHaveCount(0);
    });

    let addLinkCrId = "";
    await test.step("adding a new link now shows the change-request notice, offers only requirements and requires a reason", async () => {
      await openAddLinkDialog(page, page.getByRole("region", { name: "Links", exact: true }));
      const modal = page.getByRole("dialog", { name: "Add a link" });
      await expect(modal.getByText(/requires link changes to go through a change request/i)).toBeVisible();
      await modal.getByLabel("Search").fill(reqCName);
      const targetSelect = modal.getByLabel("Record");
      await expect(targetSelect.locator("option", { hasText: reqCName })).toHaveCount(1);
      const targetValue = await targetSelect.locator("option", { hasText: reqCName }).getAttribute("value");
      await targetSelect.selectOption(targetValue!);
      await modal.getByLabel("Relationship").selectOption({ label: "Depends on" });
      const addButton = modal.getByRole("button", { name: "Propose link" });
      await expect(addButton).toBeDisabled();
      await modal.getByLabel("Reason for change").fill("New dependency found during review.");
      await expect(addButton).toBeEnabled();
      addLinkCrId = await createsChangeRequest(() => addButton.click());
      await expect(modal).not.toBeVisible();
      await expect(page.getByText(/Change request( \S+-\d+)? created/)).toBeVisible();
      // Not added yet — no link to reqC shows up.
      await expect(page.getByRole("link", { name: reqCName })).toHaveCount(0);
    });

    await test.step("approving that change request actually creates the link", async () => {
      await page.goto(`/projects/${projectId}/change-requests/${addLinkCrId}`);
      await promoteTo(page, "Submitted");
      await expectCurrentStep(page, "Submitted");
      await promoteTo(page, "Approved");
      // An add-link request approves through the merge dialog link ticked by default.
      await page.getByRole("dialog", { name: "Approve change request" }).getByRole("button", { name: "Approve and merge 1 link" }).click();
      await expectCurrentStep(page, "Approved");

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByName(page, reqAName);
      await expect(page.getByRole("link", { name: reqCName })).toBeVisible();
    });
  });
});
