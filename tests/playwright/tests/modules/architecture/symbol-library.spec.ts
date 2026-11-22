import { expect, test } from "@playwright/test";

import { installCleanupHook, selectOrgAdminGroup, selectOrgResourcesGroup, selectProjectAdminGroup } from "../../e2e-workflows/helpers";
import { clickMenuRow } from "../../menuTree";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const drawing = (tag: string) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><title>${tag}</title><circle cx="20" cy="20" r="16" fill="none" stroke="#334155" stroke-width="3"/></svg>`;
const svgFile = (name: string) => ({ name: `${name}.svg`, mimeType: "image/svg+xml", buffer: Buffer.from(drawing(name)) });
/** A file the server refuses: it is not a drawing at all (a script inside a real SVG is removed, not refused). */
const notADrawing = (name: string) => ({ name: `${name}.svg`, mimeType: "image/svg+xml", buffer: Buffer.from("this is not a drawing") });

/**
 * Job to be done: an organisation administrator keeps a growing library of symbols (uploaded drawings) shared with every
 * project. The library is a list on Org Resources with a filter panel and folders: upload several files into a folder at
 * once (a refused file does not stop the others), narrow the list by folder, source and name, see where a symbol is used,
 * and see in a project the organisation's symbols read-only under their folder. Organisation Settings no longer lists Symbols.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the library is used through the UI.
 */
test.describe("System Architecture: the symbol library", () => {
  test("upload several symbols into a folder, filter the library, and see it from a project", async ({ page }) => {
    const { suffix, org, project } = await setUpOrg(page, "SymbolLibrary", false, "System Architecture");
    const router = `Router ${suffix}`;
    const switchName = `Switch ${suffix}`;
    const bad = `Bad ${suffix}`;
    const loose = `Loose ${suffix}`;
    const folder = `Network ${suffix}`;

    await test.step("Symbols is in Org Resources, and Organisation Settings no longer lists it", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Element Types", "System Architecture");
      await expect(page.locator("nav.resource-menu-nav").getByRole("link", { name: "Symbols", exact: true })).toHaveCount(0);
      await page.goto(`/orgs/${org.id}/resources`);
      await selectOrgResourcesGroup(page, "Architecture Symbols");
      const table = page.getByRole("table", { name: "Symbols" });
      await expect(table.getByText("Server", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Upload symbols" })).toBeVisible();
    });

    await test.step("make a folder from the actions menu", async () => {
      await page.getByRole("button", { name: "List actions" }).click();
      await clickMenuRow(page, "New folder");
      const dialog = page.getByRole("dialog", { name: "New folder" });
      await dialog.getByLabel("Name", { exact: true }).fill(folder);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Folder created.")).toBeVisible();
      await page.getByRole("button", { name: `Folder ${folder}` }).click();
    });

    await test.step("several files upload into the open folder, and a refused file does not stop the others", async () => {
      await page.getByRole("button", { name: "Upload symbols" }).click();
      const dialog = page.getByRole("dialog", { name: "Upload symbols" });
      await dialog.locator("input[type=file]").setInputFiles([svgFile(router), notADrawing(bad), svgFile(switchName)]);
      const results = dialog.getByRole("list", { name: "Upload results" });
      await expect(results.getByRole("listitem")).toHaveCount(3);
      await expect(results.getByRole("alert")).toHaveCount(1);
      await expect(results.getByText("Uploaded.")).toHaveCount(2);
      await dialog.getByRole("button", { name: "Done", exact: true }).click();
      const table = page.getByRole("table", { name: "Symbols" });
      await expect(table.getByText(router, { exact: true })).toBeVisible();
      await expect(table.getByText(switchName, { exact: true })).toBeVisible();
      await expect(table.getByText(bad, { exact: true })).toHaveCount(0);
      await expect(table.getByText("Server", { exact: true })).toHaveCount(0);
    });

    await test.step("a symbol uploaded with no folder stays at the top level", async () => {
      await page.getByRole("button", { name: `Folder ${folder}` }).click();
      await page.getByRole("button", { name: "Upload symbols" }).click();
      const dialog = page.getByRole("dialog", { name: "Upload symbols" });
      await dialog.locator("input[type=file]").setInputFiles(svgFile(loose));
      await expect(dialog.getByText("Uploaded.")).toBeVisible();
      await dialog.getByRole("button", { name: "Done", exact: true }).click();
      const row = page.getByRole("table", { name: "Symbols" }).getByRole("row", { name: new RegExp(loose) });
      await expect(row).toBeVisible();
      await expect(row.getByText(folder)).toHaveCount(0);
    });

    await test.step("the library narrows by name, source and folder, and sorts on the Name header", async () => {
      await page.getByRole("textbox", { name: "Search symbols" }).fill(router);
      const table = page.getByRole("table", { name: "Symbols" });
      await expect(table.getByText(router, { exact: true })).toBeVisible();
      await expect(table.getByText(switchName, { exact: true })).toHaveCount(0);
      await page.getByRole("textbox", { name: "Search symbols" }).fill("");
      await page.getByRole("combobox", { name: "Source" }).selectOption("builtin");
      await expect(table.getByText("Server", { exact: true })).toBeVisible();
      await expect(table.getByText(router, { exact: true })).toHaveCount(0);
      await page.getByRole("combobox", { name: "Source" }).selectOption("uploaded");
      await page.getByRole("button", { name: `Folder ${folder}` }).click();
      await expect(table.getByText(loose, { exact: true })).toHaveCount(0);
      await expect(table.getByText(router, { exact: true })).toBeVisible();
      await page.getByRole("button", { name: /^Name/ }).click();
      await expect(page).toHaveURL(/sort=name/);
    });

    await test.step("a symbol an element type uses names where it is used and cannot be deleted", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const headers = { Authorization: `Bearer ${token}` };
      const symbols = await (await page.request.get(`http://localhost:8000/api/v1/orgs/${org.id}/modules/architecture/symbols`, { headers })).json();
      const chosen = symbols.find((s: { name: string }) => s.name === router);
      const types = await (await page.request.get(`http://localhost:8000/api/v1/orgs/${org.id}/modules/architecture/element-types`, { headers })).json();
      const patched = await page.request.patch(`http://localhost:8000/api/v1/orgs/${org.id}/modules/architecture/element-types/${types[0].id}`, {
        headers, data: { symbol_id: chosen.id },
      });
      expect(patched.ok(), await patched.text()).toBeTruthy();
      await page.reload();
      const row = page.getByRole("table", { name: "Symbols" }).getByRole("row", { name: new RegExp(router) });
      await row.getByRole("button", { name: new RegExp(`Show where ${router} is used`) }).click();
      const used = page.getByRole("dialog", { name: `Where ${router} is used` });
      await expect(used.getByText(org.name)).toBeVisible();
      await expect(used.getByText(new RegExp(`1 element type: ${types[0].name}`))).toBeVisible();
      await used.getByRole("button", { name: "Close", exact: true }).click();
      await row.getByRole("button", { name: `Actions for ${router}` }).click();
      await page.getByRole("menuitem", { name: "Delete symbol" }).click();
      await page.getByRole("button", { name: "Delete", exact: true }).click();
      await expect(page.getByText(/still used by a type or an element/)).toBeVisible();
    });

    await test.step("a project sees the organisation's symbols read-only, under their folder, in its own settings", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Symbols", "System Architecture");
      const table = page.getByRole("table", { name: "Symbols" });
      const row = table.getByRole("row", { name: new RegExp(router) });
      await expect(row).toBeVisible();
      await expect(row.getByText("Organisation", { exact: true })).toBeVisible();
      await expect(row.getByRole("checkbox")).toHaveCount(0);
      await page.getByRole("button", { name: `Organisation folder ${folder}` }).click();
      await expect(table.getByText(router, { exact: true })).toBeVisible();
      await expect(table.getByText(loose, { exact: true })).toHaveCount(0);
      await row.getByRole("button", { name: `Actions for ${router}` }).click();
      await expect(page.getByRole("menuitem", { name: "Hide symbol in this project" })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Rename" })).toHaveCount(0);
    });
  });
});
