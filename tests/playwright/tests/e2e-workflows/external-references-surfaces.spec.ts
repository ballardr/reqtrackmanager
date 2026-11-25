import { expect, test } from "@playwright/test";

import { chooseRecordAddition, installCleanupHook } from "./helpers";
import { API_BASE_URL, openNew, openPeople, setUpOrg } from "../modules/stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: record where a record also lives in an outside tool (a Jira issue, a GitHub ticket), open the item from
 * the record, and find records again by the outside system or key.
 *
 * Walks the four surfaces on personas (a module record, so it also shows references need no per-module code): the
 * record's panel (add with a link, edit, remove with a confirmation), the create form's field (references are added once
 * the record exists), and the list's External references column and filter (a system and part of a key).
 *
 * Disposable organisation created through the API and removed afterwards, so the spec depends on no seeded state and can
 * be repeated against the same database. The organisation's default systems (Jira, GitHub, ...) are the ones used.
 */
test("add, edit and remove a reference, create with one, then filter the list by it", async ({ page }) => {
  test.setTimeout(150_000);
  const { suffix, project, adminHeaders } = await setUpOrg(page, "References");
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}`;
  const createPersona = async (name: string) =>
    (await (await page.request.post(`${base}/modules/stakeholders/personas`, { headers: adminHeaders, data: { name } })).json()) as { id: string };
  const referenced = await createPersona(`Referenced persona ${suffix}`);
  await createPersona(`Plain persona ${suffix}`);
  const key = `PROJ-${suffix}`;
  const link = `https://tracker.example/browse/${key}`;
  const changedKey = `PROJ-${suffix}-B`;
  const groupName = "Tags, components and references";

  await test.step("a reference is added from the record's page and opens its item in a new tab", async () => {
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${referenced.id}`);
    await chooseRecordAddition(page, "Add external reference");
    const dialog = page.getByRole("dialog", { name: "Add an external reference" });
    await expect(dialog.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    await dialog.getByRole("combobox", { name: "System" }).selectOption({ label: "Jira" });
    await dialog.getByRole("textbox", { name: "Key" }).fill(key);
    await dialog.getByRole("textbox", { name: "Link" }).fill(link);
    await dialog.getByRole("combobox", { name: "Role" }).selectOption({ label: "Delivery" });
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("Reference added.")).toBeVisible();
    const chip = page.getByRole("group", { name: groupName }).getByRole("link", { name: `Open Jira: ${key} in a new tab` });
    await expect(chip).toHaveAttribute("href", link);
    await expect(chip).toHaveAttribute("target", "_blank");
    await expect(chip).toHaveAttribute("rel", /noopener/);
    await page.reload();
    await expect(page.getByRole("group", { name: groupName }).getByText("Delivery")).toBeVisible();
  });

  await test.step("a refused link is reported and nothing is added", async () => {
    await chooseRecordAddition(page, "Add external reference");
    const dialog = page.getByRole("dialog", { name: "Add an external reference" });
    await dialog.getByRole("combobox", { name: "System" }).selectOption({ label: "Jira" });
    await dialog.getByRole("textbox", { name: "Key" }).fill(`BAD-${suffix}`);
    await dialog.getByRole("textbox", { name: "Link" }).fill("javascript:alert(1)");
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(dialog.getByText(/Could not save the reference/)).toBeVisible();
    // Nothing was stored: a reload closes the dialog and the record still has no reference.
    await page.reload();
    await expect(page.getByText(`BAD-${suffix}`)).toHaveCount(0);
  });

  await test.step("a reference is edited in place", async () => {
    await page.getByRole("button", { name: `Edit reference Jira: ${key}` }).click();
    const dialog = page.getByRole("dialog", { name: "Edit external reference" });
    await dialog.getByRole("textbox", { name: "Key" }).fill(changedKey);
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("Reference saved.")).toBeVisible();
    await expect(page.getByRole("button", { name: `Edit reference Jira: ${changedKey}` })).toBeVisible();
  });

  await test.step("removing asks first, and then the reference is gone", async () => {
    await page.getByRole("button", { name: `Remove reference Jira: ${changedKey}` }).click();
    const dialog = page.getByRole("dialog", { name: "Remove this reference?" });
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("button", { name: `Edit reference Jira: ${changedKey}` })).toBeVisible();
    await page.getByRole("button", { name: `Remove reference Jira: ${changedKey}` }).click();
    await page.getByRole("dialog", { name: "Remove this reference?" }).getByRole("button", { name: "Remove", exact: true }).click();
    await expect(page.getByText("Reference removed.")).toBeVisible();
    await expect(page.getByRole("button", { name: `Edit reference Jira: ${changedKey}` })).toHaveCount(0);
  });

  await test.step("the create form's references are added once the record exists", async () => {
    const created = `Created persona ${suffix}`;
    const createdKey = `GH-${suffix}`;
    await openPeople(page, project.id, "persona");
    await openNew(page, "Persona");
    const dialog = page.getByRole("dialog", { name: "New Persona (project)" });
    await dialog.getByLabel("Persona name").fill(created);
    await dialog.getByRole("button", { name: "Add a reference" }).click();
    await dialog.getByRole("combobox", { name: "Reference 1 system" }).selectOption({ label: "GitHub" });
    await dialog.getByRole("textbox", { name: "Reference 1 key" }).fill(createdKey);
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("Persona created.")).toBeVisible();
    await page.getByRole("button", { name: created }).click();
    await expect(page.getByRole("group", { name: groupName }).getByText(createdKey)).toBeVisible();
  });

  await test.step("the list shows a column and is narrowed by system and by key", async () => {
    const systems = (await (await page.request.get(`${base}/external-systems`, { headers: adminHeaders })).json()) as { id: string; name: string }[];
    const jira = systems.find((s) => s.name === "Jira")!;
    const listed = `LIST-${suffix}`;
    const added = await page.request.post(`${base}/artefacts/persona/${referenced.id}/external-references`, {
      headers: adminHeaders, data: { system_id: jira.id, key: listed },
    });
    expect(added.ok()).toBeTruthy();

    await openPeople(page, project.id, "persona");
    const row = page.locator("tr", { hasText: `Referenced persona ${suffix}` });
    await expect(page.getByRole("columnheader", { name: "External references" })).toBeVisible();
    await expect(row.getByText(listed)).toBeVisible();
    await expect(page.getByText(`Plain persona ${suffix}`)).toBeVisible();

    await page.getByRole("button", { name: "External system", exact: true }).click();
    await page.getByRole("checkbox", { name: "Jira" }).check();
    await page.keyboard.press("Escape");
    await expect(page.getByText(`Referenced persona ${suffix}`)).toBeVisible();
    await expect(page.getByText(`Plain persona ${suffix}`)).toBeHidden();
    // The Jira reference does not match a key that only a GitHub reference has.
    const keyBox = page.getByRole("textbox", { name: "External key" });
    await keyBox.fill(`GH-${suffix}`);
    await keyBox.press("Tab");
    await expect(page.getByText(`Referenced persona ${suffix}`)).toBeHidden();
    await keyBox.fill(listed.toLowerCase());
    await keyBox.press("Tab");
    await expect(page.getByText(`Referenced persona ${suffix}`)).toBeVisible();
    await expect(page).toHaveURL(/ref_system=Jira/);
    await expect(page).toHaveURL(/ref_key=/);
  });
});
