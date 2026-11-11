import { expect, test, type APIRequestContext } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

function doc(text: string) {
  return { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text }] }] };
}

async function login(request: APIRequestContext, email: string, password: string) {
  const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
  expect(resp.ok()).toBeTruthy();
  return { Authorization: `Bearer ${(await resp.json()).access_token}` };
}

/**
 * Job to be done: an organisation administrator requires the members to accept a confidentiality agreement; a member
 * is asked on sign-in, can read but cannot change records until accepting, and the administrator sees who has accepted;
 * a new version asks again. Runs in its own disposable organisation so the requirement never blocks another spec.
 */
test.describe("policy acceptance", () => {
  installCleanupHook();

  test("a required policy is accepted by a member and tracked by the administrator", async ({ page, request }) => {
    test.setTimeout(150_000);
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-accept-admin-${suffix}@example.com`;
    const memberEmail = `e2e-accept-member-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Acceptance ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    for (const [email, name, role] of [[adminEmail, "Acceptance Admin", "org_admin"], [memberEmail, "Acceptance Member", "member"]]) {
      const made = await request.post(`${API}/orgs/${org.id}/users`, {
        headers: serverHeaders, data: { email, display_name: name, password: PASSWORD, role },
      });
      expect(made.ok(), await made.text()).toBeTruthy();
    }
    const title = `Confidentiality ${suffix}`;

    await test.step("the administrator writes the agreement, requires acceptance and publishes it", async () => {
      await loginAs(page, adminEmail, PASSWORD);
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Policies");
      await page.getByRole("button", { name: "New policy" }).click();
      const dialog = page.getByRole("dialog", { name: "New policy" });
      await dialog.getByRole("textbox", { name: /^Title/ }).fill(title);
      await dialog.getByRole("switch", { name: "Require acceptance" }).click();
      await dialog.getByRole("textbox", { name: "Policy text" }).click();
      await page.keyboard.type("Keep client information private.");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Policy created.")).toBeVisible();
      await expect(page.getByRole("table", { name: "Policies" }).getByRole("row", { name: new RegExp(title) })).toContainText("Acceptance required");
      await page.getByRole("button", { name: `Publish ${title}` }).click();
      await page.getByRole("dialog", { name: `Publish "${title}"?` }).getByRole("button", { name: "Publish" }).click();
      await expect(page.getByText("Policy published.")).toBeVisible();
    });

    await test.step("the member is asked on sign-in and the notice stays after closing the dialog", async () => {
      await loginAs(page, memberEmail, PASSWORD);
      const dialog = page.getByRole("dialog", { name: "Policy needs your acceptance" });
      await expect(dialog.getByText("Keep client information private.")).toBeVisible();
      await dialog.getByRole("button", { name: "Close" }).click();
      await expect(page.getByRole("status").filter({ hasText: "needs your acceptance" })).toBeVisible();
    });

    await test.step("until accepting, the member can read but cannot change records", async () => {
      const headers = await login(request, memberEmail, PASSWORD);
      expect((await request.get(`${API}/policies/mine`, { headers })).ok()).toBeTruthy();
      const blocked = await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: "Blocked", summary: "" } });
      expect(blocked.status()).toBe(403);
      expect((await blocked.json()).detail.code).toBe("policy_acknowledgement_required");
    });

    await test.step("the member accepts on the Policies page and the notice goes", async () => {
      await page.getByRole("link", { name: "Review and accept" }).click();
      await expect(page.getByText("Your acceptance is required")).toBeVisible();
      await page.getByRole("button", { name: "Accept" }).click();
      await expect(page.getByText("Policy accepted.")).toBeVisible();
      await expect(page.getByText("Your acceptance is required")).toHaveCount(0);
      await expect(page.getByRole("status").filter({ hasText: "needs your acceptance" })).toHaveCount(0);
    });

    await test.step("the administrator sees the member as accepted and the other administrator as waiting", async () => {
      await loginAs(page, adminEmail, PASSWORD);
      await page.getByRole("dialog", { name: "Policy needs your acceptance" }).getByRole("button", { name: "Close" }).click();
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Policies");
      await page.getByRole("button", { name: `Acceptance of ${title}` }).click();
      const dialog = page.getByRole("dialog", { name: `Acceptance: ${title}` });
      await expect(dialog.getByText("1 of 2 accepted version 1.")).toBeVisible();
      await expect(dialog.getByRole("row", { name: /Acceptance Member/ })).toContainText("Accepted");
      await expect(dialog.getByRole("row", { name: /Acceptance Admin/ })).toContainText("Not accepted");
    });

    await test.step("a new version asks the member again", async () => {
      const adminHeaders = await login(request, adminEmail, PASSWORD);
      const listed: { id: string; title: string }[] = await (await request.get(`${API}/orgs/${org.id}/policies`, { headers: adminHeaders })).json();
      const id = listed.find((p) => p.title === title)!.id;
      expect((await request.put(`${API}/orgs/${org.id}/policies/${id}`, { headers: adminHeaders, data: { title, body: doc("Keep everything private.") } })).ok()).toBeTruthy();
      expect((await request.post(`${API}/orgs/${org.id}/policies/${id}/publish`, { headers: adminHeaders, data: { change_note: "Wider scope" } })).ok()).toBeTruthy();
      const memberHeaders = await login(request, memberEmail, PASSWORD);
      const pending: { id: string; version: number }[] = await (await request.get(`${API}/policies/mine/pending`, { headers: memberHeaders })).json();
      expect(pending.map((p) => [p.id, p.version])).toEqual([[id, 2]]);
    });
  });
});
