import { expect, type Page, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a person sees which records are excepted from a traceability rule, why, and whether each exception
 * still covers its record. The list is reached from the navigation rail; each row opens the exception's own page, which
 * links to the excepted record and offers no control that changes the exception.
 *
 * Each test builds its own disposable org (see `../stakeholders/helpers.ts`), so none depends on seeded state or on
 * another test having run. The exceptions are raised through the API.
 */

const MODULE_NAME = "Traceability & Governance";

type Headers = { Authorization: string };

async function send(page: Page, headers: Headers, method: "post" | "get", path: string, data?: unknown) {
  const response = await page.request[method](`${API_BASE_URL}/api/v1${path}`, { headers, data });
  expect(response.status(), await response.text()).toBeLessThan(300);
  return response.json();
}

test.describe("Traceability exceptions", () => {
  test("an exception is found from the navigation rail and read with its record", async ({ page }) => {
    test.setTimeout(120_000);
    const { project, adminHeaders } = await setUpOrg(page, "TraceExcept", false, MODULE_NAME);
    const base = `/projects/${project.id}`;
    const component = await send(page, adminHeaders, "post", `${base}/components`, { name: "Software", prefix: "SW" });
    const category = await send(page, adminHeaders, "post", `${base}/categories`, {
      name: "Performance", prefix: "PERF", component_id: component.id,
    });
    const requirement = await send(page, adminHeaders, "post", `${base}/requirements`, {
      name: "Respond within one second", component_id: component.id, category_id: category.id,
    });
    const rule = await send(page, adminHeaders, "post", `${base}/modules/traceability/rules`, {
      name: "Requirements are verified", source_type: "requirement", level: "required",
      requires: { op: "link", direction: "outgoing", min: 1, targets: [{ artefact_type: "requirement" }] },
    });
    const exception = await send(page, adminHeaders, "post", `${base}/modules/traceability/exceptions`, {
      artefact_type: "requirement", artefact_id: requirement.id, rule_id: rule.id,
      title: "Verification deferred", reason: "Deferred to the flight test.", expires_on: "2099-12-31",
    });

    await test.step("the list shows the request as not yet covering", async () => {
      await page.goto(base);
      await page.getByRole("link", { name: "Traceability Exceptions" }).click();
      await expect(page.getByRole("heading", { name: "Traceability Exceptions" })).toBeVisible();
      const row = page.getByRole("row", { name: /Verification deferred/ });
      await expect(row.getByText("Requested")).toBeVisible();
      await expect(row.getByText("Not approved")).toBeVisible();
      await expect(page.getByRole("button", { name: /^New/ })).toHaveCount(0);
    });

    await test.step("the exception's page names its rule, reason and expiry, and links to the record", async () => {
      await page.getByRole("link", { name: exception.unique_code }).click();
      await expect(page.getByRole("heading", { name: "Verification deferred" })).toBeVisible();
      await expect(page.getByText("Deferred to the flight test.")).toBeVisible();
      await expect(page.getByText("2099-12-31")).toBeVisible();
      await expect(page.getByRole("button", { name: /Approve|Reject|Revoke/ })).toHaveCount(0);
      // An exception takes no links: it names its record itself.
      await expect(page.getByRole("region", { name: "Links" })).toHaveCount(0);
      await page.getByRole("link", { name: /Respond within one second/ }).first().click();
      await expect(page).toHaveURL(new RegExp(`/requirements/${requirement.id}`));
    });

    await test.step("back on the list, Open only keeps a request awaiting a decision", async () => {
      await page.goto(`${base}/modules/traceability/exceptions`);
      await page.getByRole("checkbox", { name: "Open only" }).check();
      await expect(page.getByRole("link", { name: exception.unique_code })).toBeVisible();
    });
  });
});
