import { expect, test } from "@playwright/test";

import { expectReasonTooltip, loginAs, logout, ORG_NAMES, PERSONAS, chooseRecordAction } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

const apiBaseUrl = "http://localhost:8000";

/**
 * Job to be done: a standard's own "Members" section (`standards_manager`/`standards_contributor`, scoped to
 * this standard). Covers: the creator's direct `standards_manager` role; the last manager's checkbox disabled
 * (with an explanatory title) when no fallback compliance-managers group is configured; adding another org
 * member as `standards_contributor` through the "Add member" picker (`UserAutocomplete`; the second test covers
 * group matching) and revoking it, a contributor's checkbox never being disabled.
 *
 * `orgAdminAlphaBeta` creates the standard (compliance_manager through the ORG_ADMIN override, as in
 * `compliance-standards-management.spec.ts`); `memberAlphaBeta` (a plain Alpha member, seed_e2e_dataset.py) is
 * the contributor. The standard has a per-run timestamp suffix.
 */
test.describe("Compliance Module: standard-scoped RBAC — Members section", () => {
  test("standard creation auto-grants the creator, the last manager checkbox is disabled, and a contributor can be added and revoked", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-RBAC-${suffix}`;
    const standardName = `E2E RBAC Standard ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName });

    await page.getByRole("link", { name: "Members" }).click();
    await expect(page).toHaveURL(/\/standards\/[0-9a-f-]+\/members$/);

    // The creator is auto-granted `standards_manager`.
    await expect(page.getByRole("cell", { name: PERSONAS.orgAdminAlphaBeta.name, exact: true })).toBeVisible();
    await page.getByRole("button", { name: `Roles for ${PERSONAS.orgAdminAlphaBeta.name}` }).click();
    const creatorGroup = page.getByRole("group", { name: `Roles for ${PERSONAS.orgAdminAlphaBeta.name}` });
    const managerCheckbox = creatorGroup.getByRole("checkbox", {
      name: `Revoke Standards Manager from ${PERSONAS.orgAdminAlphaBeta.name}`,
    });
    await expect(managerCheckbox).toBeChecked();
    // Last remaining manager, no fallback group configured for this org ->
    // disabled, with an explanatory title (§3's manager floor).
    await expect(managerCheckbox).toBeDisabled();
    await expectReasonTooltip(page, managerCheckbox, /must always have at least one/);
    await page.keyboard.press("Escape");

    // Add `memberAlphaBeta` as a Standards Contributor, via the
    // `UserAutocomplete` search-as-you-type add flow (rebuilt from a plain,
    // unfiltered `<select>`).
    await page.getByRole("button", { name: "Add member" }).click();
    const addDialog = page.getByRole("dialog", { name: "Add a member" });
    await addDialog.getByLabel("Role").selectOption({ label: "Standards Contributor" });
    await addDialog.getByPlaceholder("Search people or groups…").fill(PERSONAS.memberAlphaBeta.name);
    await addDialog.getByRole("option", { name: new RegExp(PERSONAS.memberAlphaBeta.name) }).click();

    await expect(page.getByText(PERSONAS.memberAlphaBeta.name)).toBeVisible();
    await page.getByRole("button", { name: `Roles for ${PERSONAS.memberAlphaBeta.name}` }).click();
    const memberGroup = page.getByRole("group", { name: `Roles for ${PERSONAS.memberAlphaBeta.name}` });
    const contributorCheckbox = memberGroup.getByRole("checkbox", {
      name: `Revoke Standards Contributor from ${PERSONAS.memberAlphaBeta.name}`,
    });
    await expect(contributorCheckbox).toBeChecked();
    // A contributor grant never touches the manager floor -> always freely revocable.
    await expect(contributorCheckbox).toBeEnabled();

    // Revoking removes the whole row (no roles left on this standard), so a plain `.click()` is used: `.uncheck()`
    // re-verifies the checkbox after clicking, which never resolves once the row is gone.
    await contributorCheckbox.click();
    await expect(page.getByText(PERSONAS.memberAlphaBeta.name)).toHaveCount(0);
  });

  /**
   * Job to be done: group-based grants for module-contributed roles (`GroupModuleRole`) through Compliance's
   * Standards Manager/Contributor picker: granting `standards_manager` to a dynamically created org group
   * (the `UserAutocomplete` add flow's group-matching half) lets a member of that group (`memberAlphaBeta`,
   * added to the group through the API) perform a manager-gated action (archiving the standard) with no
   * direct grant.
   */
  test("granting standards_manager to an org group lets its member perform a manager-gated action", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-GROUP-RBAC-${suffix}`;
    const standardName = `E2E Group RBAC Standard ${suffix}`;
    const groupName = `E2E Group RBAC Group ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName });

    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${token}` };
    const orgs = await (await page.request.get(`${apiBaseUrl}/api/v1/orgs?mine=true`, { headers: authHeaders })).json();
    const alphaOrgId = orgs.find((o: { name: string; id: string }) => o.name === ORG_NAMES.alpha).id;
    const group = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/groups`, {
        headers: authHeaders, data: { name: groupName },
      })
    ).json();
    const orgUsers = await (await page.request.get(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/users`, { headers: authHeaders })).json();
    const memberUser = orgUsers.find((u: { email: string }) => u.email === PERSONAS.memberAlphaBeta.email);
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/groups/${group.id}/members`, {
      headers: authHeaders, data: { user_id: memberUser.user_id },
    });

    // Grant the group standards_manager via the "Add member" control's group-matching half. A reload is
    // needed first: the page's `orgGroups` fetch ran before the group was created through the API.
    await page.getByRole("link", { name: "Members" }).click();
    await page.reload();
    await page.getByRole("button", { name: "Add member" }).click();
    const addDialog = page.getByRole("dialog", { name: "Add a member" });
    await addDialog.getByLabel("Role").selectOption({ label: "Standards Manager" });
    await addDialog.getByPlaceholder("Search people or groups…").fill(groupName);
    await addDialog.getByRole("option", { name: new RegExp(groupName) }).click();

    // The roster shows it as its own, visually-distinguished row.
    const groupRow = page.getByRole("row", { name: new RegExp(groupName) });
    await expect(groupRow).toBeVisible();
    await expect(groupRow.getByText("Organisation group")).toBeVisible();

    const standards = await (
      await page.request.get(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/modules/compliance/standards?include_archived=false`, {
        headers: authHeaders,
      })
    ).json();
    const standardId = standards.find((s: { reference: string }) => s.reference === reference).id;

    // `memberAlphaBeta` holds no direct grant of their own — access comes
    // entirely from group membership.
    await logout(page);
    await loginAs(page, PERSONAS.memberAlphaBeta.email);
    await page.goto(`/standards/${standardId}`);
    await expect(page.getByRole("heading", { name: new RegExp(`${reference} — ${standardName}`) })).toBeVisible();
    await chooseRecordAction(page, "Standard", "Archive");
    await page.getByRole("dialog").getByRole("button", { name: "Archive" }).click();
    await expect(page.getByText("Archived", { exact: true })).toBeVisible();
  });
});
