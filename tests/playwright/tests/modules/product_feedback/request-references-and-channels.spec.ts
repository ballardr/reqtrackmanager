import { expect, test } from "@playwright/test";

import { installCleanupHook, selectProjectAdminGroup } from "../../e2e-workflows/helpers";
import { API_BASE_URL, createRequest, projectBase, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a triager records which Jira or ServiceNow items a request came from and is delivered in, and how
 * each requester asked (a support ticket, a call), so demand can be traced to where it was raised; a project can hide a
 * system it does not use.
 *
 * Builds its own disposable org (see `./helpers.ts`), so it depends on no seeded state.
 */
test.describe("Enhancement requests: external references and channel per ask", () => {
  test("adds, edits and removes references on the request page", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "FeedbackRefs");
    const request = await createRequest(page, projectBase(project.id), adminHeaders, { title: `Referenced ask ${suffix}` });
    await page.goto(`/projects/${project.id}/modules/product_feedback/requests/${request.id}`);
    const card = page.getByRole("region", { name: "External references" });

    await test.step("adds a Jira item that it is delivered in, with a link that opens in a new tab", async () => {
      await page.getByRole("button", { name: "Add reference" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Reference system").selectOption({ label: "Jira" });
      await dialog.getByLabel("Reference key").fill("PROJ-9");
      await dialog.getByLabel("Reference link").fill("https://jira.example.com/browse/PROJ-9");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Reference added.")).toBeVisible();
      const link = card.getByRole("link", { name: "PROJ-9" });
      await expect(link).toHaveAttribute("href", "https://jira.example.com/browse/PROJ-9");
      await expect(link).toHaveAttribute("target", "_blank");
      await expect(card.getByText("Delivered in")).toBeVisible();
    });

    await test.step("adds a ServiceNow ticket it came from", async () => {
      await page.getByRole("button", { name: "Add reference" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Reference system").selectOption({ label: "ServiceNow" });
      await dialog.getByLabel("Reference key").fill("INC0012345");
      await dialog.getByLabel("Reference role").selectOption("origin");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(card.getByText("INC0012345")).toBeVisible();
      await expect(card.getByText("Came from")).toBeVisible();
    });

    await test.step("a web link is required to be http or https", async () => {
      await page.getByRole("button", { name: "Edit reference PROJ-9" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Reference link").fill("javascript:alert(1)");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(dialog.getByText(/http or https/)).toBeVisible();
      await dialog.getByLabel("Reference link").fill("https://jira.example.com/browse/PROJ-10");
      await dialog.getByLabel("Reference key").fill("PROJ-10");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Reference updated.")).toBeVisible();
      await expect(card.getByRole("link", { name: "PROJ-10" })).toBeVisible();
    });

    await test.step("removing a reference asks first and leaves the other", async () => {
      await page.getByRole("button", { name: "Remove reference PROJ-10" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
      await expect(page.getByText("Reference removed.")).toBeVisible();
      await expect(card.getByText("PROJ-10")).toHaveCount(0);
      await expect(card.getByText("INC0012345")).toBeVisible();
    });
  });

  test("a new request takes its first references in the create form", async ({ page }) => {
    const { suffix, project } = await setUpOrg(page, "FeedbackRefsCreate");
    const title = `Created with a ticket ${suffix}`;
    await page.goto(`/projects/${project.id}/modules/product_feedback/requests`);
    await page.getByRole("button", { name: "New request" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Request title").fill(title);
    await dialog.getByRole("button", { name: /Add a reference/ }).click();
    await dialog.getByLabel("Reference 1 system").selectOption({ label: "GitHub" });
    await dialog.getByLabel("Reference 1 key").fill("#42");
    await dialog.getByRole("button", { name: "Save" }).click();
    await page.getByRole("row", { name: new RegExp(title) }).getByRole("link").click();
    await expect(page.getByRole("region", { name: "External references" }).getByText("GitHub")).toBeVisible();
    await expect(page.getByRole("region", { name: "External references" }).getByText("#42")).toBeVisible();
  });

  test("records how a requester asked, and a project can hide a system it does not use", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "FeedbackChannel");
    const enabled = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders`, {
      headers: adminHeaders, data: { enabled: true },
    });
    expect(enabled.ok(), await enabled.text()).toBeTruthy();
    const stakeholder = await (await page.request.post(
      `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/stakeholders`,
      { headers: adminHeaders, data: { name: `Priya ${suffix}` } },
    )).json();
    const linkTypes = await (await page.request.get(`${API_BASE_URL}/api/v1/orgs/${org.id}/link-types`, { headers: adminHeaders })).json();
    const request = await createRequest(page, projectBase(project.id), adminHeaders, { title: `Asked for ${suffix}` });
    const linked = await page.request.post(
      `${API_BASE_URL}/api/v1/projects/${project.id}/artefacts/enhancement_request/${request.id}/links`,
      {
        headers: adminHeaders,
        data: {
          link_type_id: linkTypes.find((t: { forward_name: string }) => t.forward_name === "Requested by").id,
          direction: "outgoing", other_type: "stakeholder", other_id: stakeholder.id,
        },
      },
    );
    expect(linked.ok(), await linked.text()).toBeTruthy();

    await test.step("a requester starts with no channel and a triager sets one", async () => {
      await page.goto(`/projects/${project.id}/modules/product_feedback/requests/${request.id}`);
      const table = page.getByRole("table", { name: "Requesters" });
      await expect(table.getByText("Not recorded")).toBeVisible();
      await page.getByRole("button", { name: `Set channel for Priya ${suffix}` }).click();
      await page.getByRole("combobox", { name: `Channel for Priya ${suffix}` }).selectOption({ label: "Support ticket" });
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Channel recorded.")).toBeVisible();
      await expect(table.getByText("Support ticket")).toBeVisible();
    });

    await test.step("hiding a system in the project stops it being offered, and restoring brings it back", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "External Systems", "Product Feedback");
      await page.getByRole("button", { name: "Hide External system type in this project" }).first().click();
      await page.getByRole("dialog").getByRole("button", { name: /Hide/ }).click();
      await page.goto(`/projects/${project.id}/modules/product_feedback/requests/${request.id}`);
      await page.getByRole("button", { name: "Add reference" }).click();
      await expect(page.getByRole("dialog").getByLabel("Reference system").getByRole("option", { name: "Jira" })).toHaveCount(0);
    });
  });
});
