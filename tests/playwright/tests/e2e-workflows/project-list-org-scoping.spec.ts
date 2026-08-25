import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: a server admin's project list — both the org filter and
 * the "new project" org picker — must only ever offer organisations they
 * actually belong to, never the full server-wide directory `GET /orgs`
 * otherwise returns them (I-M-05's one deliberate bypass, meant for the
 * platform-level org directory, not "orgs I can act within"). And when
 * that scoped set is down to a single org, neither control should even be
 * shown — there's no real choice to make.
 *
 * Builds two disposable orgs via the API and self-elevates into them
 * (the same join-as-admin pattern `backend/scripts/seed_e2e_dataset.py`
 * itself uses for its zero-org server-admin persona) rather than reusing
 * the shared Alpha/Beta/Gamma orgs, so this doesn't leave PERSONAS.
 * serverAdmin permanently multi-org for other specs in the suite.
 */
test.describe("project list organisation scoping for a server admin", () => {
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
    const orgB = await (
      await page.request.post("http://localhost:8000/api/v1/orgs", { headers: authHeaders, data: { name: orgBName } })
    ).json();
    for (const org of [orgA, orgB]) {
      const resp = await page.request.post(`http://localhost:8000/api/v1/orgs/${org.id}/join-as-admin`, { headers: authHeaders });
      expect(resp.status()).toBe(204);
    }

    // Real UI navigation, not just an API assertion — the actual bug
    // reported was what the page renders. Intercept the real request the
    // page fires so this checks the exact response the UI acted on, rather
    // than a separately-issued one that could drift from what the page
    // actually calls.
    const orgsResponse = page.waitForResponse((r) => r.url().includes("/api/v1/orgs?mine=true") && r.status() === 200);
    await page.goto("/projects");
    const orgsBody: { id: string; name: string }[] = await (await orgsResponse).json();
    const scopedIds = orgsBody.map((o) => o.id);
    expect(scopedIds).toContain(orgA.id);
    expect(scopedIds).toContain(orgB.id);
    // The negative check that actually proves the fix: some other org in
    // the deployment (every shared E2E persona org qualifies) must not
    // leak in just because this caller is a server admin.
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

    // Drop to a single org. Hard-deletes org B rather than self-service
    // leaving it (`DELETE /orgs/{id}/membership`, mirroring Preferences'
    // own "Leave organisation" action, under its "Your access" tab):
    // this server admin self-elevated as
    // org B's *only* admin above, so leaving would hit the "can't strip an
    // org's last admin" guard (409) — deletion is server-admin-only and
    // doesn't require ongoing membership, and these orgs are disposable
    // either way. Now there's no real choice between orgs, so both
    // controls should disappear entirely rather than offering one option.
    const deleteBResp = await page.request.delete(`http://localhost:8000/api/v1/orgs/${orgB.id}`, {
      headers: authHeaders, data: { confirm_name: orgBName },
    });
    expect(deleteBResp.status()).toBe(204);
    await page.reload();
    await expect(page.locator("select:has(option:text-is('All organisations'))")).toHaveCount(0);
    await page.getByRole("button", { name: "New project" }).click();
    const soloDialog = page.getByRole("dialog", { name: "New project" });
    // No org select now (org A has no projects yet either, so the template
    // picker is also absent) — org A is the only valid choice, applied
    // implicitly rather than asked for. The Visibility select is a real,
    // always-meaningful choice independent of org count, so it's the one
    // select still expected here.
    await expect(soloDialog.locator("select")).toHaveCount(1);
    await expect(soloDialog.getByLabel("Visibility")).toBeVisible();

    // Delete org A too, restoring the shared persona to its documented
    // zero-org baseline for any other spec that runs after this one.
    await page.request.delete(`http://localhost:8000/api/v1/orgs/${orgA.id}`, {
      headers: authHeaders, data: { confirm_name: orgAName },
    });
  });
});
