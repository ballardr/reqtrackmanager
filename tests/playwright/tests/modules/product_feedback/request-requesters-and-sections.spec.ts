import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, createRequest, projectBase, requestLevels, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a triager records who asked for a request from the request itself (the Demand card and the edit form),
 * reads a long list of requesters a page at a time, switches External references off where a project does not use
 * them, and arranges the sections of a request's page, as a project default and as a personal order.
 *
 * Each test builds its own disposable org (see `./helpers.ts`).
 */

/** Turns the Stakeholders module on and creates `count` stakeholders named `<prefix> <n>`; returns their ids. */
async function stakeholders(page: Page, org: { id: string }, project: { id: string }, headers: Record<string, string>, prefix: string, count: number) {
  const enabled = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders`, { headers, data: { enabled: true } });
  expect(enabled.ok(), await enabled.text()).toBeTruthy();
  const ids: string[] = [];
  for (let i = 1; i <= count; i += 1) {
    const created = await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/stakeholders`, {
      headers, data: { name: `${prefix} ${String(i).padStart(2, "0")}` },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    ids.push((await created.json()).id);
  }
  return ids;
}

/** Records `stakeholderIds` as the request's requesters through the generic link endpoint. */
async function requestedBy(page: Page, org: { id: string }, project: { id: string }, headers: Record<string, string>, requestId: string, stakeholderIds: string[]) {
  const linkTypes = await (await page.request.get(`${API_BASE_URL}/api/v1/orgs/${org.id}/link-types`, { headers })).json();
  const linkType = linkTypes.find((t: { forward_name: string }) => t.forward_name === "Requested by").id;
  for (const id of stakeholderIds) {
    const linked = await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/artefacts/enhancement_request/${requestId}/links`, {
      headers, data: { link_type_id: linkType, direction: "outgoing", other_type: "stakeholder", other_id: id },
    });
    expect(linked.ok(), await linked.text()).toBeTruthy();
  }
}

/** The names of the arrangeable cards on the request page, top to bottom. */
async function cardOrder(page: Page): Promise<string[]> {
  return page.locator("section[aria-label]").evaluateAll((els) =>
    els.map((el) => el.getAttribute("aria-label") ?? "").filter((name) => ["External references", "Scoring", "Demand", "Evidence"].includes(name)));
}

test.describe("Enhancement requests: requesters, paging, references switch and section order", () => {
  test("requesters are added from the Demand card and from the edit form", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "FeedbackRequesters");
    await stakeholders(page, org, project, adminHeaders, `Asker ${suffix}`, 2);
    const request = await createRequest(page, projectBase(project.id), adminHeaders, { title: `Wanted ${suffix}` });
    await page.goto(`/projects/${project.id}/modules/product_feedback/requests/${request.id}`);
    const table = page.getByRole("table", { name: "Requesters" });

    await test.step("the Demand card adds a requester", async () => {
      await page.getByRole("button", { name: "Add requester" }).click();
      const dialog = page.getByRole("dialog", { name: "Add requesters" });
      await dialog.getByRole("combobox", { name: "Requested by" }).fill(`Asker ${suffix} 01`);
      await dialog.getByRole("option", { name: new RegExp(`Asker ${suffix} 01`) }).click();
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Linked to 1 record.")).toBeVisible();
      await expect(table.getByText(`Asker ${suffix} 01`)).toBeVisible();
    });

    await test.step("the edit form adds another, saved with the edit", async () => {
      await page.getByRole("button", { name: /^Edit/ }).first().click();
      const dialog = page.getByRole("dialog", { name: /^Edit / });
      // The requesters sit in a section that starts closed, and list who has asked so far.
      await dialog.getByRole("button", { name: "Requesters section" }).click();
      await expect(dialog.getByRole("list", { name: "Current requesters" }).getByText(`Asker ${suffix} 01`)).toBeVisible();
      await dialog.getByRole("combobox", { name: "Add requesters" }).fill(`Asker ${suffix} 02`);
      await dialog.getByRole("option", { name: new RegExp(`Asker ${suffix} 02`) }).click();
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(table.getByText(`Asker ${suffix} 02`)).toBeVisible();
      await expect(table.getByText(`Asker ${suffix} 01`)).toBeVisible();
    });

    await test.step("one added by mistake is removed, after a confirmation", async () => {
      await page.getByRole("button", { name: `Remove requester Asker ${suffix} 02` }).click();
      await page.getByRole("dialog", { name: "Remove this requester?" }).getByRole("button", { name: "Remove" }).click();
      await expect(page.getByText("Requester removed.")).toBeVisible();
      await expect(table.getByText(`Asker ${suffix} 02`)).toHaveCount(0);
      await expect(table.getByText(`Asker ${suffix} 01`)).toBeVisible();
    });
  });

  test("a long list of requesters is read a page at a time and the headline covers everyone", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "FeedbackPaging");
    const ids = await stakeholders(page, org, project, adminHeaders, `Crowd ${suffix}`, 27);
    const request = await createRequest(page, projectBase(project.id), adminHeaders, { title: `Popular ${suffix}` });
    await requestedBy(page, org, project, adminHeaders, request.id, ids);
    await page.goto(`/projects/${project.id}/modules/product_feedback/requests/${request.id}`);

    const table = page.getByRole("table", { name: "Requesters" });
    await expect(page.getByText(/^27 requesters/)).toBeVisible();
    await expect(page.getByText("Showing 25 of 27 requesters")).toBeVisible();
    await expect(table.getByRole("row")).toHaveCount(26); // header + one page
    await page.getByRole("button", { name: "Show more" }).click();
    await expect(table.getByRole("row")).toHaveCount(28);
    await expect(page.getByText(/Showing \d+ of/)).toHaveCount(0);
  });

  test("a project can switch External references off and back on", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "FeedbackRefsOff");
    const request = await createRequest(page, projectBase(project.id), adminHeaders, { title: `Tracked ${suffix}` });
    const subcomponent = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/product_feedback/subcomponents/external_references`;
    const detail = `/projects/${project.id}/modules/product_feedback/requests/${request.id}`;

    await test.step("on by default: the card is offered", async () => {
      await page.goto(detail);
      await expect(page.getByRole("region", { name: "External references" })).toBeVisible();
    });

    await test.step("off: no card, no field in the form, no External Systems settings", async () => {
      const off = await page.request.put(subcomponent, { headers: adminHeaders, data: { enabled: false } });
      expect(off.ok(), await off.text()).toBeTruthy();
      await page.goto(detail);
      await expect(page.getByRole("region", { name: "Demand" })).toBeVisible();
      await expect(page.getByRole("region", { name: "External references" })).toHaveCount(0);
      await page.goto(`/projects/${project.id}/modules/product_feedback/requests`);
      await page.getByRole("button", { name: "New request" }).click();
      const dialog = page.getByRole("dialog", { name: /New enhancement request/ });
      await expect(dialog.getByRole("textbox", { name: "Request title" })).toBeVisible();
      await expect(dialog.getByText("External references")).toHaveCount(0);
    });

    await test.step("on again: the card returns", async () => {
      const on = await page.request.put(subcomponent, { headers: adminHeaders, data: { enabled: true } });
      expect(on.ok(), await on.text()).toBeTruthy();
      await page.goto(detail);
      await expect(page.getByRole("region", { name: "External references" })).toBeVisible();
    });
  });

  test("the project sets a default section order and a person arranges their own over it", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "FeedbackSections");
    const request = await createRequest(page, projectBase(project.id), adminHeaders, { title: `Ordered ${suffix}` });
    const detail = `/projects/${project.id}/modules/product_feedback/requests/${request.id}`;

    await test.step("built in: references, scoring, demand, evidence", async () => {
      await page.goto(detail);
      await expect(page.getByRole("region", { name: "Demand" })).toBeVisible();
      expect(await cardOrder(page)).toEqual(["External references", "Scoring", "Demand", "Evidence"]);
    });

    await test.step("the project default puts Demand first", async () => {
      const saved = await page.request.put(`${projectBase(project.id)}/settings`, { headers: adminHeaders, data: { request_page_sections: ["demand", "details"] } });
      expect(saved.ok(), await saved.text()).toBeTruthy();
      await page.goto(detail);
      await expect(page.getByRole("region", { name: "Demand" })).toBeVisible();
      await expect.poll(() => cardOrder(page)).toEqual(["Demand", "External references", "Scoring", "Evidence"]);
    });

    await test.step("a person's own order wins, and resetting returns to the project's", async () => {
      await page.getByRole("button", { name: "Request actions" }).click();
      await page.getByRole("menuitem", { name: "Arrange sections…" }).click();
      const dialog = page.getByRole("dialog", { name: "Arrange sections" });
      await dialog.getByRole("button", { name: "Move Scoring up" }).click();
      await dialog.getByRole("button", { name: "Move Scoring up" }).click();
      await dialog.getByRole("button", { name: "Move Scoring up" }).click();
      await expect.poll(() => cardOrder(page)).toEqual(["Scoring", "Demand", "External references", "Evidence"]);
      await page.reload();
      await expect(page.getByRole("region", { name: "Demand" })).toBeVisible();
      await expect.poll(() => cardOrder(page)).toEqual(["Scoring", "Demand", "External references", "Evidence"]); // remembered
      await page.getByRole("button", { name: "Request actions" }).click();
      await page.getByRole("menuitem", { name: "Arrange sections…" }).click();
      await page.getByRole("dialog", { name: "Arrange sections" }).getByRole("button", { name: "Use the project's order" }).click();
      await expect.poll(() => cardOrder(page)).toEqual(["Demand", "External references", "Scoring", "Evidence"]);
    });
  });

  test("the list's Columns control hides score columns and shows Demand, Owner, Created and Last updated, and remembers", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "FeedbackColumns");
    await createRequest(page, projectBase(project.id), adminHeaders, { title: `Listed ${suffix}` });
    const list = `/projects/${project.id}/modules/product_feedback/requests`;
    const table = page.getByRole("table", { name: "Enhancement requests" });
    const headers = () => table.getByRole("columnheader");

    await page.goto(list);
    await expect(table).toBeVisible();
    await expect(headers().filter({ hasText: /^Demand$/ })).toHaveCount(0); // demand and owner start hidden
    await expect(headers().filter({ hasText: /^Owner$/ })).toHaveCount(0);
    await expect(headers().filter({ hasText: /^Created$/ })).toHaveCount(0);
    await expect(headers().filter({ hasText: /^Last updated$/ })).toHaveCount(0);
    await expect(headers().filter({ hasText: /^Status$/ })).toHaveCount(1);
    const scoreColumns = await headers().filter({ hasText: /^Score/ }).count();
    expect(scoreColumns).toBeGreaterThan(0);

    await page.getByRole("button", { name: "Choose columns" }).click();
    const chooser = page.getByRole("dialog", { name: "Columns" });
    await chooser.getByRole("checkbox", { name: "Demand", exact: true }).check();
    await chooser.getByRole("checkbox", { name: "Owner", exact: true }).check();
    await chooser.getByRole("checkbox", { name: "Created", exact: true }).check();
    await chooser.getByRole("checkbox", { name: "Last updated", exact: true }).check();
    await chooser.getByRole("checkbox", { name: /^Score \(/ }).first().uncheck();
    await expect(headers().filter({ hasText: /^Demand$/ })).toHaveCount(1);
    await expect(headers().filter({ hasText: /^Owner$/ })).toHaveCount(1);
    await expect(headers().filter({ hasText: /^Created$/ })).toHaveCount(1);
    await expect(headers().filter({ hasText: /^Last updated$/ })).toHaveCount(1);
    await expect(headers().filter({ hasText: /^Score/ })).toHaveCount(scoreColumns - 1);

    await page.reload();
    await expect(headers().filter({ hasText: /^Demand$/ })).toHaveCount(1); // kept for this person

    await page.getByRole("button", { name: "Choose columns" }).click();
    await page.getByRole("dialog", { name: "Columns" }).getByRole("button", { name: "Show the default columns" }).click();
    await expect(headers().filter({ hasText: /^Demand$/ })).toHaveCount(0);
    await expect(headers().filter({ hasText: /^Score/ })).toHaveCount(scoreColumns);
  });

  test("Criteria not rated: Any criterion keeps the requests not rated on every criterion", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "FeedbackNotRated");
    const { level } = await requestLevels(page, project.id, adminHeaders);
    const full = await createRequest(page, projectBase(project.id), adminHeaders, {
      title: `Complete ${suffix}`,
      levels: {
        reach: level("reach", "Many"), impact: level("impact", "High"), confidence: level("confidence", "High"),
        ease: level("ease", "Easy"), effort: level("effort", "Medium"),
      },
    });
    await createRequest(page, projectBase(project.id), adminHeaders, { title: `Bare ${suffix}` });
    expect(full.title).toBe(`Complete ${suffix}`);

    await page.goto(`/projects/${project.id}/modules/product_feedback/requests`);
    const table = page.getByRole("table", { name: "Enhancement requests" });
    await expect(table.getByText(`Complete ${suffix}`)).toBeVisible();
    await expect(table.getByText(`Bare ${suffix}`)).toBeVisible();
    await page.getByLabel("Criteria not rated").selectOption("any");
    await expect(table.getByText(`Bare ${suffix}`)).toBeVisible();
    await expect(table.getByText(`Complete ${suffix}`)).toHaveCount(0);
  });
});
