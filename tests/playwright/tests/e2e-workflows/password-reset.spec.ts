import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import {
  apiHeaders, deleteOrgOnCleanup, installCleanupHook, loginAs, logout, SERVER_ADMIN_LOGIN, selectServerManagementGroup,
} from "./helpers";

installCleanupHook();

/**
 * Job to be done: a person who cannot sign in gets back in without anyone seeing their password, and an
 * administrator can help or force the issue.
 *
 *  1. "Forgot your password?" emails a single-use link; the page clears the secret from the address bar,
 *     the new password works and the old one does not, and the link cannot be used twice.
 *  2. An organisation admin sends a member a reset link from Users (the member receives it; the admin sees
 *     only a confirmation).
 *  3. A server admin forces a credential reset for one organisation from Server Management: the member's
 *     correct password is now refused with the reset message, and the emailed link restores access.
 *
 * Every account and organisation is disposable and uses a unique email, so reruns and other specs are
 * unaffected. The disposable organisation (and with it every member's access) is deleted afterwards.
 */

const API = "http://localhost:8000/api/v1";
const MAILHOG = "http://localhost:8025";
const OLD_PASSWORD = "OldPassw0rd!";
const NEW_PASSWORD = "BrandNewPassw0rd!";
const SECOND_PASSWORD = "AnotherPassw0rd!";

interface MailHogPart {
  Headers?: Record<string, string[]>;
  Body: string;
}

/** Decodes one MIME part according to its own transfer encoding. */
function decodePart(part: MailHogPart): string {
  const encoding = (part.Headers?.["Content-Transfer-Encoding"]?.[0] ?? "").toLowerCase();
  if (encoding === "quoted-printable") {
    return part.Body.replace(/=\r?\n/g, "").replace(/=([0-9A-F]{2})/g, (_: string, hex: string) =>
      String.fromCharCode(parseInt(hex, 16)),
    );
  }
  if (encoding === "base64") return Buffer.from(part.Body.replace(/\s+/g, ""), "base64").toString("utf8");
  return part.Body;
}

/** Every reset link emailed to `toEmail`, oldest first. */
async function resetLinksFor(request: APIRequestContext, toEmail: string): Promise<string[]> {
  const messages = await (await request.get(`${MAILHOG}/api/v2/messages?limit=100`)).json();
  const links: string[] = [];
  for (const m of [...messages.items].reverse()) {
    if (!m.To.some((to: { Mailbox: string; Domain: string }) => `${to.Mailbox}@${to.Domain}` === toEmail)) continue;
    const parts: MailHogPart[] = m.MIME?.Parts?.length ? m.MIME.Parts : [m.Content];
    for (const part of parts) {
      const found = decodePart(part).match(/https?:\/\/\S+\/reset-password#token=[\w-]+/);
      if (found) {
        links.push(found[0]);
        break;
      }
    }
  }
  return links;
}

async function newResetLink(request: APIRequestContext, toEmail: string, alreadySeen: number): Promise<string> {
  let links: string[] = [];
  await expect
    .poll(async () => (links = await resetLinksFor(request, toEmail)).length, { timeout: 20_000 })
    .toBeGreaterThan(alreadySeen);
  return links[links.length - 1];
}

async function tryPassword(page: Page, email: string, password: string): Promise<number> {
  const response = await page.request.post(`${API}/auth/login`, { data: { email, password } });
  return response.status();
}

async function chooseNewPassword(page: Page, link: string, password: string) {
  await page.goto(link);
  await expect(page.getByRole("heading", { name: "Choose a new password" })).toBeVisible();
  // The secret leaves the address bar as soon as the page has read it.
  await expect.poll(() => new URL(page.url()).hash).toBe("");
  await page.getByLabel(/^New password/).fill(password);
  await page.getByLabel(/^Confirm new password/).fill(password);
  await page.getByRole("button", { name: "Set new password" }).click();
}

test("a person resets a forgotten password, an org admin sends a link, and a server admin forces a reset", async ({ page, request }) => {
  const suffix = Date.now();
  const member = { email: `e2e-reset-member-${suffix}@example.com`, name: `E2E Reset Member ${suffix}` };
  const orgAdmin = { email: `e2e-reset-admin-${suffix}@example.com`, name: `E2E Reset Admin ${suffix}`, password: "OrgAdmin123!" };

  const adminHeaders = await apiHeaders(request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  const org = await (await request.post(`${API}/orgs`, { headers: adminHeaders, data: { name: `E2E Reset Org ${suffix}` } })).json();
  deleteOrgOnCleanup({ id: org.id });
  for (const [person, password, role] of [
    [orgAdmin, orgAdmin.password, "org_admin"],
    [member, OLD_PASSWORD, "member"],
  ] as const) {
    const created = await request.post(`${API}/orgs/${org.id}/users`, {
      headers: adminHeaders,
      data: { email: person.email, display_name: person.name, password, role },
    });
    expect(created.status(), `create ${person.email}`).toBe(201);
  }

  await test.step("forgot password: a link arrives, sets a new password once, and the old one stops working", async () => {
    await page.goto("/login");
    await page.getByRole("link", { name: "Forgot your password?" }).click();
    await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible();
    await page.getByLabel(/^Email/).fill(member.email);
    await page.getByRole("button", { name: "Send reset link" }).click();
    // The same words appear whether or not the address has an account.
    await expect(page.getByText(/a reset link is on its way/)).toBeVisible();

    const link = await newResetLink(request, member.email, 0);
    expect(new URL(link).hash, "the secret travels in the fragment, never the query").toMatch(/^#token=/);
    await chooseNewPassword(page, link, NEW_PASSWORD);
    await expect(page.getByText("Your password has been changed")).toBeVisible();

    expect(await tryPassword(page, member.email, OLD_PASSWORD)).toBe(401);
    expect(await tryPassword(page, member.email, NEW_PASSWORD)).toBe(200);

    // The link is spent: opening it again is refused with a way to ask for another.
    await chooseNewPassword(page, link, SECOND_PASSWORD);
    await expect(page.getByRole("alert")).toContainText("invalid or has expired");
    await expect(page.getByRole("link", { name: "Request a new link" })).toBeVisible();
    expect(await tryPassword(page, member.email, SECOND_PASSWORD)).toBe(401);
  });

  await test.step("an organisation admin sends a member a reset link from Users", async () => {
    await loginAs(page, orgAdmin.email, orgAdmin.password);
    await page.goto(`/orgs/${org.id}/admin/users`);
    await page.getByRole("button", { name: `${member.name}'s actions` }).click();
    await page.getByRole("menuitem", { name: "Send password reset link" }).click();
    const dialog = page.getByRole("dialog", { name: `Send a password reset link to ${member.name}?` });
    await expect(dialog).toContainText("you will not see the link");
    await dialog.getByRole("button", { name: "Send link" }).click();
    await expect(page.getByText(`Password reset link sent to ${member.name}`)).toBeVisible();
    await logout(page);

    const link = await newResetLink(request, member.email, 1);
    await chooseNewPassword(page, link, SECOND_PASSWORD);
    await expect(page.getByText("Your password has been changed")).toBeVisible();
    expect(await tryPassword(page, member.email, SECOND_PASSWORD)).toBe(200);
  });

  await test.step("a server admin forces a reset for the organisation: the password is refused until a new one is chosen", async () => {
    await loginAs(page, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
    await page.goto("/server/management");
    await selectServerManagementGroup(page, "Access review");
    await page.getByRole("button", { name: "Force a credential reset…" }).click();
    const modal = page.getByRole("dialog", { name: "Force a credential reset" });
    await modal.getByLabel("Who").selectOption({ label: "One organisation" });
    await modal.getByLabel("Organisation").selectOption({ label: org.name });
    await modal.getByRole("button", { name: "Force reset…" }).click();
    const confirm = page.getByRole("dialog", { name: "Force this credential reset?" });
    await expect(confirm.getByRole("button", { name: "Force reset" })).toBeDisabled();
    await confirm.getByLabel('Type "RESET" to confirm').fill("RESET");
    await confirm.getByRole("button", { name: "Force reset" }).click();
    await expect(page.getByText(/Credential reset applied to 2 accounts/)).toBeVisible();

    // The correct password is now refused, with the reason and the way out.
    const refused = await page.request.post(`${API}/auth/login`, { data: { email: member.email, password: SECOND_PASSWORD } });
    expect(refused.status()).toBe(403);
    await page.goto("/login");
    await page.getByLabel("Email").fill(member.email);
    await page.getByLabel("Password").fill(SECOND_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText(/must be reset before you can sign in/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Forgot your password?" })).toBeVisible();

    const link = await newResetLink(request, member.email, 2);
    await chooseNewPassword(page, link, NEW_PASSWORD);
    await expect(page.getByText("Your password has been changed")).toBeVisible();
    expect(await tryPassword(page, member.email, NEW_PASSWORD)).toBe(200);
  });
});
