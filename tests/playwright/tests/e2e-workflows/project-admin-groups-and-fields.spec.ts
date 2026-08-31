import { expect, test } from "@playwright/test";

import { loginAs, openProjectGroupPanel, PERSONAS, PROJECT_NAMES, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: per-project custom fields of all four types (C-C-01,
 * C-C-02), project group membership management (C-U-11), and per-project
 * terminology overrides (C-C-03).
 *
 * Uses Beta-2. The terminology change is reverted at the end of the test
 * since it's a shared, persistent project setting other specs' nav-label
 * assertions could otherwise be surprised by. The four custom fields are
 * each given a per-run timestamp suffix rather than a fixed name — Custom
 * Fields has no server-side uniqueness constraint on name, so a fixed name
 * re-run against an already-mutated Beta-2 (no reseed in between) doesn't
 * fail outright but does leave every earlier run's own same-named fields
 * behind, which upstream steps and other specs sharing this project can
 * then trip over. A unique name per run avoids that regardless of how many
 * times, or in what order, this spec has run against the current database.
 */
test.describe("project admin: custom fields, groups, and terminology", () => {
  test("all four custom field types, group membership, and a terminology override", async ({ page }) => {
    const suffix = Date.now();
    const verificationMethodField = `Verification method ${suffix}`;
    const detailedRationaleField = `Detailed rationale ${suffix}`;
    const safetyCriticalField = `Safety critical ${suffix}`;
    const priorityField = `Priority ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.beta2).click();
    await page.getByRole("link", { name: "Project admin", exact: true }).click();

    await test.step("create a custom field of each type", async () => {
      // Custom fields now lives inside the merged "Fields & actions" tab
      // (2026-08 UX audit roadmap: Project Admin's 8 tabs -> 5).
      await selectProjectAdminGroup(page, "Fields & actions");

      const fieldNameInput = page.getByPlaceholder("Field name");

      await fieldNameInput.fill(verificationMethodField);
      await expect(fieldNameInput).toHaveValue(verificationMethodField);
      await page.getByRole("combobox").nth(1).selectOption("short_text");
      await page.getByRole("button", { name: "New field" }).click();
      await expect(page.getByText(verificationMethodField)).toBeVisible();

      await fieldNameInput.fill(detailedRationaleField);
      await expect(fieldNameInput).toHaveValue(detailedRationaleField);
      await page.getByRole("combobox").nth(1).selectOption("long_text");
      await page.getByRole("button", { name: "New field" }).click();
      await expect(page.getByText(detailedRationaleField)).toBeVisible();

      await fieldNameInput.fill(safetyCriticalField);
      await expect(fieldNameInput).toHaveValue(safetyCriticalField);
      await page.getByRole("combobox").nth(1).selectOption("checkbox");
      await page.getByRole("button", { name: "New field" }).click();
      await expect(page.getByText(safetyCriticalField)).toBeVisible();

      await fieldNameInput.fill(priorityField);
      await expect(fieldNameInput).toHaveValue(priorityField);
      await page.getByRole("combobox").nth(1).selectOption("list");
      await page.getByPlaceholder("Options (comma separated)").fill("Low, Medium, High");
      await page.getByLabel("Required").check();
      await page.getByRole("button", { name: "New field" }).click();
      await expect(page.getByText(priorityField)).toBeVisible();
      await expect(page.getByText("Required").first()).toBeVisible();
    });

    await test.step("a new custom field shows up on the requirement create form", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("button", { name: "New Requirement" }).click();
      await expect(page.getByText(verificationMethodField)).toBeVisible();
      await expect(page.getByText(priorityField)).toBeVisible();
      await page.keyboard.press("Escape").catch(() => {});
      await page.goto(page.url());
    });

    await test.step("delete a custom field", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Fields & actions");
      const row = page.locator(".row", { hasText: safetyCriticalField });
      await row.getByRole("button").click();
      await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
      await expect(page.getByText(safetyCriticalField)).toHaveCount(0);

      // `priorityField` is `required: true` on a shared, persistent project
      // (Beta-2) — left behind, it blocks every *other* spec's requirement
      // creation on this project (UI or API) that doesn't happen to supply
      // a value for it. Delete it too so this spec's own required-field
      // exercise doesn't leak into unrelated specs sharing Beta-2.
      const priorityRow = page.locator(".row", { hasText: priorityField });
      await priorityRow.getByRole("button").click();
      await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
      await expect(page.getByText(priorityField)).toHaveCount(0);
    });

    // No group is auto-created on project creation any more (follow-up UX
    // batch Phase C, 2026-08-31) — this spec creates its own throwaway
    // group up front (via the API, same as `token`/`projectId` resolution
    // the later "nest an org group" step already needed) rather than
    // reaching for a default "Members" group that no longer exists.
    const { projectId, groupName: memberGroupName } = await test.step("create a project group to exercise member add/remove and org-group nesting against", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const id = page.url().match(/projects\/([0-9a-f-]+)\/admin/)![1];
      const groupName = `E2E Beta-2 Group ${Date.now()}`;
      await page.request.post(`http://localhost:8000/api/v1/projects/${id}/groups`, {
        headers: { Authorization: `Bearer ${token}` }, data: { name: groupName, role: "member" },
      });
      // ProjectAdminPage fetches project groups once on mount — the group
      // just created via a direct API call isn't in that state until
      // reloaded.
      await page.reload();
      return { projectId: id, groupName };
    });

    await test.step("add and remove a project group member", async () => {
      await selectProjectAdminGroup(page, "Project groups");
      // Each group row now opens a `SidePanel` (Phase 5, docs/decisions.md)
      // instead of an always-expanded `CollapsibleSection` accordion — the
      // panel's own accessible name ("<group> details") scopes every
      // interaction below to it.
      const panel = await openProjectGroupPanel(page, memberGroupName);
      await panel.getByPlaceholder("Type a name to add, or an email to invite…").fill(PERSONAS.memberAlphaBeta.name);
      await page.getByText(PERSONAS.memberAlphaBeta.email).click();
      await expect(panel.getByText(PERSONAS.memberAlphaBeta.name)).toBeVisible();

      const removeButton = panel.locator("li", { hasText: PERSONAS.memberAlphaBeta.email }).getByRole("button");
      await removeButton.click();
      await expect(panel.getByText(PERSONAS.memberAlphaBeta.email)).toHaveCount(0);
      await page.getByRole("button", { name: "Close" }).click();
    });

    await test.step("?openGroup= deep link opens that group's SidePanel directly", async () => {
      // A real, directly-navigable URL contract (`DirectoryTable`'s
      // `rowHref`, `ProjectAdminPage.tsx`'s own `useSearchParams` effect) —
      // no in-app link currently produces this exact query param (the
      // Members table stopped linking into Groups once it dropped group
      // rows entirely, Phase D, follow-up UX batch, 2026-08-31), but the
      // deep link itself is still live, bookmarkable behavior worth
      // pinning directly rather than only indirectly via whatever produces
      // it at any given time.
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const projectGroups: { id: string; name: string }[] = await page
        .request.get(`http://localhost:8000/api/v1/projects/${projectId}/groups`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        .then((r) => r.json());
      const group = projectGroups.find((g) => g.name === memberGroupName)!;

      await page.goto(`/projects/${projectId}/admin/groups?openGroup=${group.id}`);
      const panel = page.getByRole("dialog", { name: `${memberGroupName} details` });
      await expect(panel).toBeVisible();
      // The param is cleared once consumed (`ProjectAdminPage.tsx`'s own
      // `useSearchParams` effect), so browser-back doesn't reopen it
      // unexpectedly — a real URL, not client-only state.
      await expect(page).not.toHaveURL(/openGroup=/);
      await page.getByRole("button", { name: "Close" }).click();
    });

    await test.step("nest an org group into a project group directly from Project Admin", async () => {
      // The backend has always supported org_group_id here (add_project_group_member);
      // this closes the UX gap where no frontend surface sent it — only
      // OrgAdminPage's own "expanded project" panel could, previously.
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const project = await (
        await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
      ).json();
      const groupName = `E2E Nest Into Project ${Date.now()}`;
      await page.request.post(`http://localhost:8000/api/v1/orgs/${project.organization_id}/groups`, {
        headers: { Authorization: `Bearer ${token}` }, data: { name: groupName },
      });
      // ProjectAdminPage fetches org groups once on mount — the group just
      // created via a direct API call isn't in that state until reloaded.
      await page.reload();

      await selectProjectAdminGroup(page, "Project groups");
      const panel = await openProjectGroupPanel(page, memberGroupName);
      const nestSelect = panel.getByRole("combobox", { name: /Nest an? .*group…/ });
      await nestSelect.selectOption({ label: groupName });
      await nestSelect.locator("xpath=../button").click();
      await expect(panel.getByText(new RegExp(`^${groupName} \\(`))).toBeVisible();

      const orgGroupRow = panel.locator("li", { hasText: groupName });
      await orgGroupRow.getByRole("button").click();
      await expect(panel.getByText(new RegExp(`^${groupName} \\(`))).toHaveCount(0);
      await page.getByRole("button", { name: "Close" }).click();
    });

    // Style guide "Pattern: create panels, popovers, and one door for
    // bulk" — closes the 2026-08 UX audit's "Groups tab manages membership
    // only, no create form at all" finding. Mirrors Org Admin's own "New
    // group" popover coverage, against the project-scoped endpoint (which
    // also requires a role up front — `PATCH .../groups/{id}`, Phase 5,
    // makes it correctable afterward, but creation stays role-required).
    await test.step("create a new project group via the New group popover", async () => {
      await selectProjectAdminGroup(page, "Project groups");
      const newGroupName = `E2E New Project Group ${Date.now()}`;

      await page.getByRole("button", { name: "New group" }).click();
      const dialog = page.getByRole("dialog", { name: "New group" });
      await expect(dialog.getByRole("button", { name: "Create" })).toBeDisabled();
      await dialog.getByPlaceholder("e.g. Reviewers").fill(newGroupName);
      await dialog.getByLabel("Role").selectOption("stakeholder");
      await dialog.getByRole("button", { name: "Create" }).click();

      // Principle 7 — every mutation ends with feedback.
      await expect(page.getByText("Group created")).toBeVisible();
      await expect(dialog).not.toBeVisible();
      // The group's Name cell is a real `<button>` (`DirectoryTable`'s
      // `onRowClick`) — the Role badge sits in a sibling `<td>`, so this
      // checks the whole `<tr>`, not just the button itself.
      const row = page.getByRole("button", { name: new RegExp(`^${newGroupName}`) }).locator("xpath=ancestor::tr[1]");
      await expect(row).toContainText("Stakeholder");
    });

    await test.step("override and then revert a terminology term", async () => {
      // Terminology now lives inside Overview ("Project settings") rather
      // than its own tab (2026-08 UX audit roadmap: Project Admin's 8
      // tabs -> 5) — still needs a tab click since we're currently on
      // "Project groups" from the step above (Overview is only the
      // *default* tab on a fresh mount, not the currently-active one
      // here). Its own Save button is labelled "Save terminology",
      // distinct from Overview's own "Save settings" button now that both
      // sit on the same screen.
      await selectProjectAdminGroup(page, "Project settings");
      await page.getByPlaceholder("requirement").fill("Spec");
      await page.getByRole("button", { name: "Save terminology" }).click();
      await page.reload();
      await expect(page.getByPlaceholder("requirement")).toHaveValue("Spec");

      await page.getByRole("link", { name: "Specs", exact: true }).click();
      await expect(page.url()).toContain("/requirements");

      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByPlaceholder("requirement").fill("");
      await page.getByRole("button", { name: "Save terminology" }).click();
    });
  });
});
