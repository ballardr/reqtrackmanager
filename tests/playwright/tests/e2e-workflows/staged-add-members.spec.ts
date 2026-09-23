import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: `AddMembersModal` (frontend/src/components/AddMembersModal.tsx)
 * replaced two near-identical bespoke "pick one person, submit immediately,
 * close the modal" flows (`OrgAdminPage.tsx`'s "Manage users" add-member
 * step, `ProjectAdminPage.tsx`'s own Members-section add-member modal) with
 * a staged multi-add: pick several people/groups, set each one's own role,
 * then commit them all with a single button press instead of one full
 * round trip per person. This spec covers that staged commit end to end
 * against the real backend (`ProjectAdminPage.tsx`'s own instance, which
 * has no batch backend endpoint to call — see the component's own module
 * docstring — so committing fires one `POST` per staged row from one user
 * action), plus the partial-failure path the style guide's "Pattern: bulk
 * operations on a list" requires: one failing row must stay visible with
 * its own error, not silently vanish alongside the rows that succeeded.
 *
 * Persona: OrgAdminAlphaBeta (org admin of Beta, so can manage a fresh
 * throwaway Beta project's membership). Uses a brand-new project and a
 * brand-new org group per test (not a shared seeded fixture) so this can
 * run standalone or repeated without depending on another spec's state.
 */
test.describe("staged multi-add member flow", () => {
  test("staging two entries with different roles and committing once grants both in a single action", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get("http://localhost:8000/api/v1/orgs", { headers: authHeaders })).json();
    const betaOrg = orgs.find((o: { name: string }) => o.name === ORG_NAMES.beta);

    const suffix = Date.now();
    const project = await (
      await page.request.post("http://localhost:8000/api/v1/projects", {
        headers: authHeaders,
        data: { organization_id: betaOrg.id, name: `E2E Staged Add Project ${suffix}`, summary: "" },
      })
    ).json();
    const groupName = `E2E Staged Add Group ${suffix}`;
    const orgGroup = await (
      await page.request.post(`http://localhost:8000/api/v1/orgs/${betaOrg.id}/groups`, {
        headers: authHeaders, data: { name: groupName },
      })
    ).json();

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Members");

    await page.getByRole("button", { name: "Add member" }).click();
    const modal = page.getByRole("dialog", { name: "Add member" });
    const picker = modal.getByPlaceholder("Type a name to add, or an email to invite…");

    await test.step("stage a direct user with a non-default role", async () => {
      await picker.fill(PERSONAS.memberAlphaBeta.name);
      await modal.getByRole("option", { name: new RegExp(PERSONAS.memberAlphaBeta.name) }).click();
      await modal
        .getByRole("combobox", { name: `Role for ${PERSONAS.memberAlphaBeta.name} (${PERSONAS.memberAlphaBeta.email})` })
        .selectOption("stakeholder");
    });

    await test.step("stage an org group with a different role, before committing either", async () => {
      await picker.fill(groupName);
      const groupOption = modal.getByRole("option", { name: new RegExp(`^${groupName}`) });
      await expect(groupOption).toContainText("Org group");
      await groupOption.click();
      await modal.getByRole("combobox", { name: `Role for ${groupName}` }).selectOption("project_administrator");

      // Nothing granted yet — both rows are staged, no network call fired
      // by picking or setting a role.
      await expect(page.getByRole("cell", { name: PERSONAS.memberAlphaBeta.name, exact: true })).toHaveCount(0);
      await expect(page.getByRole("row", { name: new RegExp(groupName) })).toHaveCount(0);
    });

    await test.step("committing once grants both, with their own distinct roles", async () => {
      await modal.getByRole("button", { name: "Add 2 members" }).click();
      await expect(modal).not.toBeVisible();

      await expect(page.getByRole("cell", { name: PERSONAS.memberAlphaBeta.name, exact: true })).toBeVisible();
      const memberRolesButton = page.getByRole("button", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
      await memberRolesButton.click();
      await expect(
        page
          .getByRole("group", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` })
          .getByRole("checkbox", { name: new RegExp(`Revoke Stakeholder from ${PERSONAS.memberAlphaBeta.name}`) })
      ).toBeChecked();
      await page.keyboard.press("Escape");

      const groupRow = page.getByRole("row", { name: new RegExp(groupName) });
      await expect(groupRow).toBeVisible();
      await expect(groupRow).toContainText("Project administrator");
    });
  });

  test("a row that fails to commit stays staged with its own error, while the row that succeeded is gone", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get("http://localhost:8000/api/v1/orgs", { headers: authHeaders })).json();
    const betaOrg = orgs.find((o: { name: string }) => o.name === ORG_NAMES.beta);

    const suffix = Date.now();
    const project = await (
      await page.request.post("http://localhost:8000/api/v1/projects", {
        headers: authHeaders,
        data: { organization_id: betaOrg.id, name: `E2E Staged Add Failure Project ${suffix}`, summary: "" },
      })
    ).json();
    const groupName = `E2E Staged Add Failure Group ${suffix}`;
    await page.request.post(`http://localhost:8000/api/v1/orgs/${betaOrg.id}/groups`, {
      headers: authHeaders, data: { name: groupName },
    });

    // Simulated failure, not a naturally-occurring backend rejection: the
    // direct-role grant endpoint (`POST /{project_id}/roles`) has no
    // real-world input that both passes `UserAutocomplete` and is
    // rejected server-side, so this intercepts that one request and fails
    // it, while every other request (including the group's own
    // `POST /group-roles`, a distinct path) continues untouched — proving
    // the frontend's own partial-failure handling, not a specific backend
    // validation rule.
    await page.route(`**/api/v1/projects/${project.id}/roles`, async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Simulated failure for e2e partial-failure coverage." }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Members");

    await page.getByRole("button", { name: "Add member" }).click();
    const modal = page.getByRole("dialog", { name: "Add member" });
    const picker = modal.getByPlaceholder("Type a name to add, or an email to invite…");

    await picker.fill(PERSONAS.memberAlphaBeta.name);
    await modal.getByRole("option", { name: new RegExp(PERSONAS.memberAlphaBeta.name) }).click();
    await picker.fill(groupName);
    await modal.getByRole("option", { name: new RegExp(`^${groupName}`) }).click();

    await modal.getByRole("button", { name: "Add 2 members" }).click();

    await test.step("the failed row's own error shows inline and the modal stays open", async () => {
      await expect(modal.getByText("Simulated failure for e2e partial-failure coverage.")).toBeVisible();
      await expect(modal).toBeVisible();
      // The failing row (the direct user) is still staged; the succeeding
      // row (the group) is gone from the staged list.
      await expect(
        modal.getByText(`${PERSONAS.memberAlphaBeta.name} (${PERSONAS.memberAlphaBeta.email})`)
      ).toBeVisible();
      await expect(modal.getByText(groupName)).toHaveCount(0);
    });

    await test.step("the group's grant went through despite the other row failing", async () => {
      await modal.getByRole("button", { name: "Cancel" }).click();
      const groupRow = page.getByRole("row", { name: new RegExp(groupName) });
      await expect(groupRow).toBeVisible();
      // The failed row never reached the backend — no cell for it at all.
      await expect(page.getByRole("cell", { name: PERSONAS.memberAlphaBeta.name, exact: true })).toHaveCount(0);
    });
  });
});
