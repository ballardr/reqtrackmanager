import { expect, type Page, test } from "@playwright/test";

import { approveRequirementFromDetail, loginAs, openProject, PERSONAS, PROJECT_NAMES, expectCurrentStep, expectRecordLocked, promoteTo } from "./helpers";
import { openAddLinkDialog } from "../modules/linksPanel";

/**
 * Job to be done: once a requirement is approved (locked):
 * 1. Unlinking an action always requires a change request, in every project.
 * 2. Adding or removing a traceability link requires a change request only when the project opts in via
 *    `require_change_request_for_approved_links` (or an organisation-wide force applies).
 *
 * Uses "Epsilon-1 Link Lock Demo" (`PROJECT_NAMES.epsilon1`), seeded solely for this coverage. Every requirement,
 * link and action is created fresh by each test: approving and unlinking are one-way, so a seeded fixture would be
 * consumed after the first run.
 */
/**
 * Signs in, opens the demo project and creates the named throwaway requirements.
 *
 * The requirements are created through the API: creating one is not what these scenarios test, and doing it in the UI
 * spends the time the locked-record steps need. The seeded project is shared and cumulative: its requirement list grows
 * with every run, so a requirement is opened by its address (`openRequirement`) rather than found in the list, and a
 * `tr:has-text("Draft")` match would land on another run's row; `createsChangeRequest` returns each new request's id from
 * its creating response, to be opened directly by URL.
 */
async function setUp(page: Page, requirementNames: string[]) {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await openProject(page, PROJECT_NAMES.epsilon1);
  const projectIdMatch = page.url().match(/\/projects\/([0-9a-f-]{36})/);
  if (!projectIdMatch) throw new Error(`Could not extract project id from URL: ${page.url()}`);
  const projectId = projectIdMatch[1];

  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem("reqtrack_token"))}` };
  const base = `http://localhost:8000/api/v1/projects/${projectId}`;
  const [category] = await (await page.request.get(`${base}/categories`, { headers })).json();
  const requirementIds: Record<string, string> = {};
  for (const name of requirementNames) {
    const created = await page.request.post(`${base}/requirements`, {
      headers, data: { name, component_id: category.component_id, category_id: category.id },
    });
    expect(created.status(), await created.text()).toBe(201);
    requirementIds[name] = ((await created.json()) as { id: string }).id;
  }

  async function openRequirement(name: string): Promise<void> {
    await page.goto(`/projects/${projectId}/requirements/${requirementIds[name]}`);
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  }

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

  return { projectId, createsChangeRequest, openRequirement };
}

/** A name unique even when the file's tests start in the same millisecond on two workers. */
const uniqueSuffix = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

test.describe("action/link change-request locking", () => {
  test("unlinking an action routes through a change request once the requirement is locked", async ({ page }) => {
    const ts = uniqueSuffix();
    const reqAName = `E2E Action Lock Source ${ts}`;
    const actionTitle = `E2E Link Lock Action ${ts}`;
    const { projectId, createsChangeRequest, openRequirement } = await setUp(page, [reqAName]);

    await test.step("link an action to the requirement directly (still draft, ungated), then approve it", async () => {
      await openRequirement(reqAName);

      await page.getByRole("button", { name: "Create and link a new action" }).click();
      const actionPanel = page.getByRole("dialog", { name: "Create and link a new action" });
      await actionPanel.getByLabel("Title").fill(actionTitle);
      await actionPanel.getByLabel("Type", { exact: true }).selectOption({ label: "Review" });
      await actionPanel.getByRole("button", { name: "Create", exact: true }).click();
      await expect(actionPanel).not.toBeVisible();
      await expect(page.getByRole("link", { name: actionTitle })).toBeVisible();

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

      await openRequirement(reqAName);
      await expect(page.getByRole("link", { name: actionTitle })).toHaveCount(0);
    });
  });

  test("removing a link routes through a change request once the requirement is locked", async ({ page }) => {
    const ts = uniqueSuffix();
    const reqAName = `E2E Link Lock Source ${ts}`;
    const reqBName = `E2E Link Lock Target ${ts}`;
    const { projectId, createsChangeRequest, openRequirement } = await setUp(page, [reqAName, reqBName]);

    await test.step("link a requirement to reqA directly (still draft, ungated), then approve it", async () => {
      await openRequirement(reqAName);

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

      await openRequirement(reqAName);
      await expect(page.getByRole("link", { name: reqBName })).toHaveCount(0);
    });
  });

  test("adding a link routes through a change request once the requirement is locked", async ({ page }) => {
    const ts = uniqueSuffix();
    const reqAName = `E2E Link Add Lock Source ${ts}`;
    const reqCName = `E2E Link Add Lock Target ${ts}`;
    const { projectId, createsChangeRequest, openRequirement } = await setUp(page, [reqAName, reqCName]);

    await test.step("approve the requirement, which locks it", async () => {
      await openRequirement(reqAName);
      await approveRequirementFromDetail(page);
      await expect(page.getByText("Requirement approved")).toBeVisible();
      await expectRecordLocked(page);
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

      await openRequirement(reqAName);
      await expect(page.getByRole("link", { name: reqCName })).toBeVisible();
    });
  });
});
