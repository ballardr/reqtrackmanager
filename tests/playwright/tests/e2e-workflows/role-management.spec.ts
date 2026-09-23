import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, ORG_NAMES, PERSONAS, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: Fine-Grained Access Control (core, `docs/plans/
 * core-fine-grained-access-control-plan.md` Phase 3) — the "Role
 * Management" org-settings page. Covers the create -> grant ->
 * visible-in-UI -> revoke flow this phase's own testing requirement names
 * explicitly; full backend enforcement of the resulting permission is
 * already covered by `backend/tests/test_custom_roles_api.py` and
 * `test_effective_permissions.py`, so this spec focuses on the UI wiring:
 * the permission-atom picker populates from the real `GET .../permissions`
 * vocabulary, a created role appears in the definitions table, granting it
 * to a real user merges into the Users table's existing Roles dropdown
 * (the same generic-rendering pattern module-contributed roles already use
 * — see `module-contributed-roles.spec.ts`), the grant survives a reload
 * (proving it's real server state, not an optimistic local patch), and
 * revoking/deleting cleans up after itself.
 *
 * Uses a dynamically-named role (`Date.now()` suffix) rather than a fixed
 * seeded fixture, and deletes it at the end — this repo's standing
 * test-idempotency rule (a role name must be unique per organisation, so a
 * re-run against leftover state from a previous run would 409 on create).
 * The grant target is the existing seeded `memberAlphaBeta` persona,
 * granted then revoked within the same test, mirroring `module-contributed-
 * roles.spec.ts`'s own "grant, assert, revoke, assert" cleanup shape for
 * that persona's `project_creator` role.
 */
test.describe("Fine-Grained Access Control: Role Management", () => {
  test("org admin creates a custom role, grants it to a user, sees it reflected after reload, revokes it, and deletes it", async ({
    page,
  }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/orgs");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);

    await selectOrgAdminGroup(page, "Role management");

    const roleName = `E2E Custom Role ${Date.now()}`;

    // --- Create -------------------------------------------------------
    await page.getByRole("button", { name: "New custom role" }).click();
    const createDialog = page.getByRole("dialog", { name: "New custom role" });
    await createDialog.getByLabel("Name").fill(roleName);
    await createDialog.getByLabel("Description").fill("Created by role-management.spec.ts");

    // A couple of permission atoms, populated from the real, server-derived
    // vocabulary (`GET /orgs/{id}/permissions`) — never hardcoded by the
    // frontend, so finding these checkboxes at all proves that endpoint
    // populated the picker correctly.
    await createDialog.getByRole("checkbox", { name: "Grant Roles" }).check();
    await createDialog.getByRole("checkbox", { name: "requirement — view", exact: true }).check();
    await createDialog.getByRole("button", { name: "Save" }).click();

    await expect(page.getByText("Custom role created")).toBeVisible();
    await expect(createDialog).not.toBeVisible();
    // `exact: true` — the row's Actions cell also matches loosely (its
    // Edit/Delete buttons' own accessible names each embed the role name).
    await expect(page.getByRole("cell", { name: roleName, exact: true })).toBeVisible();

    // --- Grant to a user, via the Users table's existing Roles dropdown -
    // (the same generic-rendering pattern already used for module roles,
    // not a parallel, separately-built assignment UI — Phase 3's own
    // scope requirement).
    await selectOrgAdminGroup(page, "Users");
    await ensureExpanded(page, "Organisation users");

    const rolesButton = page.getByRole("button", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
    await rolesButton.click();
    const rolesGroup = page.getByRole("group", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
    await expect(rolesGroup.getByText(roleName, { exact: true })).toBeVisible();

    const grantCheckbox = rolesGroup.getByRole("checkbox", {
      name: new RegExp(`Grant ${roleName} to ${PERSONAS.memberAlphaBeta.name}`),
    });
    await grantCheckbox.click();
    await expect(
      rolesGroup.getByRole("checkbox", { name: new RegExp(`Revoke ${roleName} from ${PERSONAS.memberAlphaBeta.name}`) })
    ).toBeChecked();
    await page.keyboard.press("Escape");

    // Reload to prove the grant is real, server-persisted state (a fresh
    // GET /orgs/{id}/users), not merely an optimistic client-side patch.
    await page.reload();
    await selectOrgAdminGroup(page, "Users");
    await ensureExpanded(page, "Organisation users");
    await page.getByRole("button", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` }).click();
    const rolesGroupAfterReload = page.getByRole("group", { name: `${PERSONAS.memberAlphaBeta.name}'s roles` });
    const revokeCheckbox = rolesGroupAfterReload.getByRole("checkbox", {
      name: new RegExp(`Revoke ${roleName} from ${PERSONAS.memberAlphaBeta.name}`),
    });
    await expect(revokeCheckbox).toBeChecked();

    // --- Revoke ---------------------------------------------------------
    await revokeCheckbox.click();
    await expect(
      rolesGroupAfterReload.getByRole("checkbox", { name: new RegExp(`Grant ${roleName} to ${PERSONAS.memberAlphaBeta.name}`) })
    ).not.toBeChecked();
    await page.keyboard.press("Escape");

    // --- Cleanup: delete the role definition itself ----------------------
    await selectOrgAdminGroup(page, "Role management");
    await page.getByRole("button", { name: `Delete ${roleName}` }).click();
    const deleteDialog = page.getByRole("dialog", { name: "Delete custom role?" });
    await expect(deleteDialog.getByText(new RegExp(`This removes "${roleName}"`))).toBeVisible();
    await deleteDialog.getByRole("button", { name: "Delete" }).click();
    await expect(page.getByText("Custom role deleted")).toBeVisible();
    await expect(page.getByRole("cell", { name: roleName, exact: true })).not.toBeVisible();
  });

  test("a caller without ORG_ADMIN cannot see the role-definition half but the group is still reachable", async ({ page }) => {
    // memberAlphaBeta holds only `member` in Alpha (no ORG_ADMIN) — proves
    // Phase 0 Q8's access-split decision: `GET .../advanced-settings`
    // 403s for them (the same signal every other ORG_ADMIN-only section on
    // this page already gates on), so "New custom role" and the
    // definitions table are absent, while the group itself still loads
    // (this org member can browse the org's existing custom roles and,
    // were they ever granted `grant_roles`, use the assignment half below).
    await loginAs(page, PERSONAS.memberAlphaBeta.email);
    await page.goto("/orgs");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);

    await selectOrgAdminGroup(page, "Role management");
    await expect(page.getByText("Grant roles to users or groups")).toBeVisible();
    await expect(page.getByRole("button", { name: "New custom role" })).toHaveCount(0);
  });
});
