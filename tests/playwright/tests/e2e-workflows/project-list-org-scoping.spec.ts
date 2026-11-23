import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: a server admin's project list (the org filter and the "new project" org picker) offers only
 * organisations they belong to, never the full server-wide directory `GET /orgs` otherwise returns (a deliberate
 * bypass meant for the platform-level org directory, not "orgs I can act within"). When that scoped set is a single
 * organisation, neither control is shown, since there is no choice to make.
 *
 * Builds two disposable organisations through the API and self-elevates into them (the join-as-admin pattern
 * `backend/scripts/seed_e2e_dataset.py` uses for its zero-org server-admin persona) rather than reusing the shared
 * Alpha/Beta/Gamma organisations, so PERSONAS.serverAdmin does not become permanently multi-org for other specs.
 */
test.describe("project list organisation scoping for a server admin", () => {
  installCleanupHook();

  test("org filter and new-project org picker only list orgs the server admin actually belongs to", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);
    const serverAdminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${serverAdminToken}` };

    const suffix = Date.now();
    const orgAName = `E2E Scoping Org A (${suffix})`;
    const orgBName = `E2E Scoping Org B (${suffix})`;

    const orgA = await (
      await page.request.post("http://localhost:8000/api/v1/orgs", { headers: authHeaders, data: { name: orgAName } })
    ).json();
    deleteOrgOnCleanup({ id: orgA.id });
    const orgB = await (
      await page.request.post("http://localhost:8000/api/v1/orgs", { headers: authHeaders, data: { name: orgBName } })
    ).json();
    deleteOrgOnCleanup({ id: orgB.id });

    // Both organisations are deleted after the test (`deleteOrgOnCleanup` above, an afterEach that runs even on failure
    // or timeout): the test self-elevates the shared serverAdmin persona into both, and leaked organisations accumulate
    // scoped organisations across retries.
    for (const org of [orgA, orgB]) {
      const resp = await page.request.post(`http://localhost:8000/api/v1/orgs/${org.id}/join-as-admin`, { headers: authHeaders });
      expect(resp.status()).toBe(204);
    }

    // Real UI navigation, not only an API assertion, since the page's rendering is what matters. The real request the
    // page fires is intercepted so the check uses the exact response the UI acted on.
    const orgsResponse = page.waitForResponse((r) => r.url().includes("/api/v1/orgs?mine=true") && r.status() === 200);
    await page.goto("/projects");
    const orgsBody: { id: string; name: string }[] = await (await orgsResponse).json();
    const scopedIds = orgsBody.map((o) => o.id);
    expect(scopedIds).toContain(orgA.id);
    expect(scopedIds).toContain(orgB.id);
    // The negative check: no other org in the deployment (every shared E2E persona org qualifies) may leak in because
    // the caller is a server admin.
    expect(scopedIds.length).toBe(2);

    // Two orgs — a real choice exists, so both controls must be offered,
    // and neither may offer anything beyond org A/B.
    const orgFilter = page.locator("select:has(option:text-is('All organisations'))");
    await expect(orgFilter).toBeVisible();
    await expect(orgFilter.locator("option")).toHaveText(["All organisations", orgAName, orgBName]);

    // "New project" opens a Modal (style guide "Pattern: modal dialog for
    // entity create/rename") — scoped to it rather than a bare ".card".
    await page.getByRole("button", { name: "New project" }).click();
    const newProjectDialog = page.getByRole("dialog", { name: "New project" });
    const orgPicker = newProjectDialog.locator("select").first();
    await expect(orgPicker.locator("option")).toHaveText([orgAName, orgBName]);

    // Drop to a single org by hard-deleting org B rather than self-service leaving it (`DELETE /orgs/{id}/membership`,
    // Preferences' "Leave organisation" action): this server admin self-elevated as org B's only admin, so leaving would
    // hit the "can't strip an org's last admin" guard (409). Deletion is server-admin-only and needs no ongoing
    // membership. With no real choice between organisations, both controls disappear.
    const deleteBResp = await page.request.delete(`http://localhost:8000/api/v1/orgs/${orgB.id}`, {
      headers: authHeaders, data: { confirm_name: orgBName },
    });
    expect(deleteBResp.status()).toBe(204);
    await page.reload();
    await expect(page.locator("select:has(option:text-is('All organisations'))")).toHaveCount(0);
    await page.getByRole("button", { name: "New project" }).click();
    const soloDialog = page.getByRole("dialog", { name: "New project" });
    // No org select (org A has no projects, so the template picker is also absent): org A is the only valid choice and
    // is applied implicitly. Visibility is a meaningful choice regardless of org count, so that select is expected. The
    // "Parent project" picker is `can_be_parent`-gated (docs/decisions.md) and org A has no projects, so it renders
    // nothing rather than a picker whose only option is "None".
    await expect(soloDialog.locator("select")).toHaveCount(1);
    await expect(soloDialog.getByLabel("Visibility")).toBeVisible();
    await expect(soloDialog.getByText("Parent project")).toHaveCount(0);
  });
});
