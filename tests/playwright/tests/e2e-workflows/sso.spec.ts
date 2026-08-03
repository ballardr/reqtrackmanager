import { expect, test } from "@playwright/test";

/**
 * End-to-end proof that Massif (v3)'s OIDC SSO login (E-U-01) actually
 * works against a real identity provider, not just on paper: this drives a
 * real browser through the full authorization-code flow against the
 * Keycloak instance in tests/container/docker-compose.yml (realm/client/
 * test users defined in tests/container/keycloak/realm-export.json), and
 * confirms the resulting account is provisioned with the org role its
 * Keycloak group maps to (services/oidc_provisioning.py).
 *
 * Configures the org's SSO settings via API first (setup, not what's being
 * tested), then drives the actual login — the org-branded login page,
 * Keycloak's own real login form, the callback — entirely through the
 * browser, the same as a real user would.
 */

const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "ChangeMe123!";
const ORG_SLUG = "sso-e2e-org";
const KEYCLOAK_ISSUER = "http://localhost:8080/realms/reqtrack";
const KEYCLOAK_CLIENT_ID = "reqtrack-backend";
const KEYCLOAK_CLIENT_SECRET = "reqtrack-backend-secret";
const KEYCLOAK_ADMIN_USER = "sso-admin@example.com";
const KEYCLOAK_MEMBER_USER = "sso-member@example.com";
const KEYCLOAK_PASSWORD = "KeycloakPass123!";
const apiBaseUrl = "http://localhost:8000";

test("SSO login: real Keycloak authorization-code flow provisions the user and syncs their org role", async ({ page }) => {
  let orgId = "";

  await test.step("configure the org's SSO settings via API (setup)", async () => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(ADMIN_EMAIL);
    await page.getByLabel("Password").fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${token}` };
    // GET /orgs returns every org this server admin created (including the
    // E2E-workflow seed orgs), not just ones it's actually a member of —
    // find the admin's own org by name rather than assuming index 0.
    const orgs = await (await page.request.get(`${apiBaseUrl}/api/v1/orgs`, { headers: authHeaders })).json();
    orgId = orgs.find((o: { name: string }) => o.name === "Default Organization").id;

    const ssoResp = await page.request.put(`${apiBaseUrl}/api/v1/orgs/${orgId}/sso-config`, {
      headers: authHeaders,
      data: {
        slug: ORG_SLUG, sso_enabled: true, sso_only: false,
        oidc_issuer_url: KEYCLOAK_ISSUER, oidc_client_id: KEYCLOAK_CLIENT_ID, oidc_client_secret: KEYCLOAK_CLIENT_SECRET,
      },
    });
    expect(ssoResp.ok()).toBe(true);

    // Group -> org role mapping (services/oidc_provisioning.py): Keycloak's
    // "reqtrack-org-admins" group (sso-admin@example.com's membership, per
    // realm-export.json) maps to this app's org_admin role.
    const advResp = await page.request.put(`${apiBaseUrl}/api/v1/orgs/${orgId}/advanced-settings`, {
      headers: authHeaders,
      data: { sso_group_mappings: [{ sso_group: "reqtrack-org-admins", org_role: "org_admin" }] },
    });
    expect(advResp.ok()).toBe(true);

    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL(/\/login$/);
  });

  await test.step("real browser login through Keycloak's own login form via the org-branded page", async () => {
    await page.goto(`/login/${ORG_SLUG}`);
    await expect(page.getByRole("link", { name: "Sign in with SSO" })).toBeVisible();
    await page.getByRole("link", { name: "Sign in with SSO" }).click();

    // Now on Keycloak's real, self-hosted login form (not this app's UI).
    await page.waitForURL(/localhost:8080\/realms\/reqtrack\//);
    await page.getByLabel(/username or email/i).fill(KEYCLOAK_ADMIN_USER);
    await page.getByLabel("Password", { exact: true }).fill(KEYCLOAK_PASSWORD);
    await page.getByRole("button", { name: /sign in/i }).click();

    // Keycloak redirects to the backend callback, which redirects to the
    // frontend's /oidc-complete handler, which lands in the authenticated app.
    await page.waitForURL(/\/projects(\/|$)/, { timeout: 15000 });
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  });

  await test.step("the SSO-provisioned account has the mapped org role", async () => {
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const me = await (await page.request.get(`${apiBaseUrl}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${token}` } })).json();
    expect(me.email).toBe(KEYCLOAK_ADMIN_USER);

    const orgUsers = await (
      await page.request.get(`${apiBaseUrl}/api/v1/orgs/${orgId}/users`, { headers: { Authorization: `Bearer ${token}` } })
    ).json();
    const provisioned = orgUsers.find((u: { email: string }) => u.email === KEYCLOAK_ADMIN_USER);
    expect(provisioned?.roles).toContain("org_admin");
  });
});

test("SSO login: a user in a Keycloak group with no configured mapping gets an account but no org role", async ({ page }) => {
  // A fresh Playwright test gets its own isolated browser context (no
  // shared cookies with the previous test), so Keycloak's own login form
  // is expected here regardless of the earlier test's session.
  await page.goto(`/login/${ORG_SLUG}`);
  await page.getByRole("link", { name: "Sign in with SSO" }).click();
  await page.waitForURL(/localhost:8080\/realms\/reqtrack\//);
  await page.getByLabel(/username or email/i).fill(KEYCLOAK_MEMBER_USER);
  await page.getByLabel("Password", { exact: true }).fill(KEYCLOAK_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  await page.waitForURL(/\/projects(\/|$)/, { timeout: 15000 });
  const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const me = await (await page.request.get(`${apiBaseUrl}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${token}` } })).json();
  expect(me.email).toBe(KEYCLOAK_MEMBER_USER);

  const orgResp = await page.request.get(`${apiBaseUrl}/api/v1/orgs`, { headers: { Authorization: `Bearer ${token}` } });
  // sso-member@example.com is only in Keycloak's "reqtrack-members" group,
  // which this org has no mapping for — the account exists but holds no
  // org role, same as any other user nobody has granted access to yet, so
  // it sees zero organisations.
  expect((await orgResp.json())).toEqual([]);
});

test("SSO login via mcp-server's own /login page: real Keycloak flow lands on the MCP token page", async ({ page }) => {
  // Proves mcp-server/server.py's SSO addition end to end, the same way the
  // tests above prove the frontend's own SSO login: a real browser through
  // Keycloak's real login form, but started from mcp-server's /login page
  // (client=mcp) instead of the app's /login/{slug} page, landing on
  // mcp-server's own /login/oidc/complete with a usable token rather than
  // in the authenticated app UI.
  const mcpServerUrl = "http://localhost:8100";

  await page.goto(`${mcpServerUrl}/login?org=${ORG_SLUG}`);
  await expect(page.getByRole("button", { name: /Sign in with .* via SSO/ })).toBeVisible();
  await page.getByRole("button", { name: /Sign in with .* via SSO/ }).click();

  await page.waitForURL(/localhost:8080\/realms\/reqtrack\//);
  await page.getByLabel(/username or email/i).fill(KEYCLOAK_ADMIN_USER);
  await page.getByLabel("Password", { exact: true }).fill(KEYCLOAK_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  // Keycloak redirects to the backend callback, which — because this login
  // was started with client=mcp — redirects to mcp-server's own
  // /login/oidc/complete instead of the frontend's /oidc-complete.
  await page.waitForURL("**/login/oidc/complete**", { timeout: 15000 });
  await expect(page.getByText("Signed in")).toBeVisible();

  const tokenText = await page.locator(".token-box").first().textContent();
  expect(tokenText?.split(".").length).toBe(3); // looks like a JWT (header.payload.signature)

  // The token this real SSO round trip produced is a genuine, usable
  // ReqTrackManager access token for the Keycloak-provisioned account.
  const me = await (await page.request.get(`${apiBaseUrl}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${tokenText}` } })).json();
  expect(me.email).toBe(KEYCLOAK_ADMIN_USER);
});

async function requireOrgAdminsGroup(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const authHeaders = { Authorization: `Bearer ${token}` };
  // GET /orgs returns every org this server admin created (including the
  // E2E-workflow seed orgs), not just ones it's actually a member of — find
  // the admin's own org by name rather than assuming index 0.
  const orgs = await (await page.request.get(`${apiBaseUrl}/api/v1/orgs`, { headers: authHeaders })).json();
  const orgId = orgs.find((o: { name: string }) => o.name === "Default Organization").id;

  // Full PUT (not a partial patch) — resend the config the earlier tests
  // already set, adding the required-group gate on top of it.
  const ssoResp = await page.request.put(`${apiBaseUrl}/api/v1/orgs/${orgId}/sso-config`, {
    headers: authHeaders,
    data: {
      slug: ORG_SLUG, sso_enabled: true, sso_only: false,
      oidc_issuer_url: KEYCLOAK_ISSUER, oidc_client_id: KEYCLOAK_CLIENT_ID, oidc_client_secret: KEYCLOAK_CLIENT_SECRET,
      oidc_required_group: "reqtrack-org-admins",
    },
  });
  expect(ssoResp.ok()).toBe(true);
  expect((await ssoResp.json()).oidc_required_group).toBe("reqtrack-org-admins");

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(/\/login$/);
}

test("SSO login: a required-group gate blocks a real authenticated user who isn't in that group", async ({ page }) => {
  // Each `test()` gets its own isolated browser context, so Keycloak's own
  // SSO session never carries over between this test and the next one
  // (unlike test.step, which shares one page/context throughout).
  await requireOrgAdminsGroup(page);

  await page.goto(`/login/${ORG_SLUG}`);
  await page.getByRole("link", { name: "Sign in with SSO" }).click();
  await page.waitForURL(/localhost:8080\/realms\/reqtrack\//);
  // sso-member@example.com is only in "reqtrack-members" (per
  // realm-export.json), not the required "reqtrack-org-admins" group.
  await page.getByLabel(/username or email/i).fill(KEYCLOAK_MEMBER_USER);
  await page.getByLabel("Password", { exact: true }).fill(KEYCLOAK_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  // Real Keycloak authentication succeeds — the block happens entirely on
  // this app's side, after token verification, before a session exists.
  await page.waitForURL(/\/oidc-complete/, { timeout: 15000 });
  await expect(page.getByText(/has not provisioned you access/i)).toBeVisible();
  const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  expect(token).toBeNull();
});

test("SSO login: a user IN the required group still gets in", async ({ page }) => {
  // Relies on the gate configured by the previous test (Playwright runs a
  // file's tests in declaration order by default) — re-applying it here too
  // so this test also passes if run in isolation.
  await requireOrgAdminsGroup(page);

  await page.goto(`/login/${ORG_SLUG}`);
  await page.getByRole("link", { name: "Sign in with SSO" }).click();
  await page.waitForURL(/localhost:8080\/realms\/reqtrack\//);
  await page.getByLabel(/username or email/i).fill(KEYCLOAK_ADMIN_USER);
  await page.getByLabel("Password", { exact: true }).fill(KEYCLOAK_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  await page.waitForURL(/\/projects(\/|$)/, { timeout: 15000 });
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
});
