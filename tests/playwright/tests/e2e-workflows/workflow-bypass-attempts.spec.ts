import { expect, test } from "@playwright/test";

import { loginAs, logout, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: the requirement lifecycle's guarantees (edit-after-lock
 * requires a change request; only a PM can approve; archiving isn't a way
 * to quietly redefine an identifier) must hold even against a user
 * deliberately trying to route around them — not just against a well-
 * behaved UI. Each step below is an attempted bypass, followed by
 * confirmation it was actually blocked (both in the UI and, where it
 * matters, at the API directly).
 */
test.describe("attempts to bypass requirement/change-request workflow guarantees", () => {
  test("locking a stage, then probing edit/archive/approve boundaries", async ({ page }) => {
    await test.step("PM approves Alpha-1's stage, locking all its requirements", async () => {
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("button", { name: "Project stages" }).click();
      const approveButton = page.getByRole("button", { name: "Approve stage" });
      if (await approveButton.count()) {
        await approveButton.click();
      }
      await expect(page.getByRole("button", { name: "Approve stage" })).toHaveCount(0);
    });

    let lockedRequirementUrl = "";
    await test.step("a locked requirement offers no edit form in the UI", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("link", { name: "Must support configuration via file" }).click();
      lockedRequirementUrl = page.url();
      await expect(page.getByText("Locked (approved)")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
    });

    await test.step("a raw API edit attempt against the same locked requirement still 409s", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const match = lockedRequirementUrl.match(/projects\/([0-9a-f-]+)\/requirements\/([0-9a-f-]+)/);
      const [, projectId, requirementId] = match!;
      const resp = await page.request.put(
        `http://localhost:8000/api/v1/projects/${projectId}/requirements/${requirementId}`,
        {
          headers: { Authorization: `Bearer ${token}` },
          data: {
            name: "Renamed via raw API bypass attempt", reasoning: "x", component_id: "00000000-0000-0000-0000-000000000000",
            category_id: "00000000-0000-0000-0000-000000000000", owner_id: "00000000-0000-0000-0000-000000000000", keywords: [],
          },
        }
      );
      expect(resp.status()).toBe(409);
    });

    await test.step("archiving a locked requirement is hidden from a non-PM stakeholder", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("link", { name: "Must log all state transitions", exact: true }).click();
      await expect(page.getByRole("button", { name: "Archive" })).toHaveCount(0);
    });

    let archivedCode = "";
    let newCode = "";
    const newReqName = `Must log all state transitions (E2E recreated ${Date.now()})`;
    await test.step("PM archives it, then a same-named recreation gets a distinct identity — no way to 'become' the old one", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("link", { name: "Must log all state transitions", exact: true }).click();
      archivedCode = (await page.locator("h1").textContent())!.split(" — ")[0].trim();
      await page.getByRole("button", { name: "Archive" }).click();
      await page.waitForURL(/\/requirements$/);
      await expect(page.getByText("Must log all state transitions", { exact: true })).toHaveCount(0);

      await page.getByRole("button", { name: "New Requirement" }).click();
      // Component/category selects default asynchronously once project data
      // loads — wait so Create doesn't submit with an empty component_id.
      await expect(page.getByRole("combobox").first()).toContainText("Hardware");
      await page.getByPlaceholder("Name", { exact: true }).fill(newReqName);
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByText(newReqName)).toBeVisible();
      await page.getByText(newReqName).click();
      newCode = (await page.locator("h1").textContent())!.split(" — ")[0].trim();

      expect(newCode).not.toBe(archivedCode);
    });

    await test.step("a project member with no PM role cannot decide a change request via a direct API call either", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      // fetch an existing submitted/in-review CR to target, or fall back to
      // any CR on the project — the point is the role check, not the status.
      const projectUrl = page.url().match(/projects\/([0-9a-f-]+)/)![1];
      const crsResp = await page.request.get(`http://localhost:8000/api/v1/projects/${projectUrl}/change-requests`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const crs = await crsResp.json();
      if (crs.length > 0) {
        await logout(page);
        await loginAs(page, PERSONAS.memberAlphaBeta.email);
        const memberToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
        const resp = await page.request.post(
          `http://localhost:8000/api/v1/projects/${projectUrl}/change-requests/${crs[0].id}/decide`,
          { headers: { Authorization: `Bearer ${memberToken}` }, data: { approve: true, note: "unauthorized attempt" } }
        );
        expect(resp.status()).toBe(403);
      }
    });

    await test.step("cross-org ID guessing: a single-org user cannot open another org's project by URL", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      const pmToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const projectsResp = await page.request.get("http://localhost:8000/api/v1/projects?archived=false", {
        headers: { Authorization: `Bearer ${pmToken}` },
      });
      const projects = await projectsResp.json();
      const beta1 = projects.find((p: { name: string }) => p.name === PROJECT_NAMES.beta1);

      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      const stakeholderToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const resp = await page.request.get(`http://localhost:8000/api/v1/projects/${beta1.id}`, {
        headers: { Authorization: `Bearer ${stakeholderToken}` },
      });
      expect(resp.status()).toBe(403);

      // Also confirm the UI itself doesn't render Beta-1's content if
      // navigated to directly by URL, not just that the API rejects it.
      await page.goto(`/projects/${beta1.id}`);
      await expect(page.getByText(PROJECT_NAMES.beta1)).toHaveCount(0);
    });
  });
});
