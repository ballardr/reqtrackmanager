import { expect, type Page, test } from "@playwright/test";

import { installCleanupHook, loginAs, onCleanup, openProject, openProjectGroupPanel, PERSONAS, PROJECT_NAMES, selectProjectAdminGroup } from "./helpers";

/**
 * Logs in as the Alpha/Beta org admin, opens Beta-2's Project Admin, and resets shared Beta-2 state that an earlier
 * timed-out run may have leaked. Each test calls this, so every test runs standalone and in any order.
 *
 * Returns the project id and the session token, captured up front because an API cleanup cannot call
 * `page.evaluate` once a timeout has closed the page.
 */
async function openBeta2Admin(page: Page): Promise<{ projectId: string; sessionToken: string | null }> {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await openProject(page, PROJECT_NAMES.beta2);
  await page.getByRole("link", { name: "Project admin", exact: true }).click();
  const projectId = page.url().match(/projects\/([0-9a-f-]+)\/admin/)![1];
  const sessionToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const sessionHeaders = { Authorization: `Bearer ${sessionToken}` };

  // Reset shared Beta-2 state a timed-out run may have leaked (a timeout closes the page before an in-body `finally`
  // can revert through the API): reset terminology, and drop any required "Priority <timestamp>" field from an
  // earlier run.
  await page.request.put(`http://localhost:8000/api/v1/projects/${projectId}/terminology`, {
    headers: sessionHeaders, data: { terminology: {} },
  });
  const leftoverFields: { id: string; name: string }[] = await page.request
    .get(`http://localhost:8000/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`, { headers: sessionHeaders })
    .then((r) => r.json());
  for (const field of leftoverFields.filter((f) => /^(Priority|Safety critical) \d+$/.test(f.name))) {
    await page.request.delete(`http://localhost:8000/api/v1/projects/${projectId}/custom-fields/${field.id}`, {
      headers: sessionHeaders,
    });
  }
  await page.reload();
  return { projectId, sessionToken };
}

/**
 * Job to be done: per-project custom fields of all four types (C-C-01, C-C-02), project group membership management
 * (C-U-11), and per-project terminology overrides (C-C-03).
 *
 * Uses Beta-2. The terminology change is reverted at the end of its test, since it is a shared, persistent project
 * setting that other specs' nav-label assertions would see. The four custom fields get a per-run timestamp suffix:
 * Custom Fields has no server-side name uniqueness, so a fixed name would leave every earlier run's same-named
 * fields behind for other specs sharing the project.
 *
 * Split into three independent tests, each setting up and resetting state through `openBeta2Admin`, so a test stays
 * within the default 30s budget under load. The `global-state-mutators` project runs them one at a time
 * (`workers: 1`).
 */
test.describe("project admin: custom fields, groups, and terminology", () => {
  installCleanupHook();

  test("custom fields: each of the four types appears on the requirement form and can be deleted", async ({ page }) => {
    const suffix = Date.now();
    const verificationMethodField = `Verification method ${suffix}`;
    const detailedRationaleField = `Detailed rationale ${suffix}`;
    const safetyCriticalField = `Safety critical ${suffix}`;
    const priorityField = `Priority ${suffix}`;
    const { projectId, sessionToken } = await openBeta2Admin(page);

    // Runs in afterEach (also on failure/timeout) — see installCleanupHook.
    onCleanup(async (request) => {
      // Defensive backstop: a direct API call, so cleanup runs even if an assertion throws part-way through creating or
      // deleting these fields. `priorityField` is required, so a stuck "Priority ..." field with no default value leaves
      // the "Create" button permanently disabled for every spec that creates a requirement on Beta-2.
      // `safetyCriticalField` is not required but is swept here with it.
      const token = sessionToken;
      if (token && projectId) {
        const authHeaders = { Authorization: `Bearer ${token}` };
        const fields: { id: string; name: string }[] = await request
          .get(`http://localhost:8000/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`, {
            headers: authHeaders,
          })
          .then((r) => r.json())
          .catch(() => []);
        await Promise.all(
          fields
            .filter((f) => f.name === safetyCriticalField || f.name === priorityField)
            .map((f) =>
              request
                .delete(`http://localhost:8000/api/v1/projects/${projectId}/custom-fields/${f.id}`, { headers: authHeaders })
                .catch(() => {})
            )
        );
      }
    });
    await test.step("create a custom field of each type", async () => {
      // Custom fields sit in the merged "Fields & actions" tab.
      await selectProjectAdminGroup(page, "Fields & actions");

      // The section draws no empty fields: "New field" opens the dialog the field is made in.
      await expect(page.getByLabel("Field name", { exact: true })).toHaveCount(0);
      const fieldDialog = page.getByRole("dialog", { name: "New field" });
      /** Makes one field through the dialog, then waits for the dialog to close. */
      async function createField(name: string, type: string, extras?: () => Promise<void>) {
        await page.getByRole("button", { name: "New field", exact: true }).click();
        await fieldDialog.getByLabel("Field name", { exact: true }).fill(name);
        await fieldDialog.getByLabel("Field type", { exact: true }).selectOption(type);
        await extras?.();
        await fieldDialog.getByRole("button", { name: "Add", exact: true }).click();
        await expect(fieldDialog).toHaveCount(0);
        await expect(page.getByText(name)).toBeVisible();
      }

      await createField(verificationMethodField, "short_text");
      await createField(detailedRationaleField, "long_text");
      await createField(safetyCriticalField, "checkbox");
      await createField(priorityField, "list", async () => {
        await fieldDialog.getByLabel("Options (comma separated)", { exact: true }).fill("Low, Medium, High");
        await fieldDialog.getByLabel("required", { exact: true }).check();
      });
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
  });

  test("project groups: member add/remove, nesting, new group, and org-group role grants", async ({ page }) => {
    const { projectId, sessionToken } = await openBeta2Admin(page);

    // A project has no auto-created group, so this spec creates its own throwaway group up front through the API (as
    // with the `token`/`projectId` resolved above).
    const memberGroupName = await test.step("create a project group to exercise member add/remove and org-group nesting against", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const groupName = `E2E Beta-2 Group ${Date.now()}`;
      // `ProjectGroupCreate` takes no role: the group is created bare, which suits the steps below (member add/remove,
      // the `?openGroup=` deep link, org-group nesting) since none exercise its role.
      await page.request.post(`http://localhost:8000/api/v1/projects/${projectId}/groups`, {
        headers: { Authorization: `Bearer ${token}` }, data: { name: groupName },
      });
      // ProjectAdminPage fetches project groups once on mount — the group
      // just created via a direct API call isn't in that state until
      // reloaded.
      await page.reload();
      return groupName;
    });

    await test.step("add and remove a project group member", async () => {
      await selectProjectAdminGroup(page, "Project groups");
      // Beta-2 is a shared, persistent project (see this file's docstring) that accumulates a group per run with no reseed
      // in between. The Groups tab paginates (`GROUPS_PAGE_SIZE`, `ProjectAdminPage.tsx`), so without narrowing to this
      // run's group by name, enough prior runs push the new row off the first page and `openProjectGroupPanel` finds no row.
      await page.getByPlaceholder("Search by name").fill(memberGroupName);
      await page.waitForLoadState("networkidle");
      // Each group row opens a `SidePanel` (docs/decisions.md); its accessible name ("<group> details") scopes every
      // interaction below to it.
      const panel = await openProjectGroupPanel(page, memberGroupName);
      await panel.getByPlaceholder("Type a name to add, or an email to invite…").fill(PERSONAS.memberAlphaBeta.name);
      await page.getByText(PERSONAS.memberAlphaBeta.email).click();
      await expect(panel.getByText(PERSONAS.memberAlphaBeta.name)).toBeVisible();

      const removeButton = panel.locator("li", { hasText: PERSONAS.memberAlphaBeta.email }).getByRole("button");
      await removeButton.click();
      await expect(panel.getByText(PERSONAS.memberAlphaBeta.email)).toHaveCount(0);
      await page.getByRole("button", { name: "Close" }).click();
      // Reset the filter this step introduced — the search box's own state
      // isn't scoped to this step (no reload/navigation follows), and a
      // later step's own `reload()` call closes over whatever it's
      // currently holding (see the "create a new project group" step's own
      // comment on that race). Left non-empty, it would silently replace a
      // later step's own unrelated group list with this narrowed one.
      await page.getByPlaceholder("Search by name").fill("");
      await page.waitForLoadState("networkidle");
    });

    await test.step("?openGroup= deep link opens that group's SidePanel directly", async () => {
      // A real, directly-navigable URL contract (`DirectoryTable`'s
      // `rowHref`, `ProjectAdminPage.tsx`'s own `useSearchParams` effect) —
      // no in-app link currently produces this exact query param (the
      // Members table stopped linking into Groups once it dropped group
      // rows entirely), but the
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
      // The backend accepts `org_group_id` here (add_project_group_member); this step nests an org group from Project
      // Admin, the other surface being OrgAdminPage's "expanded project" panel.
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
      // Same accumulated-groups/pagination reasoning as the "add and remove
      // a project group member" step above — the search box's own state
      // doesn't survive the `page.reload()` just above, so this needs its
      // own narrowing again, not just once per test.
      await page.getByPlaceholder("Search by name").fill(memberGroupName);
      await page.waitForLoadState("networkidle");
      const panel = await openProjectGroupPanel(page, memberGroupName);
      const nestSelect = panel.getByRole("combobox", { name: /Nest an? .*group…/ });
      await nestSelect.selectOption({ label: groupName });
      await nestSelect.locator("xpath=../button").click();
      await expect(panel.getByText(new RegExp(`^${groupName} \\(`))).toBeVisible();

      const orgGroupRow = panel.locator("li", { hasText: groupName });
      await orgGroupRow.getByRole("button").click();
      await expect(panel.getByText(new RegExp(`^${groupName} \\(`))).toHaveCount(0);
      await page.getByRole("button", { name: "Close" }).click();
      // Reset the filter this step introduced — see the "add and remove a
      // project group member" step's own identical comment for why leaving
      // this non-empty would corrupt a later step's own `reload()` race.
      await page.getByPlaceholder("Search by name").fill("");
      await page.waitForLoadState("networkidle");
    });

    // Style guide "Pattern: create panels, popovers, and one door for bulk": the Groups tab has a create form,
    // mirroring Org Admin's "New group" popover against the project-scoped endpoint. A group is created bare (zero
    // roles) (docs/decisions.md); a role is a separate grant made afterwards through the new row's `MultiSelectDropdown`.
    await test.step("create a new project group via the New group popover, then grant it a role", async () => {
      await selectProjectAdminGroup(page, "Project groups");
      const newGroupName = `E2E New Project Group ${Date.now()}`;

      await page.getByRole("button", { name: "New group" }).click();
      const dialog = page.getByRole("dialog", { name: "New group" });
      await expect(dialog.getByRole("button", { name: "Create" })).toBeDisabled();
      // The new-group dialog has only the name field (no role picker).
      await expect(dialog.getByLabel("Role")).toHaveCount(0);
      await dialog.getByPlaceholder("e.g. Reviewers").fill(newGroupName);
      await dialog.getByRole("button", { name: "Create" }).click();

      // Principle 7 — every mutation ends with feedback.
      await expect(page.getByText("Group created")).toBeVisible();
      await expect(dialog).not.toBeVisible();
      // Beta-2 is a shared, persistent project (see this file's docstring) that accumulates a group per run with no
      // reseed, as it does custom fields. The Groups tab paginates (`GROUPS_PAGE_SIZE`, `ProjectAdminPage.tsx`), so
      // without narrowing to this run's group by name, enough prior runs push the new row off the DirectoryTable's first
      // page and this assertion finds no row.
      //
      // `createProjectGroup` triggers the page's shared `reload()`, which re-fetches the Groups tab's unfiltered list at
      // the end of a long chain of awaited requests. `loadGroups` guards against a slower stale fetch overwriting a
      // later filtered one with a request-id ref (docs/decisions.md); waiting for the network to settle first is the
      // ordinary "let the create mutation's refresh finish before searching" sequencing.
      await page.waitForLoadState("networkidle");
      await page.getByPlaceholder("Search by name").fill(newGroupName);
      // The group's Name cell is a real `<button>` (`DirectoryTable`'s
      // `onRowClick`) — the role `MultiSelectDropdown` sits in a sibling
      // `<td>`, so this checks the whole `<tr>`, not just the button itself.
      const row = page.getByRole("button", { name: new RegExp(`^${newGroupName}`) }).locator("xpath=ancestor::tr[1]");
      await expect(row).toContainText("No roles assigned");
      // The Groups tab's `DirectoryTable` type-badges every row: a `ProjectGroup` reads "Project group", distinguishing it
      // from a `ProjectMemberSource` row's "Project" badge (see the member-source coverage below and
      // `project-hierarchy.spec.ts`).
      await expect(row).toContainText("Project group");

      // Grant a role via the row's MultiSelectDropdown, as `ProjectMembersTable`'s Role column does. Uses `.click()`, not
      // `.check()`: the checkbox's accessible name flips from "Grant X to Y" to "Revoke X from Y" once the toggle succeeds,
      // so `.check()`'s re-verification against the original locator can never resolve. The outcome is asserted through a
      // freshly resolved locator, like the `row` assertion below (and project-admin-members.spec.ts).
      await row.getByRole("button", { name: `${newGroupName}'s roles` }).click();
      const roleGroup = page.getByRole("group", { name: `${newGroupName}'s roles` });
      await roleGroup.getByRole("checkbox", { name: `Grant Stakeholder to ${newGroupName}` }).click();
      await expect(row).toContainText("Stakeholder");
      await expect(row).not.toContainText("No roles assigned");
    });

    // The same "Add member" autocomplete (button + `Modal`) that grants a direct role to a user also matches org groups
    // by name: selecting one grants it a role directly (`OrgGroupProjectRole`, `POST .../group-roles`), with no
    // `ProjectGroup` wrapper and no nesting. Distinct from the "nest an org group into a project group" step above.
    await test.step("grant an org group a project role directly, from the Members tab's combined Add member autocomplete", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const authHeaders = { Authorization: `Bearer ${token}` };
      const project = await (
        await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}`, { headers: authHeaders })
      ).json();
      const directGroupName = `E2E Direct Grant Group ${Date.now()}`;
      const orgGroup = await (
        await page.request.post(`http://localhost:8000/api/v1/orgs/${project.organization_id}/groups`, {
          headers: authHeaders, data: { name: directGroupName },
        })
      ).json();
      // The group needs at least one member for the grant to be visible on
      // the Members table at all — an empty group's direct role has no
      // effective member to show it on.
      const orgUsers: { user_id: string; email: string }[] = await page
        .request.get(`http://localhost:8000/api/v1/orgs/${project.organization_id}/users`, { headers: authHeaders })
        .then((r) => r.json());
      const member = orgUsers.find((u) => u.email === PERSONAS.memberAlphaBeta.email)!;
      await page.request.post(
        `http://localhost:8000/api/v1/orgs/${project.organization_id}/groups/${orgGroup.id}/members`,
        { headers: authHeaders, data: { user_id: member.user_id } },
      );

      // Runs in afterEach (also on failure/timeout) — see installCleanupHook.
      onCleanup(async (request) => {
        // Defensive backstop: the step above removes both roles it grants (stakeholder, then member) through the "Remove
        // group" UI. Revoking an already-revoked (group, project, role) grant is a documented no-op 204
        // (test_revoke_of_a_nonexistent_grant_is_a_no_op_204, backend/tests/test_org_group_project_roles.py), so deleting both
        // unconditionally is safe; it matters only if that step fails part-way and would leak a stakeholder/member grant on
        // memberAlphaBeta into other specs sharing Beta-2.
        await Promise.all(
          ["stakeholder", "member"].map((role) =>
            request.delete(
              `http://localhost:8000/api/v1/projects/${projectId}/group-roles/${orgGroup.id}/${role}`,
              { headers: authHeaders },
            )
          )
        );
      });
      await selectProjectAdminGroup(page, "Members");
      // orgGroups is fetched once on mount — the group just created via a
      // direct API call isn't in that state until reloaded (same reason
      // the "nest an org group" step above reloads too).
      await page.reload();

      await page.getByRole("button", { name: "Add member" }).click();
      const dialog = page.getByRole("dialog", { name: "Add member" });
      await dialog.getByPlaceholder("Type a name to add, or an email to invite…").fill(directGroupName);
      const groupOption = dialog.getByRole("option", { name: new RegExp(`^${directGroupName}`) });
      await expect(groupOption).toContainText("Organisation group");
      await groupOption.click();

      // Staged, not yet granted — set this row's own role, then commit.
      await dialog.getByRole("combobox", { name: `Role for ${directGroupName}` }).selectOption("stakeholder");
      await dialog.getByRole("button", { name: "Add 1 member" }).click();
      await expect(dialog).not.toBeVisible();

      // Visible on the group's member's row, naming the granting group (the per-group provenance) and distinguishing this
      // direct grant from the nesting mechanism. The Source column shows a plain-language summary per row; memberAlphaBeta
      // holds no other role on Beta-2 here, so it reads "Group" (not "Direct and group"), and the named-group line is
      // behind the summary's click-to-open popover.
      const memberRow = page.locator("tr", { hasText: PERSONAS.memberAlphaBeta.name });
      await memberRow.getByRole("button", { name: "Group" }).click();
      await expect(
        page
          .getByRole("dialog", { name: `${PERSONAS.memberAlphaBeta.name}'s access sources` })
          .getByText(`Via group '${directGroupName}' (direct)`)
      ).toBeVisible();
      await page.keyboard.press("Escape");

      // The grant made above is also visible and manageable as the group's own row.
      await test.step("the granting group gets its own row, editable and removable", async () => {
        const groupRow = page.getByRole("button", { name: `${directGroupName}'s roles` }).locator("xpath=ancestor::tr[1]");
        await expect(groupRow.getByText("Group", { exact: true })).toBeVisible();
        // A group row's Source cell states "Direct" with no popover: nothing is upstream of the group's own grant to
        // disclose, and the Role column (checked below through the trigger's summary) names the roles it holds.
        // `exact: true` matters: this fixture's group name contains the word "Direct" ("E2E Direct Grant Group ..."), which
        // a substring match against the Name cell's "Group" badge plus name text would also satisfy.
        await expect(groupRow.getByText("Direct", { exact: true })).toBeVisible();
        const rolesButton = groupRow.getByRole("button", { name: `${directGroupName}'s roles` });
        await expect(rolesButton).toHaveText("Stakeholder (only role)");

        // The role dropdown is directly editable from this row — grant a
        // second role the same way `MembersTabGroupRowRoleToggleAndRemove`
        // (ProjectMembersTable.stories.tsx) covers in isolation.
        await rolesButton.click();
        const roleGroup = page.getByRole("group", { name: `${directGroupName}'s roles` });
        await roleGroup.getByRole("checkbox", { name: `Grant Member to ${directGroupName}` }).click();
        await page.keyboard.press("Escape");
        await expect(rolesButton).toHaveText("Stakeholder, Member");

        // "Remove group" (Actions column) revokes every role at once,
        // behind the same Tier-1 ConfirmDialog every other destructive
        // action in this table uses.
        await groupRow.getByRole("button", { name: `${directGroupName}'s actions` }).click();
        await page.getByRole("menuitem", { name: "Remove group" }).click();
        await page.getByRole("dialog", { name: `Remove ${directGroupName} from this project?` })
          .getByRole("button", { name: "Remove group" }).click();
        await expect(page.getByText(`Removed ${directGroupName}'s access.`)).toBeVisible();
        await expect(page.getByRole("button", { name: `${directGroupName}'s roles` })).toHaveCount(0);
        // That direct grant was memberAlphaBeta's only source of access
        // on this project, so their whole row disappears from the
        // effective-members list too, not just the one Source line.
        await expect(memberRow).toHaveCount(0);
      });
    });
  });

  test("terminology: override and revert a term", async ({ page }) => {
    const { projectId, sessionToken } = await openBeta2Admin(page);

    await test.step("override and then revert a terminology term", async () => {
      // The revert at the end is backed by an onCleanup (afterEach, which also runs on failure or timeout; see
      // installCleanupHook) with a direct API call as the backstop, as in the group-roles onCleanup above. Beta-2 is shared
      // and persistent, so if an assertion throws before the UI-driven revert, the override would stay and break every
      // other spec's default-terminology nav-label assertions (e.g. `getByRole("link", { name: "Requirements" })`).
      onCleanup(async (request) => {
        const token = sessionToken;
        if (token) {
          await request
            .put(`http://localhost:8000/api/v1/projects/${projectId}/terminology`, {
              headers: { Authorization: `Bearer ${token}` },
              data: { terminology: {} },
            })
            .catch(() => {});
        }
      });
      // Terminology sits in Overview ("Project settings"), so a tab click is still needed here: Overview is the default
      // tab on a fresh mount, not the active one after "Project groups". Its Save button is "Save terminology", distinct
      // from Overview's "Save settings" button on the same screen.
      await selectProjectAdminGroup(page, "Project settings");
      await page.getByRole("textbox", { name: "Requirement", exact: true }).fill("Spec");
      // Wait for the save itself before reloading — reloading straight
      // after the click can cancel the in-flight PUT.
      await Promise.all([
        page.waitForResponse((r) => r.url().endsWith(`/projects/${projectId}/terminology`) && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save terminology" }).click(),
      ]);
      await page.reload();
      await expect(page.getByRole("textbox", { name: "Requirement", exact: true })).toHaveValue("Spec");

      await page.getByRole("link", { name: "Specs", exact: true }).click();
      await expect(page.url()).toContain("/requirements");

      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("textbox", { name: "Requirement", exact: true }).fill("");
      await page.getByRole("button", { name: "Save terminology" }).click();
    });
  });
});
