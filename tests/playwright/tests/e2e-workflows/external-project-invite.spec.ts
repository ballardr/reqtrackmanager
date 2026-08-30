import { expect, test, type Page } from "@playwright/test";

import { ensureExpanded, openProjectGroupPanel, selectProjectAdminGroup } from "./helpers";

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
 * Also covers Phase 3 ("resend a pending invite", docs/decisions.md): the
 * invite shows up in the new pending-invites list
 * (`components/PendingInvitesSection.tsx`) with "Pending" status, and
 * clicking Resend retriggers a fresh email — verified the same way, via
 * MailHog's real HTTP API, rather than asserting only that the backend
 * attempted a send.
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

/** Creates a fresh org (with an org admin and "anyone" external-user
 * policy) and one project inside it, via the API — shared setup for both
 * tests below, each of which needs its own isolated org/project so their
 * dynamically-named invites can't collide. */
async function setupInviteOrgAndProject(page: Page, adminToken: string, label: string) {
  const suffix = `${label}-${Date.now()}`;
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { name: `E2E Invite Org ${suffix}` },
    })
  ).json();
  const orgAdminEmail = `e2e-invite-orgadmin-${suffix}@example.com`;
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
      data: { organization_id: org.id, name: `E2E Invite Project ${suffix}`, summary: "" },
    })
  ).json();

  return { org, orgAdminEmail, orgAdminToken, project };
}

/** MailHog stores the raw quoted-printable-encoded body (the backend's
 * plain send_email sets Content-Transfer-Encoding: quoted-printable) —
 * soft line breaks (`=\r\n`) can split the URL mid-string, and every
 * literal `=` in it is escaped as `=3D`, so both must be undone before
 * the link is regex-matched. Returns every signup link found across all
 * messages addressed to `toEmail` (newest last), so callers can tell a
 * resend apart from the original by link count/value. */
async function extractInviteLinksFromMailHog(page: Page, toEmail: string): Promise<string[]> {
  const messages = await (await page.request.get(`${mailhogUrl}/api/v2/messages?limit=50`)).json();
  const matches = messages.items.filter((m: { To: { Mailbox: string; Domain: string }[] }) =>
    m.To.some((to) => `${to.Mailbox}@${to.Domain}` === toEmail),
  );
  return matches
    .map((m: { Content: { Body: string } }) => {
      const decoded = m.Content.Body.replace(/=\r\n/g, "").replace(/=([0-9A-F]{2})/g, (_: string, hex: string) =>
        String.fromCharCode(parseInt(hex, 16)),
      );
      const found = decoded.match(/https?:\/\/\S+\/signup\?invite=\S+/);
      return found ? found[0].trim() : null;
    })
    .filter((link: string | null): link is string => link !== null);
}

test("project admin invites a brand-new external user by email, and they can sign up and access the project", async ({
  page,
}) => {
  const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  const adminToken = (await adminLoginResp.json()).access_token;

  const { orgAdminEmail, project } = await setupInviteOrgAndProject(page, adminToken, "signup");
  const inviteeEmail = `e2e-invitee-${Date.now()}@example.com`;

  await page.goto("/login");
  await page.getByLabel("Email").fill(orgAdminEmail);
  await page.getByLabel("Password").fill("OrgAdmin123!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.goto(`/projects/${project.id}/admin`);
  await selectProjectAdminGroup(page, "Project groups");
  // Each group row opens a `SidePanel` (Phase 5, docs/decisions.md) —
  // "Project Managers" is the first default group.
  const invitePanel = await openProjectGroupPanel(page, "Project Managers");

  await test.step("invite the new email via the project group's user picker", async () => {
    const picker = invitePanel.getByPlaceholder("Type a name to add, or an email to invite…");
    await picker.fill(inviteeEmail);
    // The dropdown follows the WAI-ARIA combobox/listbox pattern
    // (`UserAutocomplete.tsx`) — each match, including the invite result,
    // is `role="option"`, not `role="button"`.
    await expect(page.getByRole("option", { name: new RegExp(`Invite ${inviteeEmail}`) })).toBeVisible();
    await page.getByRole("option", { name: new RegExp(`Invite ${inviteeEmail}`) }).click();
    await expect(page.getByText(new RegExp(`invite email was sent to ${inviteeEmail}`))).toBeVisible();
    await page.getByRole("button", { name: "Close" }).click();
  });

  const inviteUrl = await test.step("find the invite email in MailHog and extract the signup link", async () => {
    let link: string | null = null;
    await expect
      .poll(
        async () => {
          const links = await extractInviteLinksFromMailHog(page, inviteeEmail);
          link = links[0] ?? null;
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

test("project admin sees a pending invite listed and can resend it, retriggering a fresh email", async ({ page }) => {
  const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  const adminToken = (await adminLoginResp.json()).access_token;

  const { orgAdminEmail, project } = await setupInviteOrgAndProject(page, adminToken, "resend");
  const inviteeEmail = `e2e-resend-invitee-${Date.now()}@example.com`;

  await page.goto("/login");
  await page.getByLabel("Email").fill(orgAdminEmail);
  await page.getByLabel("Password").fill("OrgAdmin123!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.goto(`/projects/${project.id}/admin`);
  await selectProjectAdminGroup(page, "Project groups");
  const invitePanel = await openProjectGroupPanel(page, "Project Managers");

  await test.step("invite the new email via the project group's user picker", async () => {
    const picker = invitePanel.getByPlaceholder("Type a name to add, or an email to invite…");
    await picker.fill(inviteeEmail);
    await expect(page.getByRole("option", { name: new RegExp(`Invite ${inviteeEmail}`) })).toBeVisible();
    await page.getByRole("option", { name: new RegExp(`Invite ${inviteeEmail}`) }).click();
    await expect(page.getByText(new RegExp(`invite email was sent to ${inviteeEmail}`))).toBeVisible();
    await page.getByRole("button", { name: "Close" }).click();
  });

  const firstLink = await test.step("wait for the original invite email to land in MailHog", async () => {
    let link: string | null = null;
    await expect
      .poll(
        async () => {
          const links = await extractInviteLinksFromMailHog(page, inviteeEmail);
          link = links[0] ?? null;
          return link;
        },
        { timeout: 15_000 },
      )
      .not.toBeNull();
    return link as unknown as string;
  });

  await test.step("see the invite listed as Pending", async () => {
    await page.reload();
    // Pending invites moved onto the new "Members" section (Phase 5,
    // docs/decisions.md) — the old combined "Project groups" tab no
    // longer has it.
    await selectProjectAdminGroup(page, "Members");
    await ensureExpanded(page, "Pending invites");
    const row = page.getByRole("row", { name: new RegExp(inviteeEmail) });
    await expect(row).toBeVisible();
    await expect(row.getByText("Pending")).toBeVisible();

    await test.step("resend it and confirm feedback + a second, different email fires", async () => {
      await row.getByRole("button", { name: `Resend invite to ${inviteeEmail}` }).click();
      await expect(page.getByText(`Invite resent to ${inviteeEmail}.`)).toBeVisible();

      await expect
        .poll(
          async () => (await extractInviteLinksFromMailHog(page, inviteeEmail)).length,
          { timeout: 15_000 },
        )
        .toBeGreaterThanOrEqual(2);
      const links = await extractInviteLinksFromMailHog(page, inviteeEmail);
      // A rotated token — the resend must not just re-deliver the original
      // link. MailHog's own ordering isn't asserted on (newest-first vs.
      // -last isn't a documented contract), so this checks the *set* of
      // links contains something other than the original rather than
      // indexing into a specific position.
      expect(links.some((link) => link !== firstLink)).toBe(true);
    });
  });
});
