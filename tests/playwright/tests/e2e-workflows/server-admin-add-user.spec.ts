import { expect, test, type Page } from "@playwright/test";

import {
  apiHeaders, deleteOrgOnCleanup, installCleanupHook, loginAs, onCleanup, PASSWORD, PERSONAS, SERVER_ADMIN_LOGIN,
} from "./helpers";

const API = "http://localhost:8000/api/v1";
const MAILHOG = "http://localhost:8025";

installCleanupHook();

/**
 * Job to be done: a server admin adds a person from Server Management → Users, without first
 * creating an organisation workaround: with a password and no organisation, with a password inside
 * an organisation, or by emailing an invite that the person accepts and then logs in with.
 *
 * Every account uses a unique email, and the organisation is disposable, so reruns and other specs
 * are unaffected. Created accounts are deactivated afterwards (an account with no organisation can be).
 */

async function inviteLinkFor(page: Page, toEmail: string): Promise<string> {
  let link: string | null = null;
  await expect
    .poll(async () => {
      const messages = await (await page.request.get(`${MAILHOG}/api/v2/messages?limit=50`)).json();
      for (const m of messages.items) {
        if (!m.To.some((to: { Mailbox: string; Domain: string }) => `${to.Mailbox}@${to.Domain}` === toEmail)) continue;
        const decoded = m.Content.Body.replace(/=\r\n/g, "").replace(/=([0-9A-F]{2})/g, (_: string, hex: string) =>
          String.fromCharCode(parseInt(hex, 16)));
        const found = decoded.match(/https?:\/\/\S+\/signup\?invite=\S+/);
        if (found) link = found[0].trim();
      }
      return link;
    }, { timeout: 15_000 })
    .not.toBeNull();
  return link as unknown as string;
}

test("a server admin adds users with a password (with and without an organisation) and by invite (into an organisation, or into none)", async ({ page, request, browser }) => {
  const suffix = Date.now();
  const orgName = `E2E Add User Org ${suffix}`;
  const solo = { email: `e2e-add-solo-${suffix}@example.com`, name: `E2E Solo ${suffix}`, password: "SoloPass123!" };
  const member = { email: `e2e-add-member-${suffix}@example.com`, name: `E2E Member ${suffix}`, password: "MemberPass123!" };
  const invitee = { email: `e2e-add-invitee-${suffix}@example.com`, name: `E2E Invitee ${suffix}`, password: "InviteePass123!" };
  const loner = { email: `e2e-add-loner-${suffix}@example.com`, name: `E2E Loner ${suffix}`, password: "LonerPass123!" };

  // Registered first so it runs last: the accounts are only deactivatable once the disposable org is gone.
  onCleanup(async (cleanupRequest) => {
    const headers = await apiHeaders(cleanupRequest, PERSONAS.serverAdmin.email);
    for (const person of [solo, member, invitee, loner]) {
      const found: { user_id: string }[] = await (
        await cleanupRequest.get(`${API}/system/users?search=${encodeURIComponent(person.email)}`, { headers })
      ).json();
      for (const u of found) await cleanupRequest.post(`${API}/system/users/${u.user_id}/status`, { headers, data: { action: "deactivate" } });
    }
  });
  const adminHeaders = await apiHeaders(request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  const org = await (await request.post(`${API}/orgs`, { headers: adminHeaders, data: { name: orgName } })).json();
  deleteOrgOnCleanup({ id: org.id });

  await loginAs(page, PERSONAS.serverAdmin.email);
  await page.goto("/server/management");
  await page.getByPlaceholder("Search by name or email").waitFor();

  /** Opens "Add user ▾" and chooses one of its two items, which opens that dialog. */
  async function openDialog(item: "New user" | "Invite user") {
    await page.getByRole("button", { name: "Add user" }).click();
    await page.getByRole("menuitem", { name: item }).click();
    return page.getByRole("dialog", { name: item });
  }

  await test.step("with a password and no organisation: created, listed, can log in", async () => {
    const dialog = await openDialog("New user");
    await expect(dialog.getByRole("button", { name: "Create" })).toBeDisabled();
    await dialog.getByLabel("Email").fill(solo.email);
    await dialog.getByLabel("Name", { exact: true }).fill(solo.name);
    await dialog.getByLabel("Password", { exact: true }).fill(solo.password);
    // No organisation chosen, so there is no role to pick.
    await expect(dialog.getByRole("combobox", { name: "Role" })).toHaveCount(0);
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByText(`Created ${solo.email}`)).toBeVisible();
    await expect(page.getByRole("row", { name: new RegExp(solo.email) })).toBeVisible();
    const login = await request.post(`${API}/auth/login`, { data: { email: solo.email, password: solo.password } });
    expect(login.ok()).toBeTruthy();
  });

  await test.step("a short password is refused with a message and the dialog stays open", async () => {
    const dialog = await openDialog("New user");
    await dialog.getByLabel("Email").fill(`e2e-add-weak-${suffix}@example.com`);
    await dialog.getByLabel("Name", { exact: true }).fill("Weak");
    await dialog.getByLabel("Password", { exact: true }).fill("short");
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(dialog.getByText(/at least 8 characters/i).first()).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
  });

  await test.step("with a password inside an organisation: created as a member of that organisation", async () => {
    const dialog = await openDialog("New user");
    await dialog.getByLabel("Email").fill(member.email);
    await dialog.getByLabel("Name", { exact: true }).fill(member.name);
    await dialog.getByLabel("Password", { exact: true }).fill(member.password);
    await dialog.getByRole("combobox", { name: "Organisation" }).selectOption({ label: orgName });
    await expect(dialog.getByRole("combobox", { name: "Role" })).toHaveValue("member");
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByText(`Created ${member.email}`)).toBeVisible();
    await expect(page.getByRole("row", { name: new RegExp(member.email) })).toContainText(orgName);
    const login = await request.post(`${API}/auth/login`, { data: { email: member.email, password: member.password } });
    expect(login.ok()).toBeTruthy();
  });

  await test.step("an invite asks for no password and, in an organisation, names it", async () => {
    const dialog = await openDialog("Invite user");
    await expect(dialog.getByLabel("Password", { exact: true })).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Send invite" })).toBeDisabled();
    await dialog.getByLabel("Email").fill(invitee.email);
    await dialog.getByRole("combobox", { name: "Organisation" }).selectOption({ label: orgName });
    await dialog.getByRole("button", { name: "Send invite" }).click();
    await expect(page.getByText(`Invite sent to ${invitee.email}`)).toBeVisible();
  });

  await test.step("an invite with no organisation is sent too", async () => {
    const dialog = await openDialog("Invite user");
    await dialog.getByLabel("Email").fill(loner.email);
    await dialog.getByRole("button", { name: "Send invite" }).click();
    await expect(page.getByText(`Invite sent to ${loner.email}`)).toBeVisible();
  });

  for (const person of [invitee, loner]) {
    await test.step(`${person.email} accepts the emailed link and then logs in`, async () => {
      const url = new URL(await inviteLinkFor(page, person.email));
      const context = await browser.newContext();
      try {
        const inviteePage = await context.newPage();
        await inviteePage.goto(`${url.pathname}${url.search}`);
        await expect(inviteePage.getByText("You've been invited")).toBeVisible();
        await inviteePage.getByLabel("Display name").fill(person.name);
        await inviteePage.getByLabel("Email").fill(person.email);
        await inviteePage.getByLabel("Password").fill(person.password);
        await inviteePage.getByRole("button", { name: "Create account" }).click();
        await expect(inviteePage.getByRole("button", { name: "Sign out" })).toBeVisible();
      } finally {
        await context.close();
      }
      const login = await request.post(`${API}/auth/login`, { data: { email: person.email, password: person.password } });
      expect(login.ok()).toBeTruthy();
    });
  }
});

test("an organisation admin cannot add users from Server Management", async ({ request }) => {
  const headers = await apiHeaders(request, PERSONAS.orgAdminAlphaBeta.email);
  const resp = await request.post(`${API}/system/users`, {
    headers, data: { mode: "password", email: `e2e-forbidden-${Date.now()}@example.com`, display_name: "No", password: PASSWORD },
  });
  expect(resp.status()).toBe(403);
});
