import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS } from "./helpers";

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

async function mailhogReceivedMessageTo(page: import("@playwright/test").Page, toEmail: string): Promise<boolean> {
  const messages = await (await page.request.get(`${mailhogUrl}/api/v2/messages?limit=50`)).json();
  return messages.items.some((m: { To: { Mailbox: string; Domain: string }[] }) =>
    m.To.some((to) => `${to.Mailbox}@${to.Domain}` === toEmail),
  );
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

    await test.step("rename via the inline control next to the organisation's name", async () => {
      const nameInput = page.getByLabel("Rename", { exact: true });
      await expect(nameInput).toHaveValue(orgName);
      await nameInput.fill(renamedName);
      await Promise.all([
        page.waitForResponse((r) => r.url().includes(`/orgs/${org.id}/name`) && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Rename" }).click(),
      ]);
      await expect(page.getByRole("heading", { name: renamedName })).toBeVisible();
    });

    await test.step("the new name survives a reload", async () => {
      await page.reload();
      await expect(page.getByRole("heading", { name: renamedName })).toBeVisible();
    });

    await test.step("send test email is disabled until an SMTP host is configured", async () => {
      await page.getByRole("button", { name: "Advanced settings section" }).click();
      await expect(page.getByRole("button", { name: "Send test email" })).toBeDisabled();
      await expect(page.getByText("Set an SMTP host above first.")).toBeVisible();
    });

    await test.step("configure this organisation's own SMTP override (pointed at the same MailHog the deployment uses)", async () => {
      await page.getByPlaceholder("SMTP host").fill("mailhog");
      await page.getByPlaceholder("SMTP port").fill("1025");
      await page.getByRole("checkbox", { name: "Use TLS" }).uncheck();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/advanced-settings") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save advanced settings" }).click(),
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
    });
  });

  test("server admin sends a deployment-wide test email", async ({ page }) => {
    const recipient = `e2e-system-test-email-${Date.now()}@example.com`;

    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/management");
    await page.getByRole("button", { name: "Email", exact: true }).click();

    await page.getByPlaceholder("Recipient email (defaults to your own account)").fill(recipient);
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/system/test-email") && r.request().method() === "POST"),
      page.getByRole("button", { name: "Send test email" }).click(),
    ]);
    await expect(page.getByText(/Test email sent/)).toBeVisible();

    await expect
      .poll(async () => mailhogReceivedMessageTo(page, recipient), { timeout: 15_000 })
      .toBe(true);
  });
});
