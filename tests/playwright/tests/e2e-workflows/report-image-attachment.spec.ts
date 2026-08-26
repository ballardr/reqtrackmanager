import { expect, test } from "@playwright/test";

/**
 * End-to-end proof that a report's Markdown content can include an image
 * (`RichTextEditor`'s "Insert image" panel, `utils/markdown.ts`'s
 * `attachment:` reference, `services/reports.py`'s image-flowable
 * rendering): upload an image through the attachment panel while editing
 * a project's report intro, save it, then generate a PDF and confirm a
 * real PDF download comes back — the actual embed-into-PDF-bytes
 * assertion is covered by `backend/tests/test_report_images.py`
 * (`_IMAGE_MARKER in resp.content`); this spec is the browser-driven proof
 * that the *picker* -> *insert* -> *save* -> *generate* path works end to
 * end through the real UI, not just the API.
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

test("insert an image into a project's report intro and generate a PDF", async ({ page }) => {
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
  const project = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: { Authorization: `Bearer ${orgAdminToken}` },
      data: { organization_id: org.id, name: `E2E Report Image Project ${suffix}`, summary: "" },
    })
  ).json();

  await page.goto("/login");
  await page.getByLabel("Email").fill(orgAdminEmail);
  await page.getByLabel("Password").fill("OrgAdmin123!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.goto(`/projects/${project.id}/admin`);
  await page.getByRole("tab", { name: "Report Setup", exact: true }).click();

  await test.step("upload and insert an image into the report intro", async () => {
    await page.getByRole("button", { name: "Insert image" }).first().click();
    const fileInput = page.locator('input[type="file"][accept="image/*"]').first();
    // setInputFiles only waits for the browser's own file-selection/change
    // event, not for RichTextEditor's async upload (uploadImage awaits
    // api.postFile) that follows it — the markdown insert only happens
    // once that resolves. Wait for the actual upload response so the
    // assertion below isn't racing a real network round trip against a
    // fixed timeout (this can genuinely take longer than 5s on a
    // resource-constrained CI runner than it does locally).
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/resources") && r.request().method() === "POST"),
      fileInput.setInputFiles({
        name: "pixel.png",
        mimeType: "image/png",
        buffer: Buffer.from(TINY_PNG_BASE64, "base64"),
      }),
    ]);
    // The picker inserts `![pixel.png](attachment:<id>)` at the cursor and
    // closes itself — confirm the markdown textarea actually received it.
    const introTextarea = page.locator("textarea").first();
    await expect(introTextarea).toHaveValue(/!\[pixel\.png\]\(attachment:[0-9a-f-]+\)/);
  });

  // As with the image upload above, the click only waits for the DOM
  // event, not for saveReportConfig's async PUT — without waiting for the
  // response here, the subsequent page.goto can outrace the save on a
  // loaded runner, leaving the report intro (and its image reference)
  // unpersisted when the PDF is generated below.
  await Promise.all([
    page.waitForResponse((r) => r.url().includes("/report-config") && r.request().method() === "PUT"),
    page.getByRole("button", { name: "Save settings" }).click(),
  ]);

  await test.step("generate a PDF report and confirm a real PDF downloads", async () => {
    await page.goto(`/projects/${project.id}/reports`);
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
