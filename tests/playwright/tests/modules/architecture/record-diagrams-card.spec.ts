import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/**
 * Job to be done: from an element or a connection, move to the diagrams that show it. The Diagrams card is directly under the
 * details card and lists the block diagrams that draw the record (its own box, or an ancestor's; a line, or one rolled up to
 * ancestors) and, for an element, the state machine diagrams that describe it; each row opens its editor.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the records are created through the API as
 * setup, the card and its links through the UI.
 */
test.describe("System Architecture: the Diagrams card on a record page", () => {
  test("an element and a connection list the diagrams that show them and each row opens its editor", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchRecDgm", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const post = async (path: string, data: object) => {
      const res = await page.request.post(`${arch}/${path}`, { headers: adminHeaders, data });
      expect(res.ok(), await res.text()).toBeTruthy();
      return res.json();
    };
    const elementType = (await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json())[0].id;
    const connectionType = (await (await page.request.get(`${arch}/connection-types`, { headers: adminHeaders })).json())[0].id;
    const parent = await post("elements", { name: `Vehicle ${suffix}`, element_type_id: elementType, activate: true });
    const child = await post("elements", { name: `Engine ${suffix}`, element_type_id: elementType, parent_id: parent.id, activate: true });
    const peer = await post("elements", { name: `Driver ${suffix}`, element_type_id: elementType, activate: true });
    const connection = await post("connections", { connection_type_id: connectionType, source_element_id: child.id, target_element_id: peer.id });
    const drawChild = await post("diagrams", { name: `Engine view ${suffix}` });
    const drawParent = await post("diagrams", { name: `Overview ${suffix}` });
    for (const [diagram, ids] of [[drawChild, [child.id, peer.id]], [drawParent, [parent.id, peer.id]]] as const) {
      const saved = await page.request.put(`${arch}/diagrams/${diagram.id}/layout`, {
        headers: adminHeaders, data: { version: diagram.version, placements: ids.map((element_id) => ({ element_id })) },
      });
      expect(saved.ok(), await saved.text()).toBeTruthy();
    }
    const machine = await post("state-machine-diagrams", { name: `Engine modes ${suffix}`, element_id: child.id });

    await test.step("the element's card is the second card and lists both diagram types with how it appears", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/elements/${child.id}`);
      const card = page.getByRole("region", { name: "Diagrams" });
      await expect(card).toBeVisible();
      await expect(page.locator("section.card").nth(1)).toHaveAttribute("aria-label", "Diagrams");
      await expect(card.getByRole("link", { name: new RegExp(`Engine view ${suffix}`) })).toBeVisible();
      await expect(card.getByText(/Block diagram · Placed/)).toBeVisible();
      await expect(card.getByText(new RegExp(`Block diagram · Inside .*Vehicle ${suffix}`))).toBeVisible();
      await expect(card.getByText(/State machine diagram · Describes this element/)).toBeVisible();
      await expect(card.getByRole("button", { name: "New state machine diagram" })).toBeVisible();
    });

    await test.step("a row opens the state machine editor", async () => {
      await page.getByRole("region", { name: "Diagrams" }).getByRole("link", { name: new RegExp(`Engine modes ${suffix}`) }).click();
      await expect(page).toHaveURL(new RegExp(`/state-machine-diagrams/${machine.id}$`));
    });

    await test.step("the connection's card lists the diagrams that draw it, including a rolled-up line", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/connections/${connection.id}`);
      const card = page.getByRole("region", { name: "Diagrams" });
      await expect(page.locator("section.card").nth(1)).toHaveAttribute("aria-label", "Diagrams");
      await expect(card.getByText(/Block diagram · Drawn/)).toBeVisible();
      await expect(card.getByText(/Block diagram · Rolled up/)).toBeVisible();
      await expect(card.getByRole("button", { name: "New state machine diagram" })).toHaveCount(0);
    });

    await test.step("a row opens the block diagram editor", async () => {
      await page.getByRole("region", { name: "Diagrams" }).getByRole("link", { name: new RegExp(`Overview ${suffix}`) }).click();
      await expect(page).toHaveURL(new RegExp(`/diagrams/${drawParent.id}$`));
    });
  });
});
