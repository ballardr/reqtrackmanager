import { expect, test } from "@playwright/test";

import { loginAs, logout, openRequirementByCode, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: comments can be edited and have files attached/removed,
 * but only by their own author — not even a project manager may edit
 * someone else's words. Comment attachments are the one place a file can
 * still be attached to a locked (approved) requirement, since a
 * discussion thread isn't C-G-12-governed content.
 */
test.describe("comment editing and attachments", () => {
  test("author-only edit/attach/remove; comment attachments bypass the locked-requirement gate", async ({ page }) => {
    const marker = Date.now();
    const originalBody = `E2E: original comment body (${marker}).`;
    const editedBody = `E2E: edited comment body (${marker}).`;

    await test.step("a stakeholder posts a comment with an attachment on the locked requirement", async () => {
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-001");
      await expect(page.getByText("Locked (approved)")).toBeVisible();
      // Direct attachment is blocked on a locked requirement — the
      // Attachments section shows a locked notice instead of an upload
      // control (a file input still exists elsewhere on the page, for
      // comment attachments, which remain allowed regardless of lock state).
      await expect(
        page.getByText("This requirement is approved — new attachments must be added via a change request.")
      ).toBeVisible();

      await page.getByPlaceholder("Add comment").fill(originalBody);
      const composeFileInput = page.locator('label[title="Attach a file"] input[type="file"]').last();
      await composeFileInput.setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("first attachment") });
      await page.getByRole("button", { name: "Add comment", exact: true }).click();
      await expect(page.getByText(originalBody)).toBeVisible();
      await expect(page.locator(".card", { hasText: originalBody }).last().getByText("notes.txt")).toBeVisible();
    });

    await test.step("a different user has no Edit control on someone else's comment, and the API rejects it too", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha2.email);
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-001");
      const commentCard = page.locator(".card", { hasText: originalBody }).last();
      await expect(commentCard.getByRole("button", { name: "Edit" })).toHaveCount(0);

      const projectId = page.url().match(/projects\/([0-9a-f-]+)/)![1];
      const requirementId = page.url().match(/requirements\/([0-9a-f-]+)/)![1];
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const commentsResp = await page.request.get(
        `http://localhost:8000/api/v1/projects/${projectId}/requirements/${requirementId}/comments`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      const comments: { id: string; body: string }[] = await commentsResp.json();
      const target = comments.find((c) => c.body === originalBody)!;
      const resp = await page.request.patch(
        `http://localhost:8000/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${target.id}`,
        { headers: { Authorization: `Bearer ${token}` }, data: { body: "hijacked" } }
      );
      expect(resp.status()).toBe(403);
    });

    await test.step("the author edits their own comment: new body, an added attachment, and one removed", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-001");

      await page.locator(".card", { hasText: originalBody }).last().getByRole("button", { name: "Edit" }).click();
      // Once in edit mode, the original body text no longer appears as DOM
      // text content (replaced by a textarea, whose value isn't matched by
      // hasText) — re-locate the card as "the one currently being edited"
      // rather than continuing to filter by the now-stale original text.
      const editingCard = page.locator(".card", { has: page.locator("textarea") }).last();
      await editingCard.locator("textarea").fill(editedBody);
      await editingCard.locator('input[type="file"]').setInputFiles({
        name: "second.txt", mimeType: "text/plain", buffer: Buffer.from("second attachment"),
      });
      await editingCard.getByRole("button", { name: "Save", exact: true }).click();

      await expect(page.getByText(editedBody)).toBeVisible();
      const editedCard = page.locator(".card", { hasText: editedBody }).last();
      await expect(editedCard.getByText("(edited)")).toBeVisible();
      await expect(editedCard.getByText("second.txt")).toBeVisible();
    });

    await test.step("remove one of the two attachments", async () => {
      await page.locator(".card", { hasText: editedBody }).last().getByRole("button", { name: "Edit" }).click();
      const editingCard = page.locator(".card", { has: page.locator("textarea") }).last();
      await editingCard.getByRole("button", { name: "Remove attachment" }).first().click();
      await editingCard.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.locator(".card", { hasText: editedBody }).last().getByText(/\.txt$/)).toHaveCount(1);
    });
  });
});
