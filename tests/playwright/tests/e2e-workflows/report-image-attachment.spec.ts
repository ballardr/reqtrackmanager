import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * End-to-end proof that an image reaches a generated requirements report through an organisation resource file:
 * a Markdown resource holds `![pixel.png](attachment:<image id>)`, the Reports page appends it as a resource
 * section, and the PDF that downloads embeds the picture (`report_document.resolve_report_images`). The
 * embed-into-PDF-bytes assertion for cross-organisation and cross-project references is covered by
 * `backend/tests/test_report_images.py`; this spec is the browser-driven proof of the select -> generate path.
 */

const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "ChangeMe123!";
const apiBaseUrl = "http://localhost:8000";

// A minimal, real, decodable 1x1 white PNG (not just a fake header) — the
// same shape backend/tests/test_report_images.py builds, needed because
// ReportLab's image loader (and this test's own upload) requires an
// actually-decodable image, not just bytes claiming to be one.
const TINY_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGP4//8/AAX+Av7czFnnAAAAAElFTkSuQmCC";

test("a resource file with an image is appended to the requirements PDF", async ({ page }) => {
  const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  const adminToken = (await adminLoginResp.json()).access_token;

  const suffix = Date.now();
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { name: `E2E Report Image Org ${suffix}` },
    })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  const orgAdminEmail = `e2e-reportimage-admin-${suffix}@example.com`;
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: { Authorization: `Bearer ${adminToken}` },
    data: { email: orgAdminEmail, display_name: "Report Image Admin", password: "OrgAdmin123!", role: "org_admin" },
  });
  const orgAdminToken = (
    await (
      await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: orgAdminEmail, password: "OrgAdmin123!" },
      })
    ).json()
  ).access_token;
  const authHeaders = { Authorization: `Bearer ${orgAdminToken}` };
  const project = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: authHeaders,
      data: { organization_id: org.id, name: `E2E Report Image Project ${suffix}`, summary: "" },
    })
  ).json();

  const image = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/resources`, {
      headers: authHeaders,
      multipart: { file: { name: "pixel.png", mimeType: "image/png", buffer: Buffer.from(TINY_PNG_BASE64, "base64") } },
    })
  ).json();
  const notesName = `notes-${suffix}.md`;
  const notes = await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/resources`, {
    headers: authHeaders,
    multipart: {
      file: { name: notesName, mimeType: "text/markdown", buffer: Buffer.from(`![pixel.png](attachment:${image.id})\n`) },
    },
  });
  expect(notes.ok(), await notes.text()).toBeTruthy();

  await page.goto("/login");
  await page.getByLabel("Email").fill(orgAdminEmail);
  await page.getByLabel("Password").fill("OrgAdmin123!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.goto(`/projects/${project.id}?reports=choose`);

  await test.step("select the Markdown resource as an appended section", async () => {
    await page.getByRole("button", { name: "Resource sections section" }).click();
    await page.getByLabel(notesName).check();
  });

  await test.step("generate a PDF report and confirm a real PDF with the picture downloads", async () => {
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Generate PDF" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.pdf$/);
    const downloadPath = await download.path();
    expect(downloadPath).not.toBeNull();
    const fs = await import("node:fs/promises");
    const bytes = await fs.readFile(downloadPath as string);
    expect(bytes.subarray(0, 5).toString("ascii")).toBe("%PDF-");
    expect(bytes.includes(Buffer.from("/Subtype /Image"))).toBe(true);
  });
});
