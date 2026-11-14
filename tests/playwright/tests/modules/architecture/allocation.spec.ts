import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an architect places an element in a project component and the requirements of that component are
 * suggested for allocation to it. A person accepts one suggestion (it becomes an "Allocated to" link), dismisses another
 * and restores it, and the element's page lists the same requirements from its side.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture switched on. Setup (the component, two
 * requirements, the element and its placement) goes through the API; the allocation itself is driven through the UI.
 */
test.describe("System Architecture: allocation", () => {
  test("a placement suggests requirements, which are accepted, dismissed and restored", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchAlloc", false, "System Architecture");
    const base = `${API_BASE_URL}/api/v1/projects/${project.id}`;
    const component = await (await page.request.post(`${base}/components`, { headers: adminHeaders, data: { name: "Software", prefix: "SW" } })).json();
    const category = await (await page.request.post(`${base}/categories`, {
      headers: adminHeaders, data: { name: "Performance", prefix: "PERF", component_id: component.id },
    })).json();
    const requirement = async (name: string) => {
      const created = await page.request.post(`${base}/requirements`, {
        headers: adminHeaders, data: { name, component_id: component.id, category_id: category.id },
      });
      expect(created.ok(), await created.text()).toBeTruthy();
      return created.json();
    };
    const latency = await requirement(`Report latency ${suffix}`);
    const audit = await requirement(`Audit log ${suffix}`);
    const types = await (await page.request.get(`${base}/modules/architecture/element-types`, { headers: adminHeaders })).json();
    const element = await (await page.request.post(`${base}/modules/architecture/elements`, {
      headers: adminHeaders, data: { name: `Gateway ${suffix}`, element_type_id: types[0].id, activate: true },
    })).json();
    const placed = await page.request.put(`${base}/artefacts/architecture_element/${element.id}/placements`, {
      headers: adminHeaders, data: { placements: [{ component_id: component.id }] },
    });
    expect(placed.ok(), await placed.text()).toBeTruthy();

    await test.step("the requirement suggests the element and accepting makes it allocated", async () => {
      await page.goto(`/projects/${project.id}/requirements/${latency.id}`);
      const card = page.getByRole("region", { name: "Architecture", exact: true });
      await expect(card.getByRole("link", { name: new RegExp(`Gateway ${suffix}`) })).toBeVisible();
      const accepted = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith("/allocation/accept") && r.ok());
      await card.getByRole("button", { name: "Accept", exact: true }).click();
      await accepted;
      await expect(page.getByText("Allocation added.")).toBeVisible();
      await expect(card.getByRole("button", { name: "Accept", exact: true })).toHaveCount(0);
      await expect(card.getByText("Allocated", { exact: true })).toBeVisible();
    });

    await test.step("another requirement dismisses the suggestion and restores it", async () => {
      await page.goto(`/projects/${project.id}/requirements/${audit.id}`);
      const card = page.getByRole("region", { name: "Architecture", exact: true });
      const dismissed = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith("/allocation/dismiss") && r.ok());
      await card.getByRole("button", { name: "Dismiss", exact: true }).click();
      await dismissed;
      await expect(card.getByText("Dismissed", { exact: true })).toBeVisible();
      const restored = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith("/allocation/restore") && r.ok());
      await card.getByRole("button", { name: "Restore", exact: true }).click();
      await restored;
      await expect(card.getByRole("button", { name: "Accept", exact: true })).toBeVisible();
    });

    await test.step("the element's page lists the allocated and the suggested requirement", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/elements/${element.id}`);
      const card = page.getByRole("region", { name: "Requirements", exact: true });
      await expect(card.getByRole("link", { name: new RegExp(`Report latency ${suffix}`) })).toBeVisible();
      await expect(card.getByRole("link", { name: new RegExp(`Audit log ${suffix}`) })).toBeVisible();
      await expect(card.getByRole("button", { name: "Accept", exact: true })).toHaveCount(1);
    });
  });
});
