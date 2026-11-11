import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { apiHeaders, deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, SERVER_ADMIN_LOGIN } from "./helpers";

// Deletes the disposable organisations. The rules set here belong to those organisations only, so no other spec is affected.
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";

type Headers = Record<string, string>;

/**
 * Creates a disposable organisation with an organisation administrator, a project and one requirement; returns the ids
 * needed to upload to it and the administrator's headers. A server administrator holds no organisation role, so the
 * records are created (and uploaded) as the organisation's own administrator.
 */
async function seedOrganisation(page: import("@playwright/test").Page, serverHeaders: Headers, label: string) {
  const suffix = Date.now();
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `E2E Storage ${label} ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  const adminEmail = `e2e-storage-${label.toLowerCase()}-${suffix}@example.com`;
  const created = await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: adminEmail, display_name: `E2E Storage ${label} Admin`, password: PASSWORD, role: "org_admin" },
  });
  expect(created.ok()).toBeTruthy();
  const headers = await apiHeaders(page.request, adminEmail);
  const project = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers, data: { organization_id: org.id, name: `E2E Storage Project ${suffix}`, summary: "" },
    })
  ).json();
  const component = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/components`, { headers, data: { name: "Software", prefix: "SW" } })
  ).json();
  const category = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/categories`, {
      headers, data: { name: "Performance", prefix: "PERF", component_id: component.id },
    })
  ).json();
  const requirement = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements`, {
      headers, data: { name: "Requirement with files", component_id: component.id, category_id: category.id },
    })
  ).json();
  return { org, project, requirement, suffix, adminEmail, headers };
}

function upload(page: import("@playwright/test").Page, headers: Headers, projectId: string, requirementId: string, bytes: number) {
  return page.request.post(`${apiBaseUrl}/api/v1/projects/${projectId}/requirements/${requirementId}/files`, {
    headers, multipart: { file: { name: "data.bin", mimeType: "application/octet-stream", buffer: Buffer.alloc(bytes, 1) } },
  });
}

async function openStorageDialog(page: import("@playwright/test").Page, orgName: string) {
  await page.goto("/server/organisations");
  await page.getByRole("button", { name: `${orgName} actions` }).click();
  await page.getByRole("menuitem", { name: "Storage" }).click();
  return page.getByRole("dialog", { name: `Storage: ${orgName}` });
}

/**
 * Job to be done: a server administrator caps one organisation's storage; an upload past the cap is refused with a
 * message naming the limit, raising the cap lets uploads through again, and another organisation is unaffected.
 */
test("a server administrator sets a storage limit and uploads are refused past it", async ({ page }) => {
  const headers = await apiHeaders(page.request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  const limited = await seedOrganisation(page, headers, "Limited");
  const other = await seedOrganisation(page, headers, "Other");
  await loginAs(page, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);

  await test.step("set a limit of 0.001 MB in the Storage dialog", async () => {
    const dialog = await openStorageDialog(page, limited.org.name);
    await dialog.getByRole("spinbutton", { name: "Storage limit" }).fill("0.001");
    await dialog.getByRole("combobox", { name: "Storage limit unit" }).selectOption("MB");
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("The storage rules were saved.")).toBeVisible();
  });

  await test.step("an upload past the limit is refused, and another organisation is unaffected", async () => {
    const refused = await upload(page, limited.headers, limited.project.id, limited.requirement.id, 2048);
    expect(refused.status()).toBe(403);
    expect((await refused.json()).detail.code).toBe("storage_quota_exceeded");
    const allowed = await upload(page, other.headers, other.project.id, other.requirement.id, 2048);
    expect(allowed.status()).toBe(201);
  });

  await test.step("raising the limit lets the upload through", async () => {
    const dialog = await openStorageDialog(page, limited.org.name);
    await dialog.getByRole("spinbutton", { name: "Storage limit" }).fill("1");
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("The storage rules were saved.")).toBeVisible();
    const accepted = await upload(page, limited.headers, limited.project.id, limited.requirement.id, 2048);
    expect(accepted.status()).toBe(201);
  });
});

/**
 * Job to be done: a server administrator switches uploads off for one organisation; its uploads are refused with a
 * message naming the organisation switch, and switching them on again restores them.
 */
test("a server administrator disables uploads for one organisation", async ({ page }) => {
  const headers = await apiHeaders(page.request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  const seeded = await seedOrganisation(page, headers, "Switch");
  await loginAs(page, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);

  await test.step("switch uploads off", async () => {
    const dialog = await openStorageDialog(page, seeded.org.name);
    await dialog.getByRole("switch", { name: "Allow file uploads" }).click();
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("The storage rules were saved.")).toBeVisible();
  });

  await test.step("an upload is refused with the organisation's code", async () => {
    const refused = await upload(page, seeded.headers, seeded.project.id, seeded.requirement.id, 10);
    expect(refused.status()).toBe(403);
    expect((await refused.json()).detail.code).toBe("organization_uploads_disabled");
  });

  await test.step("switching uploads on restores them", async () => {
    const dialog = await openStorageDialog(page, seeded.org.name);
    await dialog.getByRole("switch", { name: "Allow file uploads" }).click();
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("The storage rules were saved.")).toBeVisible();
    expect((await upload(page, seeded.headers, seeded.project.id, seeded.requirement.id, 10)).status()).toBe(201);
  });
});

/**
 * Job to be done: importing a bundle whose files do not fit the organisation's remaining space offers Cancel import
 * or Import without files, with the size and the space left, and importing without files creates the records.
 */
test("an import that does not fit the storage limit offers Import without files", async ({ page }) => {
  const headers = await apiHeaders(page.request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  const seeded = await seedOrganisation(page, headers, "Import");
  expect((await upload(page, seeded.headers, seeded.project.id, seeded.requirement.id, 4096)).status()).toBe(201);
  const bundle = await page.request.get(`${apiBaseUrl}/api/v1/projects/${seeded.project.id}/export`, { headers: seeded.headers });
  const bundlePath = path.join(os.tmpdir(), `e2e-storage-${seeded.suffix}.zip`);
  fs.writeFileSync(bundlePath, await bundle.body());
  // The original 4 KB are stored; a limit of 5 KB leaves 1 KB, less than the 4 KB the import brings.
  await page.request.put(`${apiBaseUrl}/api/v1/orgs/${seeded.org.id}/storage`, {
    headers, data: { file_uploads_enabled: true, storage_quota_bytes: 5120 },
  });
  await loginAs(page, seeded.adminEmail, PASSWORD);

  await page.goto("/projects");
  await page.getByRole("button", { name: "More options" }).click();
  await page.getByRole("button", { name: "Import project" }).click();
  const form = page.getByRole("dialog", { name: "Import project" });
  await form.getByLabel("Name", { exact: true }).fill(`E2E Storage Imported ${seeded.suffix}`);
  // A single-organisation administrator gets no organisation picker.
  const orgSelect = form.locator("select", { has: page.locator("option", { hasText: seeded.org.name }) });
  if ((await orgSelect.count()) > 0) await orgSelect.selectOption({ label: seeded.org.name });
  await form.locator('input[type="file"][accept*="zip"]').setInputFiles(bundlePath);
  await form.getByRole("button", { name: "Import", exact: true }).click();

  await expect(form.getByText(/do not fit in the storage space left for this organisation/)).toBeVisible();
  await expect(form.getByRole("button", { name: "Cancel import" })).toBeVisible();
  await form.getByRole("button", { name: "Import without files" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/, { timeout: 15000 });
  fs.rmSync(bundlePath, { force: true });
});
