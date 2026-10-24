import { expect, test } from "@playwright/test";

import { installCleanupHook } from "./helpers";
import { API_BASE_URL, setUpOrg } from "../modules/stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: open a project's overview and see how many records it holds in total and how they split by
 * type across the enabled modules, then jump to a type's list from the chart.
 *
 * Each test builds its own disposable organisation through the API, so nothing here depends on seeded state or on
 * another test, and it can be repeated against the same database.
 */

test("the overview totals the records of every enabled module by type and each row opens that type's list", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "OverviewTotal");
  const enabled = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/risk_management`, {
    headers: adminHeaders, data: { enabled: true },
  });
  expect(enabled.ok()).toBeTruthy();
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}`;
  const component = await (await page.request.post(`${base}/components`, { headers: adminHeaders, data: { name: "Software", prefix: "SW" } })).json();
  const category = await (
    await page.request.post(`${base}/categories`, { headers: adminHeaders, data: { name: "Functional", prefix: "FN", component_id: component.id } })
  ).json();
  for (const name of ["First", "Second"]) {
    const created = await page.request.post(`${base}/requirements`, {
      headers: adminHeaders, data: { name: `${name} ${suffix}`, reasoning: "e2e", component_id: component.id, category_id: category.id, keywords: [] },
    });
    expect(created.status()).toBe(201);
  }
  const risk = await page.request.post(`${base}/modules/risk_management/risks`, { headers: adminHeaders, data: { title: `Risk ${suffix}`, cause: "Supplier" } });
  expect(risk.status()).toBe(201);

  await page.goto(`/projects/${project.id}`);
  const chart = page.locator(".card", { hasText: "Total records" });

  await test.step("the centre is the sum and the legend lists each type with its count", async () => {
    await expect(chart).toContainText("3");
    await expect(chart).toContainText(/Requirements\s*2(?!\d)/);
    await expect(chart).toContainText(/Risks\s*1(?!\d)/);
  });

  await test.step("hovering a slice names it and the box stays until the pointer leaves", async () => {
    const ring = await chart.locator(".recharts-wrapper").boundingBox();
    // The first slice (Requirements, 2 of 3) runs clockwise from the top: a point a quarter turn round, mid-band.
    const centre = { x: ring!.x + ring!.width / 2, y: ring!.y + ring!.height / 2 };
    await page.mouse.move(centre.x + 48, centre.y);
    await expect(page.getByRole("tooltip")).toContainText(/Requirements: 2 \(67%\)/);
    await page.mouse.move(centre.x + 49, centre.y + 1);
    await page.waitForTimeout(1000);
    await expect(page.getByRole("tooltip")).toHaveCount(1);
    await page.mouse.move(centre.x, centre.y);
    await expect(page.getByRole("tooltip")).toHaveCount(0);
  });

  await test.step("the Requirements tile is gone: requirements are a slice of the total", async () => {
    await expect(page.locator(".grid-metrics").getByRole("link", { name: "Requirements", exact: true })).toHaveCount(0);
  });

  await test.step("a legend row opens that type's list", async () => {
    await chart.getByRole("button", { name: /Risks/ }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/risk_management/risks`));
    await expect(page.getByText(`Risk ${suffix}`).first()).toBeVisible();
  });
});

test("a project with no records says so instead of drawing an empty ring", async ({ page }) => {
  const { project } = await setUpOrg(page, "OverviewEmpty");

  await page.goto(`/projects/${project.id}`);

  await expect(page.locator(".card", { hasText: "Total records" })).toContainText("No records yet.");
});
