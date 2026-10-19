import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../e2e-workflows/helpers";
import { API_BASE_URL, openNew, openPeople, setUpOrg } from "../modules/stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: classify records with lightweight labels, find them again by label, and keep the
 * vocabulary tidy. This walks the whole loop on personas (a module record, so it also shows tags need
 * no per-module code): tag a record from its header, filter a list by the tag, rename the tag, add a
 * second tag and move every record to it with a previewed reclassify, then delete it with the strict
 * confirmation.
 *
 * Disposable org, created through the API and removed afterwards, so the spec depends on no seeded
 * state and can be repeated against the same database.
 */
test("tag a record, filter by the tag, rename it, reclassify and delete it", async ({ page }) => {
  const { suffix, project, adminHeaders } = await setUpOrg(page, "Tags");
  const create = async (name: string) =>
    (await (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas`, {
      headers: adminHeaders, data: { name },
    })).json()) as { id: string };
  const tagged = await create(`Tagged persona ${suffix}`);
  await create(`Plain persona ${suffix}`);
  const tagName = `Safety ${suffix}`;
  const renamed = `Safety case ${suffix}`;
  const replacement = `Regulatory ${suffix}`;

  await test.step("a tag is added from the record's header and survives a reload", async () => {
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${tagged.id}`);
    const box = page.getByRole("combobox", { name: "Tags" });
    await box.fill(tagName);
    // The chip shows at once and is saved in the background: wait for the save before reloading.
    const saved = page.waitForResponse((r) => r.url().includes("/tags") && r.request().method() === "PUT" && r.ok());
    await page.getByRole("option", { name: `Add tag "${tagName}"` }).click();
    await expect(page.getByRole("button", { name: `Remove tag ${tagName}` })).toBeVisible();
    await saved;
    await page.reload();
    await expect(page.getByRole("button", { name: `Remove tag ${tagName}` })).toBeVisible();
  });

  await test.step("the tag shows in the record's Activity tab", async () => {
    await page.getByRole("tab", { name: "Activity" }).click();
    await expect(page.getByText(`added the tag "${tagName}"`)).toBeVisible();
  });

  await test.step("the People list is narrowed by the tag", async () => {
    await page.goto(`/projects/${project.id}/modules/stakeholders/people?kind=persona`);
    await expect(page.getByText(`Plain persona ${suffix}`)).toBeVisible();
    await page.getByRole("button", { name: "Tags", exact: true }).click();
    await page.getByRole("checkbox", { name: tagName }).check();
    await page.keyboard.press("Escape");
    await expect(page.getByText(`Tagged persona ${suffix}`)).toBeVisible();
    await expect(page.getByText(`Plain persona ${suffix}`)).toBeHidden();
  });

  await test.step("Project Admin renames the tag and every record shows the new name", async () => {
    await page.goto(`/projects/${project.id}/admin/tags`);
    await page.getByRole("button", { name: tagName, exact: true }).click();
    await page.getByRole("menuitem", { name: `Rename ${tagName}` }).click();
    const dialog = page.getByRole("dialog", { name: `Rename ${tagName}` });
    await dialog.getByRole("textbox").fill(renamed);
    await dialog.getByRole("button", { name: "Save name" }).click();
    await expect(page.getByText("Tag renamed.")).toBeVisible();
    await expect(page.getByRole("table", { name: "Tags", exact: true }).getByText(renamed)).toBeVisible();
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${tagged.id}`);
    await expect(page.getByRole("button", { name: `Remove tag ${renamed}` })).toBeVisible();
  });

  await test.step("a previewed reclassify moves the record to another tag", async () => {
    await page.goto(`/projects/${project.id}/admin/tags`);
    await page.getByRole("textbox", { name: "New tag" }).fill(replacement);
    await page.getByRole("button", { name: "Add tag" }).click();
    await expect(page.getByText("Tag added.")).toBeVisible();
    await page.getByRole("button", { name: renamed, exact: true }).click();
    await page.getByRole("menuitem", { name: `Reclassify records tagged ${renamed}` }).click();
    const dialog = page.getByRole("dialog", { name: `Reclassify records tagged "${renamed}"` });
    await dialog.getByRole("button", { name: "Add these tags" }).click();
    await page.getByRole("checkbox", { name: replacement }).check();
    await page.keyboard.press("Escape");
    await expect(dialog.getByRole("button", { name: "Apply" })).toBeDisabled();
    await dialog.getByRole("button", { name: "Preview" }).click();
    await expect(dialog.getByText("1 record matched: 1 tag addition and 1 removal.")).toBeVisible();
    await dialog.getByRole("button", { name: "Apply" }).click();
    await expect(page.getByText("Reclassified 1 record.")).toBeVisible();
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${tagged.id}`);
    await expect(page.getByRole("button", { name: `Remove tag ${replacement}` })).toBeVisible();
    await expect(page.getByRole("button", { name: `Remove tag ${renamed}` })).toBeHidden();
  });

  await test.step("deleting a tag needs its name typed and removes it from the record", async () => {
    await page.goto(`/projects/${project.id}/admin/tags`);
    await page.getByRole("button", { name: replacement, exact: true }).click();
    await page.getByRole("menuitem", { name: `Delete ${replacement}` }).click();
    const dialog = page.getByRole("dialog", { name: `Delete tag "${replacement}"?` });
    await expect(dialog.getByText(/removed from 1 record/)).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Delete tag" })).toBeDisabled();
    await dialog.getByRole("textbox").fill(replacement);
    await dialog.getByRole("button", { name: "Delete tag" }).click();
    await expect(page.getByText("Tag deleted. It was removed from 1 record.")).toBeVisible();
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${tagged.id}`);
    await expect(page.getByRole("button", { name: `Remove tag ${replacement}` })).toBeHidden();
  });
});

/**
 * A restricted project accepts only listed tags: the record's box is a picker, an unlisted name is
 * refused with who can add it, and a tag the administrator adds becomes pickable.
 */
test("a restricted project accepts only listed tags", async ({ page }) => {
  const { suffix, project, adminHeaders } = await setUpOrg(page, "TagsRestricted");
  const persona = (await (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas`, {
    headers: adminHeaders, data: { name: `Restricted persona ${suffix}` },
  })).json()) as { id: string };
  const listed = `Listed ${suffix}`;

  await page.goto(`/projects/${project.id}/admin/tags`);
  await page.getByRole("combobox", { name: "Who can add a new tag" }).selectOption("restricted");
  await expect(page.getByText("Tag setting saved.")).toBeVisible();
  await page.getByRole("textbox", { name: "New tag" }).fill(listed);
  await page.getByRole("button", { name: "Add tag" }).click();
  await expect(page.getByText("Tag added.")).toBeVisible();

  await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
  const box = page.getByRole("combobox", { name: "Tags" });
  await expect(box).toHaveAttribute("placeholder", "Choose a tag…");
  await box.fill(`Made up ${suffix}`);
  await box.press("Enter");
  await expect(page.getByRole("alert").filter({ hasText: "Ask a project administrator" })).toBeVisible();
  await box.fill("");
  await box.fill(listed);
  await page.getByRole("option", { name: listed }).click();
  await expect(page.getByRole("button", { name: `Remove tag ${listed}` })).toBeVisible();
});

/**
 * The create form has a Tags field: the tags chosen there are applied once the record exists, and
 * "Tag selected" in the Requirements list adds a tag to several requirements in one previewed step.
 */
test("a create form applies the chosen tags, and the Requirements list tags the selected rows", async ({ page }) => {
  const { suffix, project, adminHeaders } = await setUpOrg(page, "TagsCreate");
  const personaName = `Created with tags ${suffix}`;
  const tag = `Pilot ${suffix}`;

  await test.step("a persona created with a tag carries it", async () => {
    await openPeople(page, project.id, "persona");
    await openNew(page, "Persona");
    const dialog = page.getByRole("dialog", { name: "New Persona (project)" });
    await dialog.getByLabel("Persona name").fill(personaName);
    await dialog.getByRole("combobox", { name: "Tags" }).fill(tag);
    await dialog.getByRole("option", { name: `Add tag "${tag}"` }).click();
    await expect(dialog.getByRole("button", { name: `Remove tag ${tag}` })).toBeVisible();
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByRole("button", { name: personaName }).click();
    await expect(page.getByRole("button", { name: `Remove tag ${tag}` })).toBeVisible();
  });

  await test.step("selected requirements are tagged together after a preview", async () => {
    const category = await (
      await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/components`, {
        headers: adminHeaders, data: { name: "Core", prefix: "COR" },
      })
    ).json();
    const sub = await (
      await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/categories`, {
        headers: adminHeaders, data: { component_id: category.id, name: "General", prefix: "GEN" },
      })
    ).json();
    const names = [`Bulk A ${suffix}`, `Bulk B ${suffix}`];
    for (const name of names) {
      const created = await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/requirements`, {
        headers: adminHeaders, data: { name, component_id: category.id, category_id: sub.id },
      });
      expect(created.ok()).toBeTruthy();
    }
    const created = await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/tags`, {
      headers: adminHeaders, data: { name: `Bulk ${suffix}` },
    });
    expect(created.ok()).toBeTruthy();

    await page.goto(`/projects/${project.id}/requirements`);
    await page.getByRole("button", { name: "List view" }).click();
    for (const name of names) await page.getByLabel(new RegExp(`^Select .*${name}$`)).check();
    await page.getByRole("button", { name: "Tag selected" }).click();
    const dialog = page.getByRole("dialog", { name: "Tag 2 selected requirements" });
    await dialog.getByRole("button", { name: "Add these tags" }).click();
    await page.getByRole("checkbox", { name: `Bulk ${suffix}` }).check();
    await page.keyboard.press("Escape");
    await dialog.getByRole("button", { name: "Preview" }).click();
    await expect(dialog.getByText("2 records matched: 2 tag additions and 0 removals.")).toBeVisible();
    await dialog.getByRole("button", { name: "Apply" }).click();
    await expect(page.getByText("Reclassified 2 records.")).toBeVisible();

    await page.getByRole("button", { name: "Tags", exact: true }).click();
    await page.getByRole("checkbox", { name: `Bulk ${suffix}` }).check();
    await page.keyboard.press("Escape");
    for (const name of names) await expect(page.getByText(name)).toBeVisible();
  });
});

/**
 * A record the organisation owns uses the organisation's tags, kept in Org Admin: tagged from a project
 * that shows it, the tag appears there with its usage, and not in the project's own list.
 */
test("an organisation-owned persona is tagged from a project and managed in Org Admin", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "TagsOrg");
  const persona = (await (await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/personas`, {
    headers: adminHeaders, data: { name: `Org persona ${suffix}` },
  })).json()) as { id: string };
  const tag = `Strategic ${suffix}`;

  await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
  const saved = page.waitForResponse((r) => r.url().includes("/tags") && r.request().method() === "PUT" && r.ok());
  await page.getByRole("combobox", { name: "Tags" }).fill(tag);
  await page.getByRole("option", { name: `Add tag "${tag}"` }).click();
  await saved;

  await page.goto(`/orgs/${org.id}/admin/tags`);
  await expect(page.getByRole("table", { name: "Tags", exact: true }).getByText(tag)).toBeVisible();
  await expect(page.getByRole("table", { name: "Where tags are used: Persona" }).getByText(tag)).toBeVisible();

  await page.goto(`/projects/${project.id}/admin/tags`);
  await expect(page.getByRole("table", { name: "Tags", exact: true })).toHaveCount(0);
  await expect(page.getByText(tag)).toBeHidden();
});
