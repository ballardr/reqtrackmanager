import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, PERSONAS, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: an org admin can generate a SCIM 2.0 bearer token through
 * the real UI, see it exactly once, and that token then authenticates a
 * real inbound SCIM request (`GET /scim/v2/Users`) — proving the whole
 * generate -> configure-in-IdP -> IdP-calls-us loop actually works end to
 * end, not just that the UI round-trips. Revoking then breaks that same
 * token immediately. The SCIM protocol surface itself (Users/Groups CRUD,
 * PATCH semantics) is covered by backend/tests/test_scim.py — this spec
 * only exercises the token lifecycle through the real UI + one real
 * authenticated call, per this suite's own scoping convention for
 * config-form specs that can't reasonably drive a real external IdP.
 *
 * Uses Gamma (orgAdminGamma is single-org, so `/orgs` auto-navigates) —
 * same choice org-security-controls.spec.ts and org-group-nesting.spec.ts
 * make, to avoid interfering with Alpha/Beta specs sharing this suite's
 * single-worker run.
 */
test.describe("SCIM provisioning token", () => {
  test("generate a token via the UI, use it for a real SCIM request, then revoke it", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);

    // SCIM lives in the "OAuth/SSO" top-level resource-menu group (2026-08
    // UX audit's Org Admin restructure, later split further from a
    // combined "Integrations & security" group — SCIM groups with SSO/OIDC
    // as the two identity-provisioning integrations, see docs/decisions.md)
    // — a real navigation, so it must be selected before the section is
    // reachable at all.
    //
    // CollapsibleSection's expand/collapse choice persists server-side per
    // user across specs sharing a persona — an unconditional click can
    // toggle an already-expanded section shut on a re-run (see
    // ensureExpanded's own docstring in helpers.ts).
    await selectOrgAdminGroup(page, "OAuth/SSO");
    await ensureExpanded(page, "SCIM provisioning");
    await expect(page.getByText("Not enabled.")).toBeVisible();

    let token = "";
    await test.step("generate a token and see it shown exactly once", async () => {
      await page.getByRole("button", { name: "Generate SCIM token" }).click();
      const tokenInput = page.getByText("Copy this token now").locator("xpath=following-sibling::input[1]");
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
      await expect(page.getByText("Not enabled.")).toBeVisible();

      const resp = await page.request.get("http://localhost:8000/scim/v2/Users", {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(resp.status()).toBe(401);
    });
  });
});
