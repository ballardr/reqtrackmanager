import { expect, test } from "@playwright/test";

import { installCleanupHook } from "./helpers";
import { API_BASE_URL, setUpOrg } from "../modules/stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: the display fixes of the fourth review show up on real pages. A versioned record shows
 * a labelled "Version 1" and no bare "v1"; the aside is one card whose "Links" appears once, wide and
 * stacked; the Pain Points list opens on open items and a link naming a status shows that slice; the
 * Score column carries its settings behind a gear that never sorts; a checkbox's text sits beside its box;
 * and a comment given at a workflow step is shown under its sentence in the Activity tab.
 *
 * Disposable org, created through the API and removed afterwards, so the spec depends on no seeded state and
 * can be repeated against the same database.
 */
test("detail header, aside card, Pain Points list defaults, score settings and transition comments", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "FourthReview");
  const enable = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers: adminHeaders, data: { enabled: true },
  });
  expect(enable.ok()).toBeTruthy();
  const cs = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/context_strategy`;
  const types = await (await page.request.get(`${cs}/pain-point-types`, { headers: adminHeaders })).json();
  const create = async (title: string) =>
    (await (await page.request.post(`${cs}/pain-points`, {
      headers: adminHeaders, data: { pain_point_type_id: types[0].id, title, description: "d" },
    })).json()) as { id: string };
  const step = async (id: string, name: string, comment?: string) => {
    const resp = await page.request.post(`${cs}/pain-points/${id}/${name}`, { headers: adminHeaders, data: { comment: comment ?? "" } });
    expect(resp.ok(), await resp.text()).toBeTruthy();
  };
  const openTitle = `Still open ${suffix}`;
  const doneTitle = `Already addressed ${suffix}`;
  const open = await create(openTitle);
  const done = await create(doneTitle);
  for (const name of ["triage", "accept"]) await step(done.id, name);
  await step(open.id, "triage");
  await step(open.id, "accept");
  const list = `/projects/${project.id}/modules/context_strategy/pain-points`;

  await test.step("the list opens on open Pain Points only, and a status link shows that slice", async () => {
    await page.goto(list);
    await expect(page.getByRole("checkbox", { name: "Open only" })).toBeChecked();
    await expect(page.getByRole("button", { name: openTitle })).toBeVisible();
    await step(done.id, "address", "Fixed in release 2.1.\nVerified with the field team.");
    await page.reload();
    await expect(page.getByRole("button", { name: doneTitle })).toHaveCount(0);
    await page.getByRole("checkbox", { name: "Open only" }).uncheck();
    await expect(page.getByRole("button", { name: doneTitle })).toBeVisible();

    await page.goto(`${list}?status=addressed`);
    await expect(page.getByRole("checkbox", { name: "Open only" })).not.toBeChecked();
    await expect(page.getByRole("button", { name: doneTitle })).toBeVisible();
    await expect(page.getByRole("button", { name: openTitle })).toHaveCount(0);
  });

  await test.step("a checkbox's text sits beside its box in the filter panel", async () => {
    await page.goto(list);
    const box = page.getByRole("checkbox", { name: "Hide intentional limitations" });
    const geometry = await box.evaluate((el) => {
      const label = el.parentElement!;
      const range = document.createRange();
      range.setStart(label.lastChild!, 0);
      range.setEnd(label.lastChild!, 1);
      const first = range.getClientRects()[0];
      const b = el.getBoundingClientRect();
      return { textLeft: first.left, boxRight: b.right, textMid: first.top + first.height / 2, boxMid: b.top + b.height / 2, line: first.height };
    });
    expect(geometry.textLeft).toBeGreaterThanOrEqual(geometry.boxRight - 1);
    expect(Math.abs(geometry.textMid - geometry.boxMid)).toBeLessThan(geometry.line);
  });

  await test.step("the Score column's gear opens the settings and never sorts", async () => {
    await page.getByRole("checkbox", { name: "Open only" }).uncheck();
    const gear = page.getByRole("button", { name: /^Score settings: / });
    await expect(page.getByRole("combobox", { name: "Scoring model" })).toHaveCount(0);
    await gear.click();
    await expect(page.getByRole("combobox", { name: "Scoring model" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Combine personas by" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: /Score/ })).toHaveAttribute("aria-sort", "none");
    await page.keyboard.press("Escape");
  });

  await test.step("the transition comment is quoted under its sentence in the Activity tab", async () => {
    await page.goto(`${list}/${done.id}`);
    await page.getByRole("tab", { name: "Activity" }).click();
    const note = page.locator("blockquote.activity-note", { hasText: "Fixed in release 2.1." });
    await expect(note).toBeVisible();
    await expect(note).toContainText("Verified with the field team.");
  });

  await test.step("addressing through the dialog records its comment too", async () => {
    await page.goto(`${list}/${open.id}`);
    await page.getByRole("button", { name: "Address" }).click();
    const dialog = page.getByRole("dialog", { name: "Mark this Pain Point addressed?" });
    await dialog.getByLabel("Transition comment").fill("Shipped in the March release");
    await dialog.getByRole("button", { name: "Address" }).click();
    await page.getByRole("tab", { name: "Activity" }).click();
    await expect(page.locator("blockquote.activity-note", { hasText: "Shipped in the March release" })).toBeVisible();
  });

  await test.step("the aside is one card, and 'Links' appears once wide and stacked", async () => {
    for (const width of [1440, 1000]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`${list}/${done.id}`);
      const aside = page.getByRole("complementary", { name: "Links" });
      // The earlier steps left the Activity tab selected (the choice is remembered), so open Links.
      await aside.getByRole("tab", { name: "Links" }).click();
      await expect(aside.getByRole("button", { name: "Add link" })).toBeVisible();
      await expect(aside.getByText("Links", { exact: true })).toHaveCount(1);
      await expect(aside.locator(".card")).toHaveCount(1);
      await expect(aside.locator(".card").getByRole("tablist")).toBeVisible();
    }
  });
});

/**
 * Job to be done: the record's version is labelled metadata on the badge line, not an unexplained "v1"
 * above the lifecycle button.
 */
test("a versioned record shows 'Version 1' on its badge line, not a bare 'v1'", async ({ page }) => {
  const { suffix, project, adminHeaders } = await setUpOrg(page, "VersionLabel");
  const persona = await (
    await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas`, {
      headers: adminHeaders, data: { name: `Versioned persona ${suffix}` },
    })
  ).json();
  await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
  const version = page.locator(".record-header").getByText("Version 1", { exact: true });
  await expect(version).toBeVisible();
  await expect(version).toHaveAttribute("title", "Version 1 of this record");
  await expect(page.locator(".record-header").getByText(/^v1$/)).toHaveCount(0);
});
