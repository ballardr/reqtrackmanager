import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: — from a record's Links panel a
 * user opens a trace (tree and map) to see where it comes from and what depends on it, following
 * links as deep as they like.
 *
 * Builds one disposable org with a chain: Requirement A <- (Depends on) Requirement B <- (Implements)
 * Decision D -> (Addresses) Pain Point P. Seen from D, B and P are upstream and A is two hops upstream.
 */
const links = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "Links", exact: true });
const trace = (page: import("@playwright/test").Page) => page.getByRole("dialog", { name: /^Trace:/ });

/** Builds a disposable org per call; the label carries a random part because `setUpOrg` names the org from the
 * millisecond clock, which two tests starting together on separate workers can share. */
async function setUpChain(page: import("@playwright/test").Page) {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, `Trace${Math.random().toString(36).slice(2, 7)}`);
  for (const key of ["context_strategy", "decisions"]) {
    const resp = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/${key}`, { headers: adminHeaders, data: { enabled: true } });
    expect(resp.ok()).toBeTruthy();
  }
  const api = `${API_BASE_URL}/api/v1/projects/${project.id}`;
  const post = async (path: string, data: object) => {
    const resp = await page.request.post(`${api}${path}`, { headers: adminHeaders, data });
    expect(resp.ok(), `${path}: ${await resp.text()}`).toBeTruthy();
    return resp.json();
  };
  const get = async (path: string) => (await page.request.get(`${api}${path}`, { headers: adminHeaders })).json();

  const component = await post("/components", { name: "Software", prefix: "SW" });
  const category = await post("/categories", { name: "Performance", prefix: "PERF", component_id: component.id });
  const requirementA = await post("/requirements", { name: `Baseline ${suffix}`, component_id: component.id, category_id: category.id });
  const requirementB = await post("/requirements", { name: `Keep reports ${suffix}`, component_id: component.id, category_id: category.id });
  const painPointTypes = await get("/modules/context_strategy/pain-point-types");
  const painPoint = await post("/modules/context_strategy/pain-points", {
    title: `Reports arrive late ${suffix}`, description: "d", priority: "high", date_identified: "2026-09-01", pain_point_type_id: painPointTypes[0].id,
  });
  const decisionTypes = await get("/modules/decisions/decision-types");
  const decision = await post("/modules/decisions", { title: `Use Postgres ${suffix}`, decision_statement: "We will.", decision_type_id: decisionTypes[0].id });

  /** Links `from` to `to` with the type whose forward name is `phrase`. */
  async function link(from: [string, string], phrase: string, to: [string, string]) {
    const options: { link_type_id: string; forward_name: string; direction: string }[] = await get(
      `/artefacts/${from[0]}/${from[1]}/link-types?other_type=${to[0]}`,
    );
    const option = options.find((o) => o.forward_name === phrase && o.direction === "outgoing");
    expect(option, `no "${phrase}" link type from ${from[0]} to ${to[0]}`).toBeTruthy();
    await post(`/artefacts/${from[0]}/${from[1]}/links`, {
      link_type_id: option!.link_type_id, direction: "outgoing", other_type: to[0], other_id: to[1],
    });
  }
  await link(["requirement", requirementB.id], "Depends on", ["requirement", requirementA.id]);
  await link(["decision", decision.id], "Implements", ["requirement", requirementB.id]);
  await link(["decision", decision.id], "Addresses", ["pain_point", painPoint.id]);

  return {
    /** Archives Requirement B (a soft delete), the record between the Decision and Requirement A. */
    archiveB: async () => {
      const resp = await page.request.delete(`${api}/requirements/${requirementB.id}`, { headers: adminHeaders });
      expect(resp.ok(), await resp.text()).toBeTruthy();
    },
    suffix,
    labelA: `${requirementA.unique_code} Baseline ${suffix}`,
    labelB: `${requirementB.unique_code} Keep reports ${suffix}`,
    painPointTitle: `Reports arrive late ${suffix}`,
    decisionPage: `/projects/${project.id}/modules/decisions/${decision.id}`,
  };
}

test.describe("link trace", () => {
  test("the tree shows upstream records, opens deeper branches on demand and keeps its direction", async ({ page }) => {
    const { labelA, labelB, painPointTitle, decisionPage } = await setUpChain(page);
    await page.goto(decisionPage);
    await links(page).getByRole("button", { name: "Trace" }).click();

    await test.step("records are grouped by direction", async () => {
      const upstream = trace(page).getByRole("region", { name: /Upstream/ });
      await expect(upstream.getByRole("link", { name: labelB })).toBeVisible();
      await expect(upstream.getByRole("link", { name: painPointTitle })).toBeVisible();
      await expect(trace(page).getByRole("region", { name: /Downstream/ }).getByText("None")).toBeVisible();
    });

    await test.step("opening a branch reads further along the same direction", async () => {
      await expect(trace(page).getByRole("link", { name: labelA })).toHaveCount(0);
      await trace(page).getByRole("button", { name: `Show what is linked beyond ${labelB}` }).click();
      await expect(trace(page).getByRole("link", { name: labelA })).toBeVisible();
      // The decision B is upstream of is not offered again beneath B.
      await trace(page).getByRole("button", { name: `Show what is linked beyond ${labelA}` }).click();
      await expect(trace(page).getByText("Nothing further in this direction.")).toBeVisible();
      await trace(page).getByRole("button", { name: `Hide what is linked beyond ${labelB}` }).click();
      await expect(trace(page).getByRole("link", { name: labelA })).toHaveCount(0);
    });
  });

  test("the map lays records out by direction, grows on demand, and following a record closes the dialog", async ({ page }) => {
    const { labelA, labelB, decisionPage, suffix } = await setUpChain(page);
    await page.goto(decisionPage);
    await links(page).getByRole("button", { name: "Trace" }).click();
    await trace(page).getByRole("tab", { name: "Map" }).click();

    const map = trace(page).getByRole("region", { name: /^Map of the records linked to/ });
    const node = (name: string | RegExp) => map.getByRole("link", { name });

    await test.step("upstream records sit left of the traced record, and two hops are drawn at first", async () => {
      await expect(node(labelB)).toBeVisible();
      await expect(node(labelA)).toBeVisible();
      const focus = await node(new RegExp(`Use Postgres ${suffix}`)).boundingBox();
      const upstream = await node(labelB).boundingBox();
      const furtherUpstream = await node(labelA).boundingBox();
      expect(furtherUpstream!.x).toBeLessThan(upstream!.x);
      expect(upstream!.x).toBeLessThan(focus!.x);
    });

    await test.step("the key opens from a button and explains the symbols", async () => {
      await trace(page).getByRole("button", { name: "Key" }).click();
      await expect(page.getByRole("dialog", { name: "Key" }).getByText("Arrow points downstream")).toBeVisible();
      await trace(page).getByRole("button", { name: "Key" }).click();
      await expect(page.getByRole("dialog", { name: "Key" })).toHaveCount(0);
    });

    await test.step("a record at the edge has a labelled control to read its own links", async () => {
      const showMore = map.getByRole("button", { name: `Show more links of ${labelA}` });
      await expect(showMore).toContainText("Show more");
      await showMore.click();
      // It had nothing further, so the control gives way to a note on the record itself.
      await expect(map.getByText("No more links")).toBeVisible();
      await expect(showMore).toHaveCount(0);
    });

    await test.step("following a record closes the dialog and opens its page", async () => {
      await node(labelB).click();
      await expect(trace(page)).toHaveCount(0);
      await expect(page).toHaveURL(/\/requirements\//);
    });
  });

  test("hiding inactive records joins an archived record's links to the record in front, in both views", async ({ page }) => {
    const { labelA, labelB, painPointTitle, decisionPage, archiveB } = await setUpChain(page);
    await archiveB();
    await page.goto(decisionPage);
    await links(page).getByRole("button", { name: "Trace" }).click();
    const hide = trace(page).getByRole("checkbox", { name: "Hide inactive records" });

    await test.step("archived records show until hidden", async () => {
      const upstream = trace(page).getByRole("region", { name: /Upstream/ });
      await expect(upstream.getByRole("link", { name: labelB })).toBeVisible();
      await expect(upstream.getByRole("link", { name: labelA })).toHaveCount(0);
    });

    await test.step("the tree skips it and joins Requirement A to the Decision, marked via B", async () => {
      await hide.check();
      const upstream = trace(page).getByRole("region", { name: /Upstream/ });
      await expect(upstream.getByRole("link", { name: labelA })).toBeVisible();
      await expect(upstream.getByText(`via ${labelB}`)).toBeVisible();
      await expect(upstream.getByRole("link", { name: labelB })).toHaveCount(0);
      await expect(upstream.getByRole("link", { name: painPointTitle })).toBeVisible();
    });

    await test.step("the map does the same, and the choice carries over", async () => {
      await trace(page).getByRole("tab", { name: "Map" }).click();
      const map = trace(page).getByRole("region", { name: /^Map of the records linked to/ });
      await expect(map.getByRole("link", { name: labelA })).toBeVisible();
      await expect(map.getByRole("link", { name: labelB })).toHaveCount(0);
      await expect(hide).toBeChecked();
    });
  });
});
