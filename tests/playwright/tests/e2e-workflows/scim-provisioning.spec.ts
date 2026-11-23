import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, PERSONAS, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: an org admin can generate a SCIM 2.0 bearer token through the UI, see it exactly once, and that
 * token authenticates a real inbound SCIM request (`GET /scim/v2/Users`), proving the generate -> configure-in-IdP ->
 * IdP-calls-us loop end to end. Revoking then breaks that token immediately. The SCIM protocol surface (Users/Groups
 * CRUD, PATCH semantics) is covered by backend/tests/test_scim.py; this spec exercises the token lifecycle through
 * the UI plus one authenticated call, since a config-form spec cannot drive a real external IdP.
 *
 * Uses Gamma (orgAdminGamma is single-org, so `/orgs` navigates straight in), as org-security-controls.spec.ts and
 * org-group-nesting.spec.ts do, to avoid interfering with Alpha/Beta specs.
 */
test.describe("SCIM provisioning token", () => {
  test("generate a token via the UI, use it for a real SCIM request, then revoke it", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);

    // Idempotent start: a token left by an earlier, interrupted run is revoked through the API first.
    const orgId = page.url().match(/\/orgs\/([^/]+)\/admin/)![1];
    const bearer = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    await page.request.delete(`http://localhost:8000/api/v1/orgs/${orgId}/scim-token`, { headers: { Authorization: `Bearer ${bearer}` } });
    await page.reload();

    // SCIM sits in the "OAuth/SSO" top-level resource-menu group, a real navigation that must be selected first.
    //
    // CollapsibleSection's expand/collapse choice persists server-side per user across specs sharing a persona, so an
    // unconditional click can toggle an already-expanded section shut on a re-run (see `ensureExpanded` in helpers.ts).
    await selectOrgAdminGroup(page, "OAuth/SSO");
    await ensureExpanded(page, "SCIM provisioning");
    await expect(page.getByText("Not enabled.")).toBeVisible();

    let token = "";
    await test.step("generate a token and see it shown exactly once", async () => {
      await page.getByRole("button", { name: "Generate SCIM token" }).click();
      const tokenInput = page.getByLabel("SCIM token", { exact: true });
      await expect(tokenInput).toBeVisible();
      token = await tokenInput.inputValue();
      expect(token).toMatch(/^rtm_scim_/);
      await expect(page.getByText(/^Enabled — current token starts with/)).toBeVisible();
    });

    await test.step("the generated token authenticates a real SCIM request", async () => {
      const resp = await page.request.get("http://localhost:8000/scim/v2/Users", {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(resp.status()).toBe(200);
      const body = await resp.json();
      expect(body.schemas).toContain("urn:ietf:params:scim:api:messages:2.0:ListResponse");
    });

    await test.step("revoking the token via the UI breaks it immediately", async () => {
      await page.getByRole("button", { name: "Revoke" }).click();
      // Revoking the live credential asks first.
      await page.getByRole("dialog", { name: "Revoke the SCIM token?" }).getByRole("button", { name: "Revoke" }).click();
      await expect(page.getByText("Not enabled.")).toBeVisible();

      const resp = await page.request.get("http://localhost:8000/scim/v2/Users", {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(resp.status()).toBe(401);
    });
  });
});
