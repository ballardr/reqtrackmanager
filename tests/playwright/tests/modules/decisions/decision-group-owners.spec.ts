import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, openOrgGroupPanel } from "../../e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: users and groups on parity, Phase 2 (docs/plans/
 * users-and-groups-parity-plan.md; Module 4 Phase 10) — a Decision's owner and
 * decision maker can be an organisation group or a project group, a member of
 * the owner group passes the "owner may propose" gate, and deleting a group
 * that still owns Decisions walks the admin through handing them to someone
 * else (the first real adopter of the shared in-use group delete flow).
 *
 * Uses a disposable org with an admin, a plain project member in an org group
 * "Review Board", a project group "Delivery Squad", and Decision Management
 * switched on, all set up through the API.
 */
test.describe("Decision Management: groups as owners and decision makers", () => {
  test("a group owns a Decision, its member can propose it, and deleting the group reassigns it", async ({ page, browser }) => {
    const suffix = Date.now();
    const adminEmail = `e2e-dgo-admin-${suffix}@example.com`;
    const memberEmail = `e2e-dgo-member-${suffix}@example.com`;
    const groupName = `Review Board ${suffix}`;
    const squadName = `Delivery Squad ${suffix}`;

    // --- Disposable org, admin, member, groups and project via the API.
    const serverToken = (
      await (await page.request.post(`${API}/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
    ).access_token;
    const serverHeaders = { Authorization: `Bearer ${serverToken}` };
    const org = await (await page.request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Decision Groups Org ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Group Admin", password: PASSWORD, role: "org_admin" },
    });
    const member = await (
      await page.request.post(`${API}/orgs/${org.id}/users`, {
        headers: serverHeaders, data: { email: memberEmail, display_name: "E2E Group Member", password: PASSWORD, role: "member" },
      })
    ).json();

    await loginAs(page, adminEmail, PASSWORD);
    const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const adminHeaders = { Authorization: `Bearer ${adminToken}` };

    const enabled = await page.request.put(`${API}/orgs/${org.id}/modules/decisions`, { headers: adminHeaders, data: { enabled: true } });
    expect(enabled.ok()).toBeTruthy();
    const project = await (
      await page.request.post(`${API}/projects`, { headers: adminHeaders, data: { organization_id: org.id, name: `E2E Decision Groups ${suffix}`, summary: "" } })
    ).json();
    const memberId: string = member.user_id ?? member.id;
    expect(
      (await page.request.post(`${API}/projects/${project.id}/roles`, { headers: adminHeaders, data: { user_id: memberId, role: "member" } })).ok(),
    ).toBeTruthy();
    const orgGroup = await (await page.request.post(`${API}/orgs/${org.id}/groups`, { headers: adminHeaders, data: { name: groupName } })).json();
    expect(
      (await page.request.post(`${API}/orgs/${org.id}/groups/${orgGroup.id}/members`, { headers: adminHeaders, data: { user_id: memberId } })).ok(),
    ).toBeTruthy();
    expect((await page.request.post(`${API}/projects/${project.id}/groups`, { headers: adminHeaders, data: { name: squadName } })).ok()).toBeTruthy();

    // --- Create a Decision owned by the org group, decided by the project group.
    await page.goto(`/projects/${project.id}/modules/decisions`);
    await page.getByRole("button", { name: "New decision" }).click();
    const dialog = page.getByRole("dialog", { name: "New decision" });
    await dialog.getByLabel("Decision title").fill("Adopt a shared release train");
    await dialog.getByLabel("Decision statement").fill("All teams ship on one release train.");
    await dialog.getByRole("button", { name: "Clear: Owner" }).click();
    await dialog.getByRole("combobox", { name: "Owner", exact: true }).fill("Review Board");
    await dialog.getByRole("option", { name: new RegExp(groupName) }).click();
    await dialog.getByRole("combobox", { name: "Decision maker", exact: true }).fill("Delivery Squad");
    await dialog.getByRole("option", { name: new RegExp(squadName) }).click();
    await dialog.getByRole("button", { name: "Save" }).click();

    // The list's Owner column names the group with its kind and size.
    const row = page.getByRole("row", { name: /DEC-001/ });
    await expect(row.getByText(groupName)).toBeVisible();
    await expect(row.getByText("Org group · 1 member")).toBeVisible();

    // The quick view shows both the owner group and the decision-maker group.
    await page.getByRole("button", { name: "DEC-001" }).click();
    const quickView = page.getByRole("dialog", { name: "DEC-001" });
    await expect(quickView.getByText(groupName)).toBeVisible();
    await expect(quickView.getByText(squadName)).toBeVisible();
    await expect(quickView.getByText(/^Project group/)).toBeVisible();
    await page.keyboard.press("Escape");

    // The "owned by me or my groups" filter hides it for the admin, who is not in the group.
    await page.getByLabel("Owned by me or my groups").check();
    await expect(page.getByRole("button", { name: "DEC-001" })).toHaveCount(0);
    await page.getByLabel("Owned by me or my groups").uncheck();

    // --- A member of the owner group can propose it (the owner gate), though they hold no edit role.
    const memberContext = await browser.newContext();
    const memberPage = await memberContext.newPage();
    try {
      await loginAs(memberPage, memberEmail, PASSWORD);
      await memberPage.goto(`/projects/${project.id}/modules/decisions`);
      await memberPage.getByLabel("Owned by me or my groups").check();
      await memberPage.getByRole("button", { name: "DEC-001" }).click();
      await memberPage.getByRole("dialog", { name: "DEC-001" }).getByRole("link", { name: "View full details" }).click();
      await expect(memberPage.getByRole("heading", { name: "DEC-001" })).toBeVisible();
      await memberPage.getByRole("button", { name: "Propose" }).click();
      await expect(memberPage.getByText("Proposed", { exact: true }).first()).toBeVisible();
    } finally {
      await memberContext.close();
    }

    // --- Deleting the group is blocked while it owns the Decision; hand it to the admin instead.
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Groups");
    const panel = await openOrgGroupPanel(page, groupName);
    await panel.getByRole("button", { name: "Delete group" }).click();
    await page.getByRole("dialog", { name: `Delete "${groupName}"?` }).getByRole("button", { name: "Delete group" }).click();

    const inUse = page.getByRole("dialog", { name: `Delete “${groupName}”?` });
    await expect(inUse.getByText(/1 decision owners/)).toBeVisible();
    // The owner is required, so the optional "leave them empty" route is unavailable.
    await expect(inUse.getByText("Some of these fields are required, so a replacement is needed.")).toBeVisible();
    await inUse.getByRole("combobox", { name: "New owner" }).fill("E2E Group Admin");
    await inUse.getByRole("option", { name: /E2E Group Admin/ }).click();
    await inUse.getByRole("button", { name: "Confirm delete" }).click();
    await expect(page.getByText("Group deleted", { exact: true })).toBeVisible();

    // The Decision now names the admin as its owner.
    await page.goto(`/projects/${project.id}/modules/decisions`);
    await page.getByRole("button", { name: "DEC-001" }).click();
    const afterQuickView = page.getByRole("dialog", { name: "DEC-001" });
    await expect(afterQuickView.getByText(/E2E Group Admin/).first()).toBeVisible();
    await expect(afterQuickView.getByText(groupName)).toHaveCount(0);
  });
});
