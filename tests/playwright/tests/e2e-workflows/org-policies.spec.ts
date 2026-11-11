import { expect, test, type APIRequestContext } from "@playwright/test";

import { apiHeaders, installCleanupHook, loginAs, ORG_NAMES, onCleanup, PERSONAS, selectOrgAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";
const ADMIN = PERSONAS.orgAdminAlphaBeta.email;

/** Registers cleanup that deletes every policy of the organisation whose title carries `marker`. Idempotent. */
function removePoliciesOnCleanup(organizationId: string, marker: string): void {
  onCleanup(async (request: APIRequestContext) => {
    const headers = await apiHeaders(request, ADMIN);
    const listed = await request.get(`${API}/orgs/${organizationId}/policies`, { headers });
    if (!listed.ok()) return;
    for (const item of (await listed.json()) as { id: string; title: string }[]) {
      if (item.title.includes(marker)) await request.delete(`${API}/orgs/${organizationId}/policies/${item.id}`, { headers });
    }
  });
}

function doc(text: string) {
  return { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text }] }] };
}

/**
 * Job to be done: an organisation administrator adds the organisation's own policies, publishes them (telling the
 * members), and members read them on the Policies page; a policy limited to an audience is absent for everyone else,
 * and nobody outside the organisation can read any of them.
 */
test.describe("organisation policies", () => {
  installCleanupHook();

  test("an administrator publishes a policy, a member reads it and an outsider cannot", async ({ page }) => {
    test.setTimeout(120_000);
    const marker = `E2E Access ${Date.now()}`;
    await loginAs(page, ADMIN);
    const headers = await apiHeaders(page.request, ADMIN);
    const orgs: { id: string; name: string }[] = await (await page.request.get(`${API}/orgs?mine=true`, { headers })).json();
    const alpha = orgs.find((o) => o.name === ORG_NAMES.alpha)!;
    removePoliciesOnCleanup(alpha.id, marker);

    await test.step("the administrator adds a policy from a starter title and publishes it, notifying members", async () => {
      await page.goto(`/orgs/${alpha.id}/admin`);
      await selectOrgAdminGroup(page, "Policies");
      // The list is a table only once a policy exists; a fresh organisation shows its empty state.
      await expect(page.getByRole("button", { name: "New policy" })).toBeVisible();
      await page.getByRole("button", { name: "New policy" }).click();
      const dialog = page.getByRole("dialog", { name: "New policy" });
      await expect(dialog.getByText("Every member of the organisation.")).toBeVisible();
      await dialog.getByRole("button", { name: "Access policy" }).click();
      await dialog.getByRole("textbox", { name: /^Title/ }).fill(marker);
      await dialog.getByRole("textbox", { name: "Policy text" }).click();
      await page.keyboard.type("Request access through your manager.");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Policy created.")).toBeVisible();

      await page.getByRole("button", { name: `Publish ${marker}` }).click();
      const publish = page.getByRole("dialog", { name: `Publish "${marker}"?` });
      await publish.getByRole("checkbox", { name: "Notify members" }).check();
      await publish.getByRole("button", { name: "Publish" }).click();
      await expect(page.getByText("Policy published.")).toBeVisible();
    });

    await test.step("a member reads it on the Policies page and was notified", async () => {
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.getByRole("link", { name: "Policies" }).click();
      await expect(page.getByText("Request access through your manager.")).toBeVisible();
      const memberHeaders = await apiHeaders(page.request, PERSONAS.stakeholderAlpha.email);
      const notifications: { type: string }[] = await (await page.request.get(`${API}/notifications`, { headers: memberHeaders })).json();
      expect(notifications.some((n) => n.type === "policy_published")).toBeTruthy();
    });

    await test.step("an administrator of another organisation cannot read it, even by address", async () => {
      const listed: { id: string; title: string }[] = await (await page.request.get(`${API}/orgs/${alpha.id}/policies`, { headers })).json();
      const policyId = listed.find((p) => p.title === marker)!.id;
      const outsider = await apiHeaders(page.request, PERSONAS.orgAdminGamma.email);
      expect((await page.request.get(`${API}/policies/mine/${policyId}`, { headers: outsider })).status()).toBe(404);
    });
  });

  test("a policy limited to an audience is absent for a member outside it", async ({ page }) => {
    test.setTimeout(90_000);
    const marker = `E2E Confidentiality ${Date.now()}`;
    await loginAs(page, ADMIN);
    const headers = await apiHeaders(page.request, ADMIN);
    const orgs: { id: string; name: string }[] = await (await page.request.get(`${API}/orgs?mine=true`, { headers })).json();
    const alpha = orgs.find((o) => o.name === ORG_NAMES.alpha)!;
    removePoliciesOnCleanup(alpha.id, marker);

    const inside = await apiHeaders(page.request, PERSONAS.stakeholderAlpha.email);
    const me: { id: string } = await (await page.request.get(`${API}/auth/me`, { headers: inside })).json();
    const created = await page.request.post(`${API}/orgs/${alpha.id}/policies`, {
      headers, data: { title: marker, body: doc("Keep client information private."), audience: [{ type: "user", id: me.id }] },
    });
    expect(created.ok()).toBeTruthy();
    const { id } = await created.json();
    expect((await page.request.post(`${API}/orgs/${alpha.id}/policies/${id}/publish`, { headers, data: {} })).ok()).toBeTruthy();

    await test.step("the audience member reads it", async () => {
      expect((await page.request.get(`${API}/policies/mine/${id}`, { headers: inside })).ok()).toBeTruthy();
    });

    await test.step("another member of the organisation gets a 404 and does not see it listed", async () => {
      const other = await apiHeaders(page.request, PERSONAS.stakeholderAlpha2.email);
      expect((await page.request.get(`${API}/policies/mine/${id}`, { headers: other })).status()).toBe(404);
      const mine: { title: string }[] = await (await page.request.get(`${API}/policies/mine`, { headers: other })).json();
      expect(mine.some((p) => p.title === marker)).toBeFalsy();
    });

    await test.step("the administrator list shows who the policy is limited to", async () => {
      await loginAs(page, ADMIN);
      await page.goto(`/orgs/${alpha.id}/admin`);
      await selectOrgAdminGroup(page, "Policies");
      const row = page.getByRole("table", { name: "Policies" }).getByRole("row", { name: new RegExp(marker) });
      await expect(row).toContainText(PERSONAS.stakeholderAlpha.name);
    });
  });
});
