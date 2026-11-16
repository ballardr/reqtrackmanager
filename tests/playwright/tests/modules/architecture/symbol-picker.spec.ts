import { expect, test } from "@playwright/test";

import { apiLogin, installCleanupHook, loginAs, logout, PASSWORD, selectProjectAdminGroup } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

const SYMBOL_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><circle cx="20" cy="20" r="16" fill="none" stroke="#334155" stroke-width="3"/></svg>';

const svgFile = (name: string) => ({ name: `${name}.svg`, mimeType: "image/svg+xml", buffer: Buffer.from(SYMBOL_SVG) });

/**
 * Job to be done: an architect chooses a symbol for an element without leaving the form: upload a drawing from the
 * picker (it is chosen and joins the shared library), then browse the library as a Gallery of drawings and choose a tile or
 * the None tile. Someone without the Architecture Admin role is not offered the upload, and the server still refuses it.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the element and the member are API setup,
 * the behaviour under test goes through the UI and the stored reads.
 */
test.describe("System Architecture: the symbol picker uploads and shows a Gallery", () => {
  test("upload from the picker, choose it, then browse the Gallery and choose a tile and None", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSymbolPick", false, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const types = await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json();
    const name = `Gateway ${suffix}`;
    const made = await page.request.post(`${arch}/elements`, { headers: adminHeaders, data: { name, element_type_id: types[0].id, activate: true } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const element = await made.json();
    const symbolName = `edge-${suffix}`;
    const readElement = async () => (await page.request.get(`${arch}/elements/${element.id}`, { headers: adminHeaders })).json();
    const openEdit = async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/elements/${element.id}`);
      await page.getByRole("button", { name: "Edit", exact: true }).click();
      return page.getByRole("dialog", { name: `Edit ${name}` });
    };

    await test.step("an upload from the picker is chosen at once and stored only when the form is saved", async () => {
      const dialog = await openEdit();
      await dialog.locator("input[type=file]").setInputFiles(svgFile(symbolName));
      await expect(page.getByText("Symbol uploaded and chosen. Save to keep the choice.")).toBeVisible();
      await expect(dialog.getByLabel("Symbol", { exact: true }).locator("option:checked")).toHaveText(symbolName);
      expect((await readElement()).symbol_id).toBeNull();
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(dialog).toBeHidden();
      await expect.poll(async () => (await readElement()).symbol_id).not.toBeNull();
    });

    await test.step("the file is in the Symbols settings, in the shared library", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Symbols", "System Architecture");
      await expect(page.locator(`input[value="${symbolName}"]`)).toBeVisible();
    });

    await test.step("the drawing shows on a diagram box", async () => {
      const diagram = await (await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } })).json();
      await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
      await expect(page.getByLabel(`${name}, node`, { exact: true }).locator(".graph-node-symbol")).toBeVisible();
    });

    await test.step("the Gallery shows the drawings, filters by name and chooses a tile", async () => {
      const dialog = await openEdit();
      await dialog.getByRole("button", { name: "Gallery", exact: true }).click();
      await dialog.getByRole("button", { name: /^Symbol:/ }).click();
      const grid = page.getByRole("radiogroup", { name: "Symbols" });
      await expect(grid.getByRole("radio", { name: symbolName })).toHaveAttribute("aria-checked", "true");
      await expect(grid.locator("img").first()).toBeVisible();
      await page.getByLabel("Filter symbols").fill("zzz-no-such");
      await expect(page.getByText("No symbols match.")).toBeVisible();
      await page.getByLabel("Filter symbols").fill(symbolName.slice(0, 6));
      await grid.getByRole("radio", { name: symbolName }).click();
      await expect(grid).toBeHidden();
      await expect(dialog.getByRole("button", { name: `Symbol: ${symbolName}` })).toBeVisible();
    });

    await test.step("the None tile returns to the type's symbol, and the view is remembered", async () => {
      const dialog = page.getByRole("dialog", { name: `Edit ${name}` });
      await dialog.getByRole("button", { name: `Symbol: ${symbolName}` }).click();
      await page.getByRole("radio", { name: "Use the type's symbol" }).click();
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(dialog).toBeHidden();
      await expect.poll(async () => (await readElement()).symbol_id).toBeNull();
      const again = await openEdit();
      await expect(again.getByRole("button", { name: "Gallery", exact: true })).toHaveAttribute("aria-pressed", "true");
    });
  });

  test("a member without the Architecture Admin role is not offered the upload, and the server refuses it", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "ArchSymbolMember", false, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const types = await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json();
    const name = `Router ${suffix}`;
    const made = await page.request.post(`${arch}/elements`, { headers: adminHeaders, data: { name, element_type_id: types[0].id, activate: true } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const element = await made.json();

    const email = `e2e-symbolmember-${suffix}@example.com`;
    const user = await page.request.post(`${API}/api/v1/orgs/${org.id}/users`, {
      headers: adminHeaders, data: { email, display_name: "Symbol Member", password: PASSWORD, role: "member" },
    });
    expect(user.ok(), await user.text()).toBeTruthy();
    const userId = (await user.json()).user_id as string;
    const role = await page.request.post(`${API}/api/v1/projects/${project.id}/roles`, { headers: adminHeaders, data: { user_id: userId, role: "member" } });
    expect(role.ok(), await role.text()).toBeTruthy();
    const architect = await page.request.post(`${API}/api/v1/projects/${project.id}/members/${userId}/module-roles`, {
      headers: adminHeaders, data: { module_key: "architecture", role_key: "architect" },
    });
    expect(architect.ok(), await architect.text()).toBeTruthy();

    await logout(page);
    await loginAs(page, email);
    await page.goto(`/projects/${project.id}/modules/architecture/elements/${element.id}`);
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: `Edit ${name}` });
    await expect(dialog.getByLabel("Symbol", { exact: true })).toBeVisible();
    // The capabilities read has answered before the absence means anything.
    await page.waitForResponse((r) => r.url().endsWith("/modules/architecture/capabilities")).catch(() => undefined);
    await expect(dialog.locator("input[type=file]")).toHaveCount(0);
    await expect(dialog.getByText("Upload a symbol")).toHaveCount(0);

    const token = (await apiLogin(page.request, email)).access_token;
    const refused = await page.request.post(`${arch}/symbols`, { headers: { Authorization: `Bearer ${token}` }, multipart: { file: svgFile("nope") } });
    expect(refused.status()).toBe(403);
  });
});
