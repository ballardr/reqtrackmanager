import { expect, type Page, test } from "@playwright/test";

import {
  approveRequirementFromDetail, expectCurrentStep, installCleanupHook, promoteTo, selectProjectAdminGroup,
} from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a project refuses to approve a requirement that does not meet a Required traceability rule. It turns on
 * the Traceability rules check for approvals in its baseline policy; a requirement whose only links were carried over
 * from another requirement is refused until a person confirms them, from the Links panel or the Actions card.
 *
 * Each test builds its own disposable org (see `../stakeholders/helpers.ts`), so none depends on seeded state or on
 * another test having run.
 */

const MODULE_NAME = "Traceability & Governance";

type Headers = { Authorization: string };

async function send(page: Page, headers: Headers, method: "post" | "put" | "get", path: string, data?: unknown) {
  const response = await page.request[method](`${API_BASE_URL}/api/v1${path}`, { headers, data });
  expect(response.status(), await response.text()).toBeLessThan(300);
  return response.status() === 204 ? null : response.json();
}

/**
 * A requirement linked to another and to an action, then copied by making an alias of it independent, so every link of
 * the copy carries a note; and a Required rule that every requirement links to a requirement. Returns the copy's id.
 */
async function carriedOverRequirement(page: Page, headers: Headers, orgId: string, projectId: string): Promise<string> {
  const project = `/projects/${projectId}`;
  const software = await send(page, headers, "post", `${project}/components`, { name: "Software", prefix: "SW" });
  const performance = await send(page, headers, "post", `${project}/categories`, { name: "Performance", prefix: "PERF", component_id: software.id });
  const hardware = await send(page, headers, "post", `${project}/components`, { name: "Hardware", prefix: "HW" });
  const interfaces = await send(page, headers, "post", `${project}/categories`, { name: "Interfaces", prefix: "IF", component_id: hardware.id });
  const requirement = (name: string) =>
    send(page, headers, "post", `${project}/requirements`, { name, component_id: software.id, category_id: performance.id });
  const original = await requirement("Bus timing");
  const upstream = await requirement("System timing");

  const linkTypes: { id: string; forward_name: string }[] = await send(page, headers, "get", `/orgs/${orgId}/link-types`);
  const linkType = linkTypes.find((t) => t.forward_name !== "Related to")!;
  await send(page, headers, "post", `${project}/artefacts/requirement/${original.id}/links`, {
    link_type_id: linkType.id, direction: "outgoing", other_type: "requirement", other_id: upstream.id,
  });
  const actionTypes: { id: string }[] = await send(page, headers, "get", `${project}/action-types`);
  await send(page, headers, "post", `${project}/requirements/${original.id}/actions/create-and-link`, {
    title: "Bench test the bus", action_type_id: actionTypes[0].id,
  });

  const aliased = await send(page, headers, "put", `${project}/requirements/${original.id}/aliases`, {
    places: [{ component_id: hardware.id, category_id: interfaces.id }],
  });
  const made = await send(page, headers, "post", `${project}/requirements/${original.id}/aliases/${aliased.aliases[0].id}/make-independent`, {});

  await send(page, headers, "post", `${project}/modules/traceability/rules`, {
    name: "Requirements trace to a requirement", source_type: "requirement", level: "required",
    requires: { op: "link", direction: "outgoing", min: 1, targets: [{ artefact_type: "requirement" }] },
  });
  return made.requirement_id;
}

test.describe("Traceability enforcement", () => {
  test("carried-over links refuse an approval until one is confirmed", async ({ page }) => {
    test.setTimeout(120_000);
    const { org, project, adminHeaders } = await setUpOrg(page, "TraceEnforce", false, MODULE_NAME);
    const copyId = await carriedOverRequirement(page, adminHeaders, org.id, project.id);
    const copyUrl = `/projects/${project.id}/requirements/${copyId}`;

    await test.step("the project checks the Required rules when a person approves a record", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Baseline policy", "Governance");
      await page.getByRole("checkbox", { name: "Stage baseline" }).uncheck();
      await page.getByRole("combobox", { name: "Check record approvals" }).selectOption({ label: "Manual approvals only" });
      await page.getByRole("checkbox", { name: "Traceability rules" }).check();
      await page.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Baseline policy saved.")).toBeVisible();
      await expect(page.getByRole("row", { name: /Traceability rules/ }).getByText("Manual approvals")).toBeVisible();
    });

    await test.step("approving the copy is refused, naming the rule", async () => {
      await page.goto(copyUrl);
      await promoteTo(page, "Approved");
      const dialog = page.getByRole("dialog", { name: "Approve this requirement?" });
      await dialog.getByRole("button", { name: "Approve", exact: true }).click();
      await expect(page.getByText(/met only by links carried over/).first()).toBeVisible();
    });

    await test.step("the action's carried-over link is confirmed from the Actions card", async () => {
      await page.goto(copyUrl);
      await page.getByRole("button", { name: "Actions for Bench test the bus" }).click();
      await page.getByRole("menuitem", { name: "Confirm link" }).click();
      await expect(page.getByText("Link confirmed.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Actions for Bench test the bus" })).toHaveCount(0);
    });

    await test.step("a requirement link is confirmed from the Links panel and the approval succeeds", async () => {
      const links = page.getByRole("region", { name: "Links" });
      const rowMenus = links.getByRole("button", { name: /^Actions for link: .*System timing/ });
      await rowMenus.click();
      await page.getByRole("menuitem", { name: "Confirm link" }).click();
      await expect(rowMenus).toHaveCount(0);
      await approveRequirementFromDetail(page);
      await expectCurrentStep(page, "Approved");
      const approved = await send(page, adminHeaders, "get", `/projects/${project.id}/requirements/${copyId}`);
      expect(approved.status).toBe("approved");
    });
  });
});
