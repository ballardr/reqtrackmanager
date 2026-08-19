import { expect, test } from "@playwright/test";

import { openGroupCard } from "./helpers";

/**
 * End-to-end proof of the "add a project user by email" flow
 * (`Organization.external_user_policy`, `services/invites.py`): a project
 * admin invites someone with no existing account, via the same
 * autocomplete used to add existing org members
 * (`components/UserAutocomplete.tsx`), a real invite email lands in
 * MailHog with a working signup link, and completing that signup grants
 * the project access promised at invite time. See docs/decisions.md's
 * "Self-signup, invites, and SSO" entry.
 *
 * Configures the organisation via API first (setup), then drives the
 * actual invite through the browser's project-admin UI, and verifies the
 * email through MailHog's real HTTP API (the same SMTP relay
 * tests/container/docker-compose.yml wires the backend to) rather than
 * asserting only that the backend attempted a send.
 */

const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "ChangeMe123!";
const apiBaseUrl = "http://localhost:8000";
const mailhogUrl = "http://localhost:8025";

test("project admin invites a brand-new external user by email, and they can sign up and access the project", async ({
  page,
}) => {
  const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  const adminToken = (await adminLoginResp.json()).access_token;

  const suffix = Date.now();
  const orgName = `E2E Invite Org ${suffix}`;
  const orgAdminEmail = `e2e-invite-orgadmin-${suffix}@example.com`;
  const inviteeEmail = `e2e-invitee-${suffix}@example.com`;
  const projectName = `E2E Invite Project ${suffix}`;

  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { name: orgName },
    })
  ).json();
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: { Authorization: `Bearer ${adminToken}` },
    data: { email: orgAdminEmail, display_name: "Invite Org Admin", password: "OrgAdmin123!", role: "org_admin" },
  });
  const orgAdminToken = (
    await (
      await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: orgAdminEmail, password: "OrgAdmin123!" },
      })
    ).json()
  ).access_token;

  await page.request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/advanced-settings`, {
    headers: { Authorization: `Bearer ${orgAdminToken}` },
    data: { external_user_policy: "anyone" },
  });

  const project = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: { Authorization: `Bearer ${orgAdminToken}` },
      data: { organization_id: org.id, name: projectName, summary: "" },
    })
  ).json();

  await page.goto("/login");
  await page.getByLabel("Email").fill(orgAdminEmail);
  await page.getByLabel("Password").fill("OrgAdmin123!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.goto(`/projects/${project.id}/admin`);
  await page.getByRole("tab", { name: "Project groups", exact: true }).click();
  // Groups now render collapsed by default (2026-08 UX audit "Directories
  // at scale") — expand "Project Managers" (the first default group)
  // before its own add-member input is reachable at all.
  await openGroupCard(page, "Project Managers");

  await test.step("invite the new email via the project group's user picker", async () => {
    const picker = page.getByPlaceholder("Type a name to add, or an email to invite…").first();
    await picker.fill(inviteeEmail);
    // The dropdown follows the WAI-ARIA combobox/listbox pattern
    // (`UserAutocomplete.tsx`) — each match, including the invite result,
    // is `role="option"`, not `role="button"`.
    await expect(page.getByRole("option", { name: new RegExp(`Invite ${inviteeEmail}`) })).toBeVisible();
    await page.getByRole("option", { name: new RegExp(`Invite ${inviteeEmail}`) }).click();
    await expect(page.getByText(new RegExp(`invite email was sent to ${inviteeEmail}`))).toBeVisible();
  });

  const inviteUrl = await test.step("find the invite email in MailHog and extract the signup link", async () => {
    let link: string | null = null;
    await expect
      .poll(
        async () => {
          const messages = await (await page.request.get(`${mailhogUrl}/api/v2/messages?limit=50`)).json();
          const match = messages.items.find((m: { To: { Mailbox: string; Domain: string }[] }) =>
            m.To.some((to) => `${to.Mailbox}@${to.Domain}` === inviteeEmail),
          );
          if (!match) return null;
          // MailHog stores the raw quoted-printable-encoded body (the
          // backend's plain send_email sets Content-Transfer-Encoding:
          // quoted-printable) — soft line breaks (`=\r\n`) can split the
          // URL mid-string, and every literal `=` in it is escaped as
          // `=3D`, so both must be undone before the link is regex-matched.
          const decoded: string = (match.Content.Body as string)
            .replace(/=\r\n/g, "")
            .replace(/=([0-9A-F]{2})/g, (_: string, hex: string) => String.fromCharCode(parseInt(hex, 16)));
          const found = decoded.match(/https?:\/\/\S+\/signup\?invite=\S+/);
          link = found ? found[0].trim() : null;
          return link;
        },
        { timeout: 15_000 },
      )
      .not.toBeNull();
    return link as unknown as string;
  });

  await test.step("complete signup via the invite link and confirm project access", async () => {
    const url = new URL(inviteUrl);
    await page.goto(`${url.pathname}${url.search}`);
    await expect(page.getByText("You've been invited")).toBeVisible();
    await page.getByLabel("Display name").fill("Invited Person");
    // The email field is prefilled by nothing server-side — the invite is
    // matched by the email the invitee types, so it must match exactly.
    await page.getByLabel("Email").fill(inviteeEmail);
    await page.getByLabel("Password").fill("InvitedPerson123!");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    const inviteeToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const projectsResp = await page.request.get(`${apiBaseUrl}/api/v1/projects`, {
      headers: { Authorization: `Bearer ${inviteeToken}` },
    });
    const projects = await projectsResp.json();
    expect(projects.some((p: { id: string }) => p.id === project.id)).toBe(true);
  });
});
