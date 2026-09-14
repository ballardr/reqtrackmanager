import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: Platform review 2026-09, Phase 8. Once a requirement is
 * approved (locked):
 *
 * 1. Unlinking an action always requires a change request instead of the
 *    direct endpoint — unconditional, every project (closes an asymmetry
 *    `unlink_action` had with the already-gated add side, item 514).
 * 2. Adding/removing a traceability link *also* requires a change request,
 *    but only once a project opts in via `require_change_request_for_
 *    approved_links` (or an org-wide force applies) — links otherwise stay
 *    ungated, unlike actions.
 *
 * Uses "Epsilon-1 Link Lock Demo" (`PROJECT_NAMES.epsilon1`), a project
 * `backend/scripts/seed_e2e_dataset.py` seeds dedicated solely to this
 * coverage (`require_change_request_for_approved_links` is on; no other
 * spec may depend on that) — but, per the same fix `requirement-actions
 * .spec.ts` already applied to its own originally-fixed fixture, every
 * requirement/link/action this spec touches is created fresh by this run
 * rather than a pre-seeded one: approving a requirement and unlinking/
 * removing are one-way, so a fixed seeded fixture would be fully consumed
 * after the first run and break every repeat run against the same database.
 */
test.describe("action/link change-request locking (platform review 2026-09, Phase 8)", () => {
  test("unlinking an action, and adding/removing a link, all route through a change request once locked", async ({ page }) => {
    const ts = Date.now();
    const reqAName = `E2E Link Lock Source ${ts}`;
    const reqBName = `E2E Link Lock Target 1 ${ts}`;
    const reqCName = `E2E Link Lock Target 2 ${ts}`;
    const actionTitle = `E2E Link Lock Action ${ts}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.epsilon1).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    // The "Change requests" list (below) is shared, cumulative state for
    // this whole project — every change request any run of this spec has
    // ever created (plus, historically, any left mid-flight by a run that
    // failed partway) stays in it. Rather than find "the" change request
    // this step just created by matching status text against that shared
    // list — `tr:has-text("Draft")`, tried first, strict-mode-violates the
    // moment a second Draft row exists for any reason, and has also been
    // observed to land on the wrong row without erroring at all — capture
    // each created change request's own id straight from its creating
    // POST response (below) and navigate to it directly by URL. This is
    // the same fix `openRequirementByCode` in helpers.ts already needed for
    // an identical shared-list strict-mode violation.
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

    await test.step("create three throwaway requirements", async () => {
      for (const name of [reqAName, reqBName, reqCName]) {
        await page.getByRole("button", { name: "New Requirement" }).click();
        const createPanel = page.getByRole("dialog", { name: "New Requirement" });
        await createPanel.getByPlaceholder("Name", { exact: true }).fill(name);
        await createPanel.getByRole("button", { name: "Create", exact: true }).click();
        await expect(createPanel).not.toBeVisible();
      }
    });

    await test.step("link an action and a requirement to reqA directly (still draft, ungated), then approve it", async () => {
      await page.getByText(reqAName).click();

      await page.getByRole("button", { name: "Create and link a new action" }).click();
      const actionPanel = page.getByRole("dialog", { name: "Create and link a new action" });
      await actionPanel.getByPlaceholder("Title").fill(actionTitle);
      await actionPanel.getByLabel("Type", { exact: true }).selectOption({ label: "Review" });
      await actionPanel.getByRole("button", { name: "Create", exact: true }).click();
      await expect(actionPanel).not.toBeVisible();
      await expect(page.getByRole("link", { name: actionTitle })).toBeVisible();

      await page.getByRole("button", { name: "Add link" }).click();
      const linkModal = page.getByRole("dialog", { name: "Add link" });
      // Still draft — no change-request notice, and Add link works directly.
      await expect(linkModal.getByText(/requires a change request/i)).toHaveCount(0);
      await linkModal.getByPlaceholder("Search by code or name…").fill(reqBName);
      const targetSelect = linkModal.getByLabel("Target requirement");
      const targetValue = await targetSelect.locator("option", { hasText: reqBName }).getAttribute("value");
      await targetSelect.selectOption(targetValue!);
      await linkModal.getByLabel("Link type").selectOption({ label: "Related to" });
      await linkModal.getByRole("button", { name: "Add link" }).click();
      await expect(linkModal).not.toBeVisible();
      await expect(page.getByRole("link", { name: reqBName })).toBeVisible();

      await page.getByRole("button", { name: "Approve", exact: true }).click();
      await expect(page.getByText("Requirement approved")).toBeVisible();
      await expect(page.getByText("Locked (approved)")).toBeVisible();
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
      await expect(page.getByText("Change request created")).toBeVisible();
      // Not removed yet — only once the change request is approved.
      await expect(page.getByRole("link", { name: actionTitle })).toBeVisible();
    });

    await test.step("approving that change request actually unlinks the action", async () => {
      await page.goto(`/projects/${projectId}/change-requests/${unlinkActionCrId}`);
      await page.getByRole("button", { name: "Submit" }).click();
      await expect(page.getByText("Submitted", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Approve", exact: true }).click();
      await expect(page.getByText("Approved", { exact: true })).toBeVisible();

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByText(reqAName).click();
      await expect(page.getByRole("link", { name: actionTitle })).toHaveCount(0);
    });

    let removeLinkCrId = "";
    await test.step("removing the link now opens a change-request confirm, not a plain remove", async () => {
      const linkRow = page.locator(".row", { hasText: "Related to" });
      await linkRow.getByRole("button", { name: "Remove link" }).click();
      const dialog = page.getByRole("dialog", { name: "Remove this link via change request?" });
      await expect(dialog).toBeVisible();
      const confirmButton = dialog.getByRole("button", { name: "Remove link" });
      await expect(confirmButton).toBeDisabled();
      await dialog.getByLabel("Reason for change").fill("Link was recorded against the wrong requirement.");
      await expect(confirmButton).toBeEnabled();
      removeLinkCrId = await createsChangeRequest(() => confirmButton.click());
      await expect(dialog).not.toBeVisible();
      await expect(page.getByText("Change request created")).toBeVisible();
      // Not removed yet — the link is still there.
      await expect(page.getByRole("link", { name: reqBName })).toBeVisible();
    });

    await test.step("approving that change request actually removes the link", async () => {
      await page.goto(`/projects/${projectId}/change-requests/${removeLinkCrId}`);
      await page.getByRole("button", { name: "Submit" }).click();
      await expect(page.getByText("Submitted", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Approve", exact: true }).click();
      await expect(page.getByText("Approved", { exact: true })).toBeVisible();

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByText(reqAName).click();
      await expect(page.getByRole("link", { name: reqBName })).toHaveCount(0);
    });

    let addLinkCrId = "";
    await test.step("adding a new link now opens the picker's change-request notice and requires a reason", async () => {
      await page.getByRole("button", { name: "Add link" }).click();
      const modal = page.getByRole("dialog", { name: "Add link" });
      await expect(modal.getByText(/requires a change request/i)).toBeVisible();
      await modal.getByPlaceholder("Search by code or name…").fill(reqCName);
      const targetSelect = modal.getByLabel("Target requirement");
      const targetValue = await targetSelect.locator("option", { hasText: reqCName }).getAttribute("value");
      await targetSelect.selectOption(targetValue!);
      await modal.getByLabel("Link type").selectOption({ label: "Depends on" });
      const addButton = modal.getByRole("button", { name: "Add link" });
      await expect(addButton).toBeDisabled();
      await modal.getByLabel("Reason for change").fill("New dependency found during review.");
      await expect(addButton).toBeEnabled();
      addLinkCrId = await createsChangeRequest(() => addButton.click());
      await expect(modal).not.toBeVisible();
      await expect(page.getByText("Change request created")).toBeVisible();
      // Not added yet — no link to reqC shows up.
      await expect(page.getByRole("link", { name: reqCName })).toHaveCount(0);
    });

    await test.step("approving that change request actually creates the link", async () => {
      await page.goto(`/projects/${projectId}/change-requests/${addLinkCrId}`);
      await page.getByRole("button", { name: "Submit" }).click();
      await expect(page.getByText("Submitted", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Approve", exact: true }).click();
      await expect(page.getByText("Approved", { exact: true })).toBeVisible();

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByText(reqAName).click();
      await expect(page.getByRole("link", { name: reqCName })).toBeVisible();
    });
  });
});
