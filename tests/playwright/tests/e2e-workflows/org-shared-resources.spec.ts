import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, SERVER_ADMIN_LOGIN } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: keep an organisation's shared resources where people look for files. The organisation Files page has
 * a Shared resources tab that every member can read; the upload and delete controls appear only for a person the server
 * says may manage them (an organisation administrator, or anyone holding a custom role with that permission), and a
 * resource's link count is stated before it is deleted. Each test works in its own disposable organisation.
 */
test.describe("organisation shared resources", () => {
  installCleanupHook();

  async function token(request: APIRequestContext, email: string, password: string = PASSWORD) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  async function setup(request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const serverHeaders = await token(request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Resources ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    const people: Record<string, string> = {};
    for (const role of ["org_admin", "member"] as const) {
      const email = `e2e-resources-${role}-${suffix}@example.com`;
      await request.post(`${API}/orgs/${org.id}/users`, {
        headers: serverHeaders, data: { email, display_name: `E2E Resources ${role}`, password: PASSWORD, role },
      });
      people[role] = email;
    }
    return { org, people, suffix, adminHeaders: await token(request, people.org_admin) };
  }

  async function openResources(page: Page, orgId: string) {
    await page.goto(`/orgs/${orgId}/files?tab=resources`);
    await expect(page.getByRole("tab", { name: "Shared resources", selected: true })).toBeVisible();
  }

  test("an administrator uploads, sees the link count and deletes; a member only reads", async ({ page, request }) => {
    const { org, people, adminHeaders, suffix } = await setup(request);
    const name = `standard-${suffix}.txt`;

    await test.step("the administrator uploads from the Files page", async () => {
      await loginAs(page, people.org_admin);
      await openResources(page, org.id);
      await page.locator('input[type="file"]').setInputFiles({ name, mimeType: "text/plain", buffer: Buffer.from("shared") });
      await expect(page.getByRole("link", { name })).toBeVisible();
    });

    await test.step("Organisation administration no longer carries the section", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await expect(page.getByRole("button", { name: /Shared resources/ })).toHaveCount(0);
    });

    await test.step("a linked resource names its links in the delete confirmation", async () => {
      const project = await (await request.post(`${API}/projects`, {
        headers: adminHeaders, data: { organization_id: org.id, name: `Resources project ${suffix}`, summary: "" },
      })).json();
      const component = await (await request.post(`${API}/projects/${project.id}/components`, { headers: adminHeaders, data: { name: "Hardware", prefix: "HW" } })).json();
      const category = await (await request.post(`${API}/projects/${project.id}/categories`, {
        headers: adminHeaders, data: { name: "Functional", prefix: "FN", component_id: component.id },
      })).json();
      const requirement = await (await request.post(`${API}/projects/${project.id}/requirements`, {
        headers: adminHeaders, data: { name: `Linked ${suffix}`, component_id: component.id, category_id: category.id },
      })).json();
      const resources = await (await request.get(`${API}/orgs/${org.id}/resources`, { headers: adminHeaders })).json();
      const linked = await request.post(`${API}/projects/${project.id}/requirements/${requirement.id}/files/link`, {
        headers: adminHeaders, data: { file_id: resources[0].id },
      });
      expect(linked.ok(), await linked.text()).toBeTruthy();

      await openResources(page, org.id);
      await page.getByRole("button", { name: `Delete ${name}` }).click();
      const dialog = page.getByRole("dialog", { name: `Delete ${name}?` });
      await expect(dialog.getByText(/removed from 1 /)).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Delete" })).toBeDisabled();
      await dialog.getByRole("textbox").fill(name);
      await dialog.getByRole("button", { name: "Delete" }).click();
      await expect(page.getByRole("link", { name })).toHaveCount(0);
    });

    await test.step("a member sees the list without the controls", async () => {
      await request.post(`${API}/orgs/${org.id}/resources`, {
        headers: adminHeaders, multipart: { file: { name: `readable-${suffix}.txt`, mimeType: "text/plain", buffer: Buffer.from("x") } },
      });
      await loginAs(page, people.member);
      await openResources(page, org.id);
      await expect(page.getByRole("link", { name: `readable-${suffix}.txt` })).toBeVisible();
      await expect(page.getByText("Upload shared resource")).toHaveCount(0);
      await expect(page.getByRole("button", { name: /^Delete / })).toHaveCount(0);
    });
  });

  test("a member given a custom role holding the permission can upload", async ({ page, request }) => {
    const { org, people, adminHeaders, suffix } = await setup(request);
    const memberHeaders = await token(request, people.member);
    const me = await (await request.get(`${API}/auth/me`, { headers: memberHeaders })).json();
    const role = await (await request.post(`${API}/orgs/${org.id}/custom-roles`, {
      headers: adminHeaders,
      data: { name: `Resource keeper ${suffix}`, description: "", scope: "org", permissions: ["manage_org_resources"] },
    })).json();
    const granted = await request.post(`${API}/orgs/${org.id}/custom-roles/${role.id}/users/${me.id}`, { headers: adminHeaders, data: {} });
    expect(granted.ok(), await granted.text()).toBeTruthy();

    await loginAs(page, people.member);
    await openResources(page, org.id);
    await expect(page.getByText("Upload shared resource")).toBeVisible();
  });
});
