import { expect, test, type Page } from "@playwright/test";

import { ensureExpanded } from "./helpers";

/**
 * End-to-end proof of Phase A (follow-up UX batch, docs/decisions.md):
 * Org Admin gets its own "Invite user" entry point — previously the
 * token-link invite flow (`services/invites.py`) was only reachable from
 * inside a project. An org admin invites someone by email (no password, no
 * name — the invitee sets those at signup), sees the invite listed as
 * "Pending" in the same Users table real users appear in, and can resend
 * it, retriggering a fresh email — the same MailHog-verified pattern
 * `external-project-invite.spec.ts` already established for the
 * project-level equivalent.
 *
 * Also covers the new `org_role` `FilterField` (`GET /orgs/{id}/users`'s
 * `org_role` param already existed server-side but had no frontend control
 * wired up to it before this phase).
 *
 * Each test creates its own fresh organisation (with its own admin), the
 * same isolation `external-project-invite.spec.ts` uses — an org-only
 * invite must never land in one of the shared seeded orgs (Alpha/Beta/
 * Gamma), since `user-access-panel.spec.ts`'s Users-table sort test reads
 * every visible row and would be corrupted by an unsorted invited row
 * mixed into a different org's directory.
 */

const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "ChangeMe123!";
const apiBaseUrl = "http://localhost:8000";
const mailhogUrl = "http://localhost:8025";

async function setupOrgAndAdmin(page: Page, adminToken: string, label: string) {
  const suffix = `${label}-${Date.now()}`;
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { name: `E2E Org Invite ${suffix}` },
    })
  ).json();
  const orgAdminEmail = `e2e-org-invite-admin-${suffix}@example.com`;
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: { Authorization: `Bearer ${adminToken}` },
    data: { email: orgAdminEmail, display_name: "Org Invite Admin", password: "OrgAdmin123!", role: "org_admin" },
  });
  return { org, orgAdminEmail };
}

/** Same MailHog decode/extract helper `external-project-invite.spec.ts`
 * uses — kept local rather than shared since these are the only two spec
 * files that need it, and duplicating a small, stable helper avoids adding
 * cross-file coupling for a two-caller utility. */
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

test("org admin invites a user org-level, and they can sign up and get org access (not project access)", async ({ page }) => {
  const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  const adminToken = (await adminLoginResp.json()).access_token;
  const { orgAdminEmail } = await setupOrgAndAdmin(page, adminToken, "signup");
  const inviteeEmail = `e2e-org-invitee-${Date.now()}@example.com`;

  await page.goto("/login");
  await page.getByLabel("Email").fill(orgAdminEmail);
  await page.getByLabel("Password").fill("OrgAdmin123!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.goto("/orgs");
  await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
  await page.getByRole("link", { name: "Users" }).click();
  await ensureExpanded(page, "Organisation users");

  await test.step("invite the new email via the org-level 'Invite user' button", async () => {
    // Distinct from "New user" (immediate password account) — the whole
    // point of this phase.
    await page.getByRole("button", { name: "Invite user" }).click();
    const dialog = page.getByRole("dialog", { name: "Invite user" });
    await expect(dialog.getByLabel("Password")).toHaveCount(0);
    await dialog.getByLabel("Email").fill(inviteeEmail);
    await dialog.getByRole("button", { name: "Send invite" }).click();
    await expect(page.getByText("Invite sent")).toBeVisible();
  });

  await test.step("the invite shows up as Pending in the same Users table real users appear in", async () => {
    const row = page.getByRole("row", { name: new RegExp(inviteeEmail) });
    await expect(row).toBeVisible();
    await expect(row.getByText("Pending")).toBeVisible();
    await expect(row.getByText(/Invited by/)).toBeVisible();
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

  await test.step("complete signup via the invite link and confirm org access but no project access", async () => {
    const url = new URL(inviteUrl);
    await page.goto(`${url.pathname}${url.search}`);
    await expect(page.getByText("You've been invited")).toBeVisible();
    await page.getByLabel("Display name").fill("Org Invitee");
    // The email field is prefilled by nothing server-side — the invite is
    // matched by the email the invitee types, so it must match exactly.
    await page.getByLabel("Email").fill(inviteeEmail);
    await page.getByLabel("Password").fill("OrgInvitee123!");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    const inviteeToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const projectsResp = await page.request.get(`${apiBaseUrl}/api/v1/projects?archived=false`, {
      headers: { Authorization: `Bearer ${inviteeToken}` },
    });
    // Org-only invite — no project role granted, so the projects list is
    // empty for this brand-new account.
    expect(await projectsResp.json()).toEqual([]);
  });
});

test("org admin sees a pending org-level invite listed and can resend it, retriggering a fresh email", async ({ page }) => {
  const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  const adminToken = (await adminLoginResp.json()).access_token;
  const { orgAdminEmail } = await setupOrgAndAdmin(page, adminToken, "resend");
  const inviteeEmail = `e2e-org-resend-invitee-${Date.now()}@example.com`;

  await page.goto("/login");
  await page.getByLabel("Email").fill(orgAdminEmail);
  await page.getByLabel("Password").fill("OrgAdmin123!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.goto("/orgs");
  await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
  await page.getByRole("link", { name: "Users" }).click();
  await ensureExpanded(page, "Organisation users");

  await test.step("invite the new email via the org-level 'Invite user' button", async () => {
    await page.getByRole("button", { name: "Invite user" }).click();
    const dialog = page.getByRole("dialog", { name: "Invite user" });
    await dialog.getByLabel("Email").fill(inviteeEmail);
    await dialog.getByRole("button", { name: "Send invite" }).click();
    await expect(page.getByText("Invite sent")).toBeVisible();
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

  await test.step("resend it and confirm feedback + a second, different email fires", async () => {
    const row = page.getByRole("row", { name: new RegExp(inviteeEmail) });
    await expect(row.getByText("Pending")).toBeVisible();
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
    // indexing into a specific position (same reasoning as
    // `external-project-invite.spec.ts`'s equivalent project-level test).
    expect(links.some((link) => link !== firstLink)).toBe(true);
  });
});

test("filtering the Users table by organisation role narrows results", async ({ page }) => {
  const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  const adminToken = (await adminLoginResp.json()).access_token;
  const { org, orgAdminEmail } = await setupOrgAndAdmin(page, adminToken, "rolefilter");

  const orgAdminToken = (
    await (
      await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: orgAdminEmail, password: "OrgAdmin123!" },
      })
    ).json()
  ).access_token;
  const suffix = Date.now();
  const creatorEmail = `e2e-role-filter-creator-${suffix}@example.com`;
  const memberEmail = `e2e-role-filter-member-${suffix}@example.com`;
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: { Authorization: `Bearer ${orgAdminToken}` },
    data: { email: creatorEmail, display_name: "Role Filter Creator", password: "RoleFilter123!", role: "project_creator" },
  });
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: { Authorization: `Bearer ${orgAdminToken}` },
    data: { email: memberEmail, display_name: "Role Filter Member", password: "RoleFilter123!", role: "member" },
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill(orgAdminEmail);
  await page.getByLabel("Password").fill("OrgAdmin123!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.goto("/orgs");
  await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
  await page.getByRole("link", { name: "Users" }).click();
  await ensureExpanded(page, "Organisation users");
  await expect(page.getByText(creatorEmail)).toBeVisible();
  await expect(page.getByText(memberEmail)).toBeVisible();

  await page.getByRole("combobox", { name: "Organisation role" }).selectOption({ label: "Project creator" });
  await expect(page.getByText(creatorEmail)).toBeVisible();
  await expect(page.getByText(memberEmail)).toHaveCount(0);

  await page.getByRole("combobox", { name: "Organisation role" }).selectOption({ label: "Member" });
  await expect(page.getByText(memberEmail)).toBeVisible();
  await expect(page.getByText(creatorEmail)).toHaveCount(0);
});
