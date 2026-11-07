import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import {
  apiHeaders, ensureExpanded, installCleanupHook, loginAs, logout, onCleanup, ORG_NAMES, PERSONAS, selectOrgAdminGroup,
  selectServerManagementGroup,
} from "./helpers";

const API = "http://localhost:8000/api/v1";
const ORG_SLUG = "e2e-login-brand-org";

/** The api prefix for an organisation's own messages, or the platform's. */
const scopeUrl = (organizationId: string | null) => (organizationId ? `${API}/orgs/${organizationId}/announcements` : `${API}/system/announcements`);

/**
 * Registers cleanup that deletes every message whose title contains `marker` in the given scope, so a failed run
 * leaves no banner or login-page message behind for another spec. Idempotent.
 */
function deleteMessagesOnCleanup(marker: string, organizationId: string | null, email: string, password?: string): void {
  onCleanup(async (request: APIRequestContext) => {
    const headers = await apiHeaders(request, email, password);
    const listed = await request.get(scopeUrl(organizationId), { headers });
    if (!listed.ok()) return;
    for (const item of (await listed.json()).items as { id: string; title: string }[]) {
      if (item.title.includes(marker)) await request.delete(`${scopeUrl(organizationId)}/${item.id}`, { headers });
    }
  });
}

async function fillAndSave(page: Page, fields: { title: string; body: string; login?: boolean }) {
  await page.getByRole("button", { name: "New message" }).click();
  const dialog = page.getByRole("dialog", { name: "New message" });
  await dialog.getByRole("textbox", { name: /^Title/ }).fill(fields.title);
  await dialog.getByRole("textbox", { name: "Message" }).fill(fields.body);
  if (fields.login) await dialog.getByRole("checkbox", { name: /Show on the login pages/ }).check();
  return dialog;
}

/**
 * Job to be done: a server administrator announces something to everyone (shown on the login page before sign-in
 * and as a dismissible banner after), and an organisation administrator does the same for their own organisation
 * without it reaching anyone else; either may send a message once as a notification.
 *
 * Both tests delete the messages they create in cleanup (the platform one is visible to every other spec while it
 * exists, so it is created and removed within the test).
 */
test.describe("announcements", () => {
  installCleanupHook();

  test("a platform message shows on the login page and as a dismissible banner", async ({ page }) => {
    test.setTimeout(90_000);
    const marker = `E2E Platform Notice ${Date.now()}`;
    deleteMessagesOnCleanup(marker, null, PERSONAS.serverAdmin.email);

    await test.step("the server administrator writes a message flagged for the login pages", async () => {
      await loginAs(page, PERSONAS.serverAdmin.email);
      await page.goto("/server/management");
      await selectServerManagementGroup(page, "Messages");
      await ensureExpanded(page, "Messages");
      const dialog = await fillAndSave(page, { title: marker, body: "Maintenance tonight.", login: true });
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Message created.")).toBeVisible();
      await expect(page.getByRole("table", { name: "Messages" }).getByText(marker)).toBeVisible();
    });

    await test.step("the login page shows it before anyone signs in", async () => {
      await logout(page);
      await expect(page.getByRole("region", { name: "Announcements" }).getByText(marker)).toBeVisible();
      await expect(page.getByText("Maintenance tonight.")).toBeVisible();
    });

    await test.step("a member sees it as a banner after signing in, and dismissing hides it", async () => {
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      const banner = page.getByRole("region", { name: "Announcements" });
      await expect(banner.getByText(marker)).toBeVisible();
      // The banner is pinned above the top bar, and stays there when the page is scrolled.
      const bannerBox = (await banner.boundingBox())!;
      const headerBox = (await page.locator("header.app-header").boundingBox())!;
      expect(bannerBox.y).toBeLessThan(headerBox.y);
      expect(bannerBox.y + bannerBox.height).toBeLessThanOrEqual(headerBox.y + 1);
      await page.screenshot({ path: "test-results/announcement-banner.png" });
      await banner.getByRole("button", { name: `Dismiss ${marker}` }).click();
      await expect(page.getByText(marker)).toHaveCount(0);
      await page.reload();
      await expect(page.getByText(marker)).toHaveCount(0);
    });
  });

  test("an organisation message shows only on its own login page and can be sent as a notification", async ({ page }) => {
    test.setTimeout(90_000);
    const marker = `E2E Org Notice ${Date.now()}`;
    const adminEmail = PERSONAS.orgAdminAlphaBeta.email;
    await loginAs(page, adminEmail);
    const headers = await apiHeaders(page.request, adminEmail);
    const orgs: { id: string; name: string; slug: string | null }[] = await (await page.request.get(`${API}/orgs?mine=true`, { headers })).json();
    const alpha = orgs.find((o) => o.name === ORG_NAMES.alpha)!;
    if (!alpha.slug) {
      const set = await page.request.put(`${API}/orgs/${alpha.id}/sso-config`, { headers, data: { slug: ORG_SLUG, sso_enabled: false, sso_only: false } });
      expect(set.ok()).toBeTruthy();
    }
    const slug = alpha.slug ?? ORG_SLUG;
    deleteMessagesOnCleanup(marker, alpha.id, adminEmail);

    await test.step("a web address is refused with the server's reason shown in the dialog", async () => {
      await page.goto(`/orgs/${alpha.id}/admin`);
      await selectOrgAdminGroup(page, "Messages");
      await ensureExpanded(page, "Messages");
      const dialog = await fillAndSave(page, { title: marker, body: "See https://example.com now" });
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(dialog.getByText("An organisation message cannot contain a web address.")).toBeVisible();
    });

    await test.step("a plain message is created, flagged for the login page", async () => {
      const dialog = page.getByRole("dialog", { name: "New message" });
      await dialog.getByRole("textbox", { name: "Message" }).fill("Badges are collected at reception.");
      await dialog.getByRole("checkbox", { name: /Show on the login pages/ }).check();
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Message created.")).toBeVisible();
    });

    await test.step("it shows on the organisation's login page but not on the plain one", async () => {
      await logout(page);
      await page.goto(`/login/${slug}`);
      await expect(page.getByRole("region", { name: "Announcements" }).getByText(marker)).toBeVisible();
      await page.goto("/login");
      await expect(page.getByText(marker)).toHaveCount(0);
    });

    await test.step("sending it as a notification reaches a member once", async () => {
      await loginAs(page, adminEmail);
      await page.goto(`/orgs/${alpha.id}/admin`);
      await selectOrgAdminGroup(page, "Messages");
      await ensureExpanded(page, "Messages");
      await page.getByRole("button", { name: `Send ${marker} as a notification` }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Send" }).click();
      await expect(page.getByText("Notification sent.")).toBeVisible();
      await expect(page.getByRole("button", { name: `Send ${marker} as a notification` })).toHaveCount(0);
      await expect(page.getByText(/^Sent to \d+ (person|people) on/)).toBeVisible();

      const memberHeaders = await apiHeaders(page.request, PERSONAS.stakeholderAlpha.email);
      const notifications: { type: string; title: string }[] = await (await page.request.get(`${API}/notifications`, { headers: memberHeaders })).json();
      expect(notifications.filter((n) => n.type === "system_announcement" && n.title === marker)).toHaveLength(1);
      const sentAgain = await page.request.post(`${scopeUrl(alpha.id)}/${await idOf(page.request, alpha.id, marker, headers)}/notify`, { headers });
      expect(sentAgain.status()).toBe(409);
    });
  });
});

async function idOf(request: APIRequestContext, organizationId: string, title: string, headers: Record<string, string>): Promise<string> {
  const items: { id: string; title: string }[] = (await (await request.get(scopeUrl(organizationId), { headers })).json()).items;
  return items.find((i) => i.title === title)!.id;
}

