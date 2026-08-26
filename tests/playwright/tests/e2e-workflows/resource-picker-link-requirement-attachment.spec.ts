import { expect, test } from "@playwright/test";

/**
 * Job to be done: `Pattern: resource picker dialog` (2026-08 UX audit
 * roadmap row 508) — `RequirementDetailPage.tsx`'s Attachments card can
 * reach into the organisation's shared-resource pool and link an existing
 * file onto the requirement, via `POST /{requirement_id}/files/link`
 * (already existed backend-side, but had zero frontend callers before this
 * pass — see docs/ux-audit-2026-08.md "Shared org resources have almost
 * no way to consume them").
 *
 * Builds its own throwaway org/admin/project/component/category/
 * requirement via the API first (same pattern report-image-attachment.spec.ts
 * already uses for its own picker-driven flow) rather than reusing a seeded
 * project's requirement — Alpha-1's own first requirement (HW-FN-001) is
 * deliberately locked by the seed script for the CR-approval workflow, and
 * this spec needs an unlocked one (the "Link from shared resources" button
 * is hidden once a requirement is locked, matching the direct-upload
 * trigger's own gating) without having to reason about which other seeded
 * requirement is safe to depend on staying unlocked across the whole suite.
 */

const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "ChangeMe123!";
const apiBaseUrl = "http://localhost:8000";

test("link an organisation shared resource onto a requirement via the resource picker dialog", async ({ page }) => {
  const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  const adminToken = (await adminLoginResp.json()).access_token;
  const adminHeaders = { Authorization: `Bearer ${adminToken}` };

  const suffix = Date.now();
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: adminHeaders,
      data: { name: `E2E Resource Picker Org ${suffix}` },
    })
  ).json();
  const orgAdminEmail = `e2e-resourcepicker-admin-${suffix}@example.com`;
  const orgAdminPassword = "OrgAdmin123!";
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: adminHeaders,
    data: { email: orgAdminEmail, display_name: "Resource Picker Admin", password: orgAdminPassword, role: "org_admin" },
  });
  const orgAdminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: { email: orgAdminEmail, password: orgAdminPassword },
  });
  const orgAdminLoginBody = await orgAdminLoginResp.json();
  const orgAdminToken = orgAdminLoginBody.access_token;
  const orgAdminUserId = orgAdminLoginBody.user.id;
  const orgAdminHeaders = { Authorization: `Bearer ${orgAdminToken}` };

  const project = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: orgAdminHeaders,
      data: { organization_id: org.id, name: `E2E Resource Picker Project ${suffix}`, summary: "" },
    })
  ).json();
  const component = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/components`, {
      headers: orgAdminHeaders,
      data: { name: "Software", prefix: "SW" },
    })
  ).json();
  const category = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/categories`, {
      headers: orgAdminHeaders,
      data: { name: "Functional", prefix: "FN", component_id: component.id },
    })
  ).json();
  const requirement = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements`, {
      headers: orgAdminHeaders,
      data: {
        name: "Log every configuration change",
        reasoning: "E2E seed for the resource-picker spec.",
        component_id: component.id,
        category_id: category.id,
        keywords: [],
      },
    })
  ).json();

  // A second shared resource the picker's "no files available" / multi-file
  // shape can be exercised against too, plus proving only the selected one
  // gets attached.
  const filename = `safety-spec-${suffix}.pdf`;
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/resources`, {
    headers: orgAdminHeaders,
    multipart: { file: { name: filename, mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 e2e fixture") } },
  });
  const otherFilename = `onboarding-${suffix}.docx`;
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/resources`, {
    headers: orgAdminHeaders,
    multipart: {
      file: { name: otherFilename, mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: Buffer.from("e2e fixture") },
    },
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill(orgAdminEmail);
  await page.getByLabel("Password").fill(orgAdminPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.goto(`/projects/${project.id}/requirements/${requirement.id}`);
  await expect(page.getByRole("heading", { name: "Attachments" })).toBeVisible();
  // Not linked yet.
  await expect(page.getByRole("link", { name: filename })).toHaveCount(0);

  await test.step("open the resource picker and attach one of the two shared resources", async () => {
    await page.getByRole("button", { name: "Link from shared resources" }).click();

    const dialog = page.getByRole("dialog", { name: "Link from shared resources" });
    await expect(dialog.getByText(filename)).toBeVisible();
    await expect(dialog.getByText(otherFilename)).toBeVisible();

    const attachButton = dialog.getByRole("button", { name: "Attach selected" });
    await expect(attachButton).toBeDisabled();

    await dialog.getByRole("checkbox", { name: filename }).check();
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/files/link") && r.request().method() === "POST"),
      dialog.getByRole("button", { name: "Attach 1 selected" }).click(),
    ]);
    await expect(dialog).not.toBeVisible();
  });

  await test.step("the linked file now appears in the Attachments card, downloadable; the unselected one doesn't", async () => {
    await expect(page.getByRole("link", { name: filename })).toBeVisible();
    await expect(page.getByRole("link", { name: otherFilename })).toHaveCount(0);
  });

  await test.step("once the requirement is locked (approved), the button disappears", async () => {
    const lockResp = await page.request.put(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements/${requirement.id}`, {
      headers: orgAdminHeaders,
      data: {
        name: requirement.name, reasoning: requirement.reasoning, clarification: "",
        component_id: component.id, category_id: category.id, owner_id: orgAdminUserId, status: "approved", keywords: [],
        change_note: "E2E: locking to prove the resource-picker trigger hides once locked.",
      },
    });
    expect(lockResp.ok()).toBe(true);
    await page.reload();
    await expect(page.getByRole("heading", { name: "Attachments" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Link from shared resources" })).toHaveCount(0);
    // The already-linked file is still there — locking only blocks new
    // attachments, not the existing one.
    await expect(page.getByRole("link", { name: filename })).toBeVisible();
  });
});
