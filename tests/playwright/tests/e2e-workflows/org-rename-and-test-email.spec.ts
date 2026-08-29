import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, selectOrgAdminGroup, selectServerManagementGroup } from "./helpers";

/**
 * Job to be done: an org admin can rename their own organisation, and can
 * send a test email to confirm their org's own SMTP override
 * (`Organization.smtp_*`) actually works before relying on it; separately,
 * a server admin can send a test email to confirm the deployment-wide SMTP
 * configuration works. Verifies real delivery through MailHog's HTTP API
 * (the same SMTP relay `tests/container/docker-compose.yml` wires the
 * backend to) rather than only asserting the UI shows a success message —
 * same verification approach as `external-project-invite.spec.ts`.
 *
 * Uses a disposable organisation (created via API, like
 * `server-org-lifecycle.spec.ts`) for the rename/org-SMTP test rather than
 * a shared seed org, since renaming and reconfiguring SMTP are exactly the
 * kind of mutation other specs sharing this suite's single-worker run
 * shouldn't see.
 */

const apiBaseUrl = "http://localhost:8000";
const mailhogUrl = "http://localhost:8025";

type MailhogPart = {
  Headers: Record<string, string[]>;
  Body: string;
  MIME?: { Parts: MailhogPart[] } | null;
};
type MailhogMessage = { To: { Mailbox: string; Domain: string }[]; MIME: { Parts: MailhogPart[] } };

async function mailhogMessageTo(page: import("@playwright/test").Page, toEmail: string): Promise<MailhogMessage | undefined> {
  const messages = await (await page.request.get(`${mailhogUrl}/api/v2/messages?limit=50`)).json();
  return messages.items.find((m: MailhogMessage) => m.To.some((to) => `${to.Mailbox}@${to.Domain}` === toEmail));
}

async function mailhogReceivedMessageTo(page: import("@playwright/test").Page, toEmail: string): Promise<boolean> {
  return (await mailhogMessageTo(page, toEmail)) !== undefined;
}

/** Decodes a quoted-printable body (stdlib `email.message.EmailMessage`'s
 * default transfer encoding for these templates' non-7bit-safe long lines)
 * into UTF-8 text: strips soft line breaks (`=\r\n`/`=\n`), then resolves
 * `=XX` hex escapes byte-by-byte before decoding as UTF-8. */
function decodeQuotedPrintable(input: string): string {
  const withoutSoftBreaks = input.replace(/=\r\n/g, "").replace(/=\n/g, "");
  const bytes: number[] = [];
  for (let i = 0; i < withoutSoftBreaks.length; i++) {
    const ch = withoutSoftBreaks[i];
    if (ch === "=" && /^[0-9A-Fa-f]{2}$/.test(withoutSoftBreaks.slice(i + 1, i + 3))) {
      bytes.push(parseInt(withoutSoftBreaks.slice(i + 1, i + 3), 16));
      i += 2;
    } else {
      bytes.push(ch.charCodeAt(0));
    }
  }
  return Buffer.from(bytes).toString("utf-8");
}

/**
 * Recursively finds the `text/html` MIME part of a captured message (it may
 * be nested inside a `multipart/related` sub-part once an inline logo cid
 * attachment is present — see `services/email.py`) and decodes its body per
 * its own `Content-Transfer-Encoding`, so tests can assert on the actual
 * rendered HTML rather than only on delivery having happened at all.
 */
function mailhogHtmlBody(message: MailhogMessage): string {
  function search(part: MailhogPart): string | undefined {
    const contentType = part.Headers["Content-Type"]?.[0] ?? "";
    if (contentType.includes("text/html")) {
      const encoding = (part.Headers["Content-Transfer-Encoding"]?.[0] ?? "").toLowerCase();
      if (encoding === "base64") return Buffer.from(part.Body, "base64").toString("utf-8");
      if (encoding === "quoted-printable") return decodeQuotedPrintable(part.Body);
      return part.Body;
    }
    for (const sub of part.MIME?.Parts ?? []) {
      const found = search(sub);
      if (found) return found;
    }
    return undefined;
  }
  for (const part of message.MIME.Parts) {
    const found = search(part);
    if (found) return found;
  }
  throw new Error("No text/html MIME part found in captured message");
}

test.describe("organisation rename and test-email actions", () => {
  test("org admin renames their organisation and sends a test email via their own SMTP override", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Rename Org ${suffix}`;
    const renamedName = `E2E Renamed Org ${suffix}`;
    const orgAdminEmail = `e2e-rename-admin-${suffix}@example.com`;
    const testEmailRecipient = `e2e-org-test-email-${suffix}@example.com`;

    const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: "admin@example.com", password: "ChangeMe123!" },
    });
    const adminToken = (await adminLoginResp.json()).access_token;

    const org = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
        headers: { Authorization: `Bearer ${adminToken}` },
        data: { name: orgName },
      })
    ).json();
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { email: orgAdminEmail, display_name: "Org SMTP Test Admin", password: "OrgAdmin123!", role: "org_admin" },
    });

    await page.goto("/login");
    await page.getByLabel("Email").fill(orgAdminEmail);
    await page.getByLabel("Password").fill("OrgAdmin123!");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    await page.goto(`/orgs/${org.id}/admin`);
    await expect(page.getByRole("heading", { name: orgName })).toBeVisible();

    await test.step("rename via the Overview group's action menu and its Rename modal", async () => {
      // Style guide "Pattern: action menu" — rename and export now live
      // behind one kebab trigger instead of an always-visible inline
      // input; selecting "Rename" opens a Modal with the field.
      await page.getByRole("button", { name: "Organisation actions" }).click();
      // See the identical fix (and its full explanation) in
      // org-merge-import.spec.ts: clicking the menuitem before the
      // `Popover`-based menu finishes positioning can silently miss it.
      await expect(page.getByRole("menu", { name: "Organisation actions" })).toBeVisible();
      await page.getByRole("menuitem", { name: "Rename" }).click();
      const dialog = page.getByRole("dialog", { name: "Rename" });
      const nameInput = dialog.getByLabel("Rename", { exact: true });
      await expect(nameInput).toHaveValue(orgName);
      await nameInput.fill(renamedName);
      await Promise.all([
        page.waitForResponse((r) => r.url().includes(`/orgs/${org.id}/name`) && r.request().method() === "PUT"),
        dialog.getByRole("button", { name: "Save" }).click(),
      ]);
      await expect(page.getByRole("heading", { name: renamedName })).toBeVisible();
      await expect(dialog).not.toBeVisible();
    });

    await test.step("the new name survives a reload", async () => {
      await page.reload();
      await expect(page.getByRole("heading", { name: renamedName })).toBeVisible();
    });

    await test.step("send test email is disabled until an SMTP host is configured", async () => {
      // SMTP/test-email lives in the "SMTP & email" card under its own
      // "Email" top-level resource-menu group (2026-08 UX audit's Org
      // Admin restructure, later split further from a combined
      // "Integrations & security" group), open by default there — no
      // section-toggle click needed, just select the group.
      await selectOrgAdminGroup(page, "Email");
      await expect(page.getByRole("button", { name: "Send test email" })).toBeDisabled();
      await expect(page.getByText("Set an SMTP host above first.")).toBeVisible();
    });

    await test.step("configure this organisation's own SMTP override (pointed at the same MailHog the deployment uses)", async () => {
      await page.getByPlaceholder("SMTP host").fill("mailhog");
      await page.getByPlaceholder("SMTP port").fill("1025");
      await page.getByRole("checkbox", { name: "Use TLS" }).uncheck();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/advanced-settings") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save email settings" }).click(),
      ]);
    });

    await test.step("send a test email and confirm it actually arrives via this org's own SMTP override", async () => {
      const recipientInput = page.getByPlaceholder("Recipient email (defaults to your own account)");
      await recipientInput.fill(testEmailRecipient);
      await Promise.all([
        page.waitForResponse((r) => r.url().includes(`/orgs/${org.id}/test-email`) && r.request().method() === "POST"),
        page.getByRole("button", { name: "Send test email" }).click(),
      ]);
      await expect(page.getByText(/Test email sent/)).toBeVisible();

      await expect
        .poll(async () => mailhogReceivedMessageTo(page, testEmailRecipient), { timeout: 15_000 })
        .toBe(true);

      // The email is now real, rendered HTML from the shared branded
      // template (services/email_templates.py), not a bare plain-text
      // string — confirm the structure and this org's own branding
      // resolved into it, not just that something arrived.
      const message = await mailhogMessageTo(page, testEmailRecipient);
      const html = mailhogHtmlBody(message!);
      expect(html).toContain("<!DOCTYPE html>");
      expect(html).toContain("prefers-color-scheme: dark");
      expect(html).toContain(renamedName);
    });
  });

  test("server admin sends a deployment-wide test email", async ({ page }) => {
    const recipient = `e2e-system-test-email-${Date.now()}@example.com`;

    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/management");
    await selectServerManagementGroup(page, "Email");

    await page.getByPlaceholder("Recipient email (defaults to your own account)").fill(recipient);
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/system/test-email") && r.request().method() === "POST"),
      page.getByRole("button", { name: "Send test email" }).click(),
    ]);
    await expect(page.getByText(/Test email sent/)).toBeVisible();

    await expect
      .poll(async () => mailhogReceivedMessageTo(page, recipient), { timeout: 15_000 })
      .toBe(true);

    const message = await mailhogMessageTo(page, recipient);
    const html = mailhogHtmlBody(message!);
    expect(html).toContain("<!DOCTYPE html>");
    expect(html).toContain("deployment-wide SMTP configuration");
  });

  test("an instant notification email includes a one-click unsubscribe link", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Notif Email Org ${suffix}`;
    const personaEmail = `e2e-notif-email-${suffix}@example.com`;

    const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: "admin@example.com", password: "ChangeMe123!" },
    });
    const adminToken = (await adminLoginResp.json()).access_token;

    const org = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
        headers: { Authorization: `Bearer ${adminToken}` },
        data: { name: orgName },
      })
    ).json();
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { email: personaEmail, display_name: "Notif Email Persona", password: "Password123!", role: "member" },
    });

    const personaLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: personaEmail, password: "Password123!" },
    });
    const personaToken = (await personaLoginResp.json()).access_token;

    // A password change fires an instant PASSWORD_CHANGED notification
    // (services/notifications.py::notify) — a security-relevant one that
    // always emails regardless of preference defaults.
    await page.request.post(`${apiBaseUrl}/api/v1/auth/change-password`, {
      headers: { Authorization: `Bearer ${personaToken}` },
      data: { current_password: "Password123!", new_password: "Password456!" },
    });

    await expect
      .poll(async () => mailhogReceivedMessageTo(page, personaEmail), { timeout: 15_000 })
      .toBe(true);

    const message = await mailhogMessageTo(page, personaEmail);
    const html = mailhogHtmlBody(message!);
    expect(html).toContain("Manage your email preferences");
    expect(html).toMatch(/href="[^"]*\/api\/v1\/notifications\/unsubscribe\?token=/);
  });
});
