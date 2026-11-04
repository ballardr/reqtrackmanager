import crypto from "node:crypto";

import { expect, type APIRequestContext, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, openDesignerTextView, PASSWORD, saveNewVersion, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: reorder blocks in the block editor by dragging one, without the blocks below it coming along.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout block drag", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  test("dragging a middle block moves only that block, and the new order is saved", async ({ page, request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-blockdrag-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Block drag ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Block Drag Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Drag project ${suffix}`, summary: "" } })).json();
    const name = `E2E drag layout ${suffix}`;
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
    const dialog = page.getByRole("dialog", { name: "New report layout" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await page.getByRole("tab", { name: "Blocks" }).click();

    await test.step("three blocks are added, each after the one before", async () => {
      for (const label of ["Page break", "Spacer", "Heading 1"]) {
        await page.getByRole("button", { name: "Add block" }).click();
        await page.getByRole("menuitem", { name: label, exact: true }).click();
      }
    });

    const title = (label: string) => page.locator(".blocklyText").filter({ hasText: new RegExp(`^${label}$`) }).first();

    await test.step("dragging the Spacer below the Heading leaves the Heading where it was", async () => {
      const grab = (await title("Spacer").boundingBox())!;
      const below = (await title("Heading").boundingBox())!;
      await page.mouse.move(grab.x + 4, grab.y + grab.height / 2);
      await page.mouse.down();
      // Blockly starts a drag after a few pixels of movement; step so it sees a drag, not a click.
      await page.mouse.move(grab.x + 20, grab.y + 20, { steps: 5 });
      // Once the Spacer is lifted out the Heading closes up into the Spacer's place, so the Spacer belongs where the
      // Heading's title was: one block below its own place, whatever height the fonts make a block.
      await page.mouse.move(below.x + 4, below.y + below.height / 2, { steps: 15 });
      await page.mouse.up();
    });

    const order = async () => {
      await openDesignerTextView(page);
      const text = await page.getByRole("textbox", { name: "Layout text" }).inputValue();
      await page.getByRole("tab", { name: "Blocks" }).click();
      return text;
    };

    await test.step("the saved layout has the new order", async () => {
      expect(await order()).toMatch(/@page_break[\s\S]*@heading[\s\S]*@spacer/);
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@page_break[\s\S]*@heading[\s\S]*@spacer/);
    });
  });
});
