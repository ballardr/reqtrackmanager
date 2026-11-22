import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: pick a requirement's component and category from a long tree without losing the search box, with the
 * last row whole at the end of the list and the list meeting the panel's border.
 *
 * Uses its own disposable project with thirty extra categories, so it mutates nothing shared and passes alone, first,
 * last or repeated.
 */
test.describe("tree selector: scroll region and search header", () => {
  installCleanupHook();

  test("open, scroll to the end, search and choose", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Tree Scroll");
    const software = project.components[1];
    for (let i = 1; i <= 30; i += 1) {
      const made = await page.request.post(`http://localhost:8000/api/v1/projects/${project.projectId}/categories`, {
        headers: project.headers, data: { name: `Subsystem ${String(i).padStart(2, "0")}`, prefix: `Q${i}`, component_id: software.id },
      });
      expect(made.ok()).toBeTruthy();
    }
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}/requirements`);
    await page.getByRole("button", { name: "New requirement" }).click();
    const dialog = page.getByRole("dialog", { name: "New requirement" });
    await dialog.getByPlaceholder("Name", { exact: true }).fill("Chosen from a long tree");

    await dialog.getByRole("button", { name: "Component and category", exact: true }).click();
    const panel = page.getByRole("dialog", { name: "Component and category" });
    const choices = panel.getByRole("radiogroup", { name: "Component and category" });
    const search = panel.getByRole("searchbox");
    await expect(search).toBeVisible();

    // The list is the one scrolling element and the search stays where it was.
    const searchTop = (await search.boundingBox())!.y;
    await expect.poll(() => choices.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);
    await choices.evaluate((el) => { el.scrollTop = el.scrollHeight; });
    expect((await search.boundingBox())!.y).toBe(searchTop);

    // The last row is whole and the list ends at the panel's border.
    const last = choices.getByRole("radio", { name: "Software / Subsystem 30" });
    await expect(last).toBeVisible();
    const regionBox = (await choices.boundingBox())!;
    const lastBox = (await last.boundingBox())!;
    expect(lastBox.y + lastBox.height).toBeLessThanOrEqual(regionBox.y + regionBox.height + 0.5);
    const panelBox = (await panel.boundingBox())!;
    expect(panelBox.y + panelBox.height - (regionBox.y + regionBox.height)).toBeLessThanOrEqual(2);

    // A child row shows its own name; its path is the accessible name.
    await expect(last).toHaveText("Subsystem 30");

    await search.fill("Subsystem 07");
    await choices.getByRole("radio", { name: "Software / Subsystem 07" }).click();
    await expect(dialog.getByRole("button", { name: "Component and category", exact: true })).toHaveText(/Software \/ Subsystem 07/);
  });
});
