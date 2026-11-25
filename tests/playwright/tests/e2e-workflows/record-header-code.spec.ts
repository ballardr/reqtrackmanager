import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

// Archives this file's disposable projects after each test (see createDisposableProject).
installCleanupHook();

/**
 * Job to be done: find a record's code however long its title is.
 *
 * Covers: on an Action with a long title, the record code follows the title's last word (or starts the next line)
 * and never sits beside the first line next to the action controls, at a wide and at a narrow window.
 */
const API = "http://localhost:8000/api/v1";

test.describe("record header code", () => {
  for (const viewport of [{ width: 1280, height: 800 }, { width: 420, height: 800 }]) {
    test(`the code follows a long title at ${viewport.width}px`, async ({ page }) => {
      const { projectId, headers } = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Header Code");
      const actionTypes: { id: string }[] = await (await page.request.get(`${API}/projects/${projectId}/action-types`, { headers })).json();
      const title = `E2E ${"An exceptionally long action title ".repeat(6)}${Date.now()}`;
      const action = await (
        await page.request.post(`${API}/projects/${projectId}/actions`, { headers, data: { title, action_type_id: actionTypes[0].id } })
      ).json();
      await page.setViewportSize(viewport);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.goto(`/projects/${projectId}/actions/${action.id}`);

      const header = page.locator(".record-header");
      await expect(header.locator(".record-header__code")).toBeVisible();
      const placement = await header.evaluate((el) => {
        const heading = el.querySelector(".record-header__heading")!;
        const range = document.createRange();
        range.selectNodeContents(heading);
        const lines = Array.from(range.getClientRects());
        const last = lines[lines.length - 1];
        const code = el.querySelector(".record-header__code")!.getBoundingClientRect();
        const actions = el.querySelector(".item-row__actions")!.getBoundingClientRect();
        return {
          lines: lines.length,
          afterLastWord: code.top < last.bottom && code.bottom > last.top && code.left >= last.right - 1,
          onTheNextLine: code.top >= last.bottom - 1,
          clearOfActions: code.right <= actions.left + 1,
        };
      });
      expect(placement.lines).toBeGreaterThan(1);
      expect(placement.afterLastWord || placement.onTheNextLine).toBe(true);
      expect(placement.clearOfActions).toBe(true);
    });
  }
});
