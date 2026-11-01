import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";
/** A white-on-transparent 1 x 1 pixel PNG stands in for a white logo. */
const PIXEL = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

/**
 * Job to be done: judge a picture, whatever its colour, in the image library. Pictures are drawn on a checkerboard,
 * and a switch lets the person see them on a light or a dark page. Works in its own disposable organisation.
 */
test.describe("Report image backdrop", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  test("library pictures sit on a checkerboard and the backdrop switch changes it", async ({ page, request }: { page: Page; request: APIRequestContext }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-backdrop-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Backdrop ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Backdrop Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Backdrop project ${suffix}`, summary: "" } })).json();

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
    const create = page.getByRole("dialog", { name: "New report layout" });
    await create.getByRole("textbox", { name: "Name" }).fill(`Backdrop layout ${suffix}`);
    await create.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name: `Backdrop layout ${suffix}` })).toBeVisible();

    await page.getByRole("tab", { name: "Blocks" }).click();
    await page.getByRole("button", { name: "Add block" }).click();
    await page.getByRole("menuitem", { name: "Image", exact: true }).click();
    await page.getByLabel("Block details").getByRole("button", { name: "Choose image…" }).click();
    const library = page.getByRole("dialog", { name: "Image library" });
    const fileName = `white-${suffix}.png`;
    await library.locator('input[type="file"]').setInputFiles({ name: fileName, mimeType: "image/png", buffer: PIXEL });
    await expect(library.getByRole("button", { name: `Select ${fileName}` })).toHaveAttribute("aria-pressed", "true");

    const preview = library.locator(".report-image-preview");
    await expect(preview).toHaveClass(/picture-backdrop/);
    await expect(preview).toHaveAttribute("data-backdrop", "checkerboard");
    await expect(library.getByRole("button", { name: `Select ${fileName}` }).locator("img")).toHaveClass(/picture-backdrop/);

    await library.getByRole("button", { name: "Dark" }).click();
    await expect(preview).toHaveAttribute("data-backdrop", "dark");
    await library.getByRole("button", { name: "Checkerboard" }).click();
    await expect(preview).toHaveAttribute("data-backdrop", "checkerboard");
  });
});
