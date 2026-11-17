import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/**
 * Job to be done: an architect moves between the project's diagrams from the diagram's own title, and reads what a diagram
 * shows by hovering its title, with no line of its own for it in the header.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the two diagrams are created through the API
 * as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: switching between diagrams", () => {
  test("the chevron beside the title opens another diagram, and the title's tooltip names what it shows", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSwitch", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const ids: string[] = [];
    for (const name of [`First ${suffix}`, `Second ${suffix}`]) {
      const made = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name, activate: true } });
      expect(made.ok(), await made.text()).toBeTruthy();
      ids.push((await made.json()).id);
    }

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${ids[0]}`);
    const heading = page.getByRole("heading", { name: `First ${suffix}` });
    await expect(heading).toBeVisible();
    // The scope is not a line of its own; hovering the title shows it.
    await expect(page.getByText(/^System context/)).toHaveCount(0);
    await heading.hover();
    await expect(page.getByRole("tooltip")).toContainText("System context");

    await page.getByRole("button", { name: "Switch diagram" }).click();
    await expect(page.getByRole("link", { name: new RegExp(`First ${suffix}`) })).toHaveCount(0);
    await page.getByRole("link", { name: new RegExp(`Second ${suffix}`) }).click();

    await expect(page).toHaveURL(new RegExp(`/diagrams/${ids[1]}$`));
    await expect(page.getByRole("heading", { name: `Second ${suffix}` })).toBeVisible();
  });
});
