import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

import {
  apiHeaders,
  deleteOrgOnCleanup,
  installCleanupHook,
  loginAs,
  onCleanup,
  PASSWORD,
  selectServerManagementGroup,
  SERVER_ADMIN_LOGIN,
} from "./helpers";

// Switches uploads back on after each test and deletes the disposable organisations.
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";

/** Restores the deployment-wide switch whatever the test did, so no other spec meets a disabled deployment. */
function restoreUploadsOnCleanup() {
  onCleanup(async (request) => {
    const headers = await apiHeaders(request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
    await request.put(`${apiBaseUrl}/api/v1/system/file-uploads`, { headers, data: { file_uploads_enabled: true } });
  });
}

/**
 * Job to be done: a server administrator disables file uploads for the whole deployment; every upload control then
 * says it is unavailable and why, and enabling them again restores the control.
 */
test("a server administrator disables uploads and the avatar control becomes unavailable", async ({ page }) => {
  restoreUploadsOnCleanup();
  await loginAs(page, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);

  await test.step("disable uploads in server administration", async () => {
    await page.goto("/server/management");
    await selectServerManagementGroup(page, "File uploads");
    const toggle = page.getByRole("switch", { name: "Allow file uploads" });
    await expect(toggle).toBeChecked();
    await toggle.click();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("The file upload setting was saved.")).toBeVisible();
  });

  await test.step("the avatar control is unavailable and explains why", async () => {
    await page.goto("/preferences/profile");
    const trigger = page.getByRole("button", { name: /Choose file/ });
    await expect(trigger).toHaveAttribute("aria-disabled", "true");
    await trigger.hover();
    await expect(page.getByText(/File uploads are disabled on this deployment/)).toBeVisible();
  });

  await test.step("enabling uploads restores the control", async () => {
    await page.goto("/server/management");
    await selectServerManagementGroup(page, "File uploads");
    await page.getByRole("switch", { name: "Allow file uploads" }).click();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("The file upload setting was saved.")).toBeVisible();
    await page.goto("/preferences/profile");
    await expect(page.locator("label.btn", { hasText: "Choose file" })).toBeVisible();
  });
});

/**
 * Job to be done: importing a project bundle that carries a file while uploads are disabled offers Cancel import
 * or Import without files, creates the records without the file, and reports how many files were left out.
 */
test("importing a bundle with a file while uploads are disabled offers Import without files", async ({ page }) => {
  restoreUploadsOnCleanup();
  const suffix = Date.now();
  const serverHeaders = await apiHeaders(page.request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `E2E Uploads Org ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  // A server administrator is not a member of a new organisation, so its content is created by an organisation admin.
  const orgAdminEmail = `e2e-uploads-admin-${suffix}@example.com`;
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: orgAdminEmail, display_name: "E2E Uploads Admin", password: PASSWORD, role: "org_admin" },
  });
  const orgAdminHeaders = await apiHeaders(page.request, orgAdminEmail, PASSWORD);
  const project = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: orgAdminHeaders, data: { organization_id: org.id, name: `E2E Uploads Source ${suffix}`, summary: "" },
    })
  ).json();
  const component = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/components`, {
      headers: orgAdminHeaders, data: { name: "Software", prefix: "SW" },
    })
  ).json();
  const category = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/categories`, {
      headers: orgAdminHeaders, data: { name: "Performance", prefix: "PERF", component_id: component.id },
    })
  ).json();
  const requirement = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements`, {
      headers: orgAdminHeaders, data: { name: "Requirement with a file", component_id: component.id, category_id: category.id },
    })
  ).json();
  const attached = await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements/${requirement.id}/files`, {
    headers: orgAdminHeaders, multipart: { file: { name: "spec.txt", mimeType: "text/plain", buffer: Buffer.from("hello") } },
  });
  expect(attached.status()).toBe(201);
  const bundle = await page.request.get(`${apiBaseUrl}/api/v1/projects/${project.id}/export`, { headers: orgAdminHeaders });
  const bundlePath = path.join(os.tmpdir(), `e2e-uploads-${suffix}.zip`);
  fs.writeFileSync(bundlePath, await bundle.body());

  await loginAs(page, orgAdminEmail, PASSWORD);
  await page.request.put(`${apiBaseUrl}/api/v1/system/file-uploads`, { headers: serverHeaders, data: { file_uploads_enabled: false } });

  const importedName = `E2E Uploads Imported ${suffix}`;
  await page.goto("/projects");
  await page.getByRole("button", { name: "More options" }).click();
  await page.getByRole("button", { name: "Import project" }).click();
  const form = page.getByRole("dialog", { name: "Import project" });
  await form.getByLabel("Name", { exact: true }).fill(importedName);
  // The organisation admin belongs to one organisation, so the dialog has no organisation picker.
  await form.locator('input[type="file"][accept*="zip"]').setInputFiles(bundlePath);
  await form.getByRole("button", { name: "Import", exact: true }).click();

  await expect(form.getByText(/1 file \(5 B\) cannot be stored because file uploads are disabled/)).toBeVisible();
  await expect(form.getByRole("button", { name: "Cancel import" })).toBeVisible();
  await form.getByRole("button", { name: "Import without files" }).click();

  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/, { timeout: 15000 });
  // The records came across and the file did not.
  const importedId = page.url().match(/projects\/([0-9a-f-]+)$/)![1];
  const imported: { id: string; name: string }[] = await (
    await page.request.get(`${apiBaseUrl}/api/v1/projects/${importedId}/requirements`, { headers: orgAdminHeaders })
  ).json();
  expect(imported.map((r) => r.name)).toContain("Requirement with a file");
  const files = await (
    await page.request.get(`${apiBaseUrl}/api/v1/projects/${importedId}/requirements/${imported[0].id}/files`, { headers: orgAdminHeaders })
  ).json();
  expect(files).toHaveLength(0);
  fs.rmSync(bundlePath, { force: true });
});
