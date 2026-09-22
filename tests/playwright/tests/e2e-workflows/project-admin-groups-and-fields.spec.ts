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
    let projectId = "";

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.beta2).click();
    await page.getByRole("link", { name: "Project admin", exact: true }).click();
    projectId = page.url().match(/projects\/([0-9a-f-]+)\/admin/)![1];

    try {
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
    } finally {
      // Defensive backstop, same reasoning as the terminology and
      // group-roles `finally` blocks below — a direct API call, not the UI
      // steps above, so cleanup still runs even if an assertion throws
      // mid-way through creating/deleting these fields. This one matters
      // more than most: `priorityField` is a *required* field, and this
      // exact gap (an earlier interrupted run leaving 1-3 required
      // "Priority ..." fields stuck on Beta-2, each with no default value)
      // was found live while verifying an unrelated dependency bump —
      // every other spec that creates a plain requirement on Beta-2 got a
      // permanently-disabled "Create" button until the stuck fields were
      // found and deleted by hand. `safetyCriticalField` isn't required
      // and can't block anything, but it's cheap to sweep up alongside
      // `priorityField` here rather than leave it as one more never-used
      // row on an already heavily-accumulated shared project.
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token")).catch(() => null);
      if (token && projectId) {
        const authHeaders = { Authorization: `Bearer ${token}` };
        const fields: { id: string; name: string }[] = await page
          .request.get(`http://localhost:8000/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`, {
            headers: authHeaders,
          })
          .then((r) => r.json())
          .catch(() => []);
        await Promise.all(
          fields
            .filter((f) => f.name === safetyCriticalField || f.name === priorityField)
            .map((f) =>
              page.request
                .delete(`http://localhost:8000/api/v1/projects/${projectId}/custom-fields/${f.id}`, { headers: authHeaders })
                .catch(() => {})
            )
        );
      }
    }

    // No group is auto-created on project creation any more (follow-up UX
    // batch Phase C, 2026-08-31) — this spec creates its own throwaway
    // group up front (via the API, same as the `token`/`projectId` resolved
    // above) rather than reaching for a default "Members" group that no
    // longer exists.
    const memberGroupName = await test.step("create a project group to exercise member add/remove and org-group nesting against", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const groupName = `E2E Beta-2 Group ${Date.now()}`;
      // PR7 of the members/groups directory rework plan: `ProjectGroupCreate`
      // no longer accepts a role at all — this group is created bare, which
      // is fine here since none of the steps below (member add/remove,
      // the `?openGroup=` deep link, org-group nesting) exercise its role.
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
      // Beta-2 is a shared, persistent project (see this file's own
      // docstring) that accumulates a group per run of this spec with no
      // reseed in between — the Groups tab paginates (`GROUPS_PAGE_SIZE`,
      // `ProjectAdminPage.tsx`), so without narrowing to this run's own
      // group by name first, enough prior runs push the just-created row
      // off the first page and `openProjectGroupPanel` below times out
      // finding no row at all, not a wrong one — the same reasoning the
      // "create a new project group" step further down already applies to
      // its own row lookup.
      await page.getByPlaceholder("Search by name").fill(memberGroupName);
      await page.waitForLoadState("networkidle");
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

    // Style guide "Pattern: create panels, popovers, and one door for
    // bulk" — closes the 2026-08 UX audit's "Groups tab manages membership
    // only, no create form at all" finding. Mirrors Org Admin's own "New
    // group" popover coverage, against the project-scoped endpoint. PR7 of
    // the members/groups directory rework plan (docs/decisions.md) dropped
    // the role picker this modal used to have — a group is created bare
    // (zero roles) and a role is a separate grant made afterward via the
    // new row's own `MultiSelectDropdown`, not at creation time.
    await test.step("create a new project group via the New group popover, then grant it a role", async () => {
      await selectProjectAdminGroup(page, "Project groups");
      const newGroupName = `E2E New Project Group ${Date.now()}`;

      await page.getByRole("button", { name: "New group" }).click();
      const dialog = page.getByRole("dialog", { name: "New group" });
      await expect(dialog.getByRole("button", { name: "Create" })).toBeDisabled();
      // No role picker any more (PR7) — just the name field.
      await expect(dialog.getByLabel("Role")).toHaveCount(0);
      await dialog.getByPlaceholder("e.g. Reviewers").fill(newGroupName);
      await dialog.getByRole("button", { name: "Create" }).click();

      // Principle 7 — every mutation ends with feedback.
      await expect(page.getByText("Group created")).toBeVisible();
      await expect(dialog).not.toBeVisible();
      // Beta-2 is a shared, persistent project (see this file's own
      // docstring) that accumulates a group per run of this spec with no
      // reseed in between, the same way it accumulates custom fields —
      // the Groups tab paginates (`GROUPS_PAGE_SIZE`, `ProjectAdminPage
      // .tsx`), so without narrowing to this run's own group by name
      // first, enough prior runs push the just-created row off the
      // DirectoryTable's first page and this assertion times out finding
      // no row at all, not a wrong one.
      //
      // `createProjectGroup` triggers this page's shared `reload()` (every
      // mutation handler on this page does), which itself re-fetches the
      // Groups tab's own unfiltered list as one step in a long sequential
      // chain of unrelated awaited requests (project/stages/components/
      // categories/custom fields/...). This used to race a search typed
      // into the box before that chain settled — `reload()`'s own slower,
      // stale-search fetch could resolve after a fresh, filtered one and
      // silently overwrite it with the unfiltered list. `loadGroups` now
      // guards against that with a request-id ref (Platform review 2026-09
      // Phase 4, docs/decisions.md), so this is no longer a live race —
      // waiting for the network to settle first here is just the ordinary
      // "let the create mutation's own refresh finish before searching"
      // sequencing, not a workaround for a bug still open.
      await page.waitForLoadState("networkidle");
      await page.getByPlaceholder("Search by name").fill(newGroupName);
      // The group's Name cell is a real `<button>` (`DirectoryTable`'s
      // `onRowClick`) — the role `MultiSelectDropdown` sits in a sibling
      // `<td>`, so this checks the whole `<tr>`, not just the button itself.
      const row = page.getByRole("button", { name: new RegExp(`^${newGroupName}`) }).locator("xpath=ancestor::tr[1]");
      await expect(row).toContainText("No roles assigned");
      // PR5 of the members/groups directory rework plan: the Groups tab's
      // `DirectoryTable` now type-badges every row — a real `ProjectGroup`
      // reads "Project group", distinguishing it from a `ProjectMemberSource`
      // row's "Project" badge (see the dedicated member-source coverage
      // below, and `project-hierarchy.spec.ts`'s own member-source steps).
      await expect(row).toContainText("Project group");

      // Grant a role via the new per-row MultiSelectDropdown (PR7) —
      // mirrors `ProjectMembersTable`'s own Role column interaction. Uses
      // `.click()`, not `.check()`: the checkbox's own accessible name
      // flips from "Grant X to Y" to "Revoke X from Y" the moment the
      // toggle succeeds (`ProjectMembersTable`'s pre-existing pattern,
      // reused here), so `.check()`'s built-in re-verification against
      // that same original locator can never resolve — the working
      // pattern elsewhere in this suite (project-admin-members.spec.ts)
      // always clicks, then asserts the outcome via a separate, freshly
      // resolved locator, exactly like the `row` assertion below.
      await row.getByRole("button", { name: `${newGroupName}'s roles` }).click();
      const roleGroup = page.getByRole("group", { name: `${newGroupName}'s roles` });
      await roleGroup.getByRole("checkbox", { name: `Grant Stakeholder to ${newGroupName}` }).click();
      await expect(row).toContainText("Stakeholder");
      await expect(row).not.toContainText("No roles assigned");
    });

    // PR5 of the members/groups directory rework plan: the same "Add
    // member" autocomplete (button + `Modal`, PR3) that already grants a
    // direct role to a user also matches org groups by name — selecting
    // one grants it a role *directly* via PR4's new mechanism
    // (`OrgGroupProjectRole`, `POST .../group-roles`), with no
    // `ProjectGroup` wrapper created and no nesting involved. Distinct from
    // the "nest an org group into a project group" step above, which is
    // the older, still-supported composition mechanism.
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

      try {
        await selectProjectAdminGroup(page, "Members");
        // orgGroups is fetched once on mount — the group just created via a
        // direct API call isn't in that state until reloaded (same reason
        // the "nest an org group" step above reloads too).
        await page.reload();

        await page.getByRole("button", { name: "Add member" }).click();
        const dialog = page.getByRole("dialog", { name: "Add member" });
        await dialog.getByPlaceholder("Type a name to add, or an email to invite…").fill(directGroupName);
        const groupOption = dialog.getByRole("option", { name: new RegExp(`^${directGroupName}`) });
        await expect(groupOption).toContainText("Org group");
        await groupOption.click();

        // Staged, not yet granted — set this row's own role, then commit.
        await dialog.getByRole("combobox", { name: `Role for ${directGroupName}` }).selectOption("stakeholder");
        await dialog.getByRole("button", { name: "Add 1 member" }).click();
        await expect(dialog).not.toBeVisible();

        // Visible on the group's member's own row, naming the granting
        // group directly (PR1's per-group provenance) and distinguishing
        // this direct grant from the nesting mechanism's own wording. The
        // Source column now shows a plain-language summary per row
        // (platform review 2026-09 follow-up) rather than this line being
        // always-visible in the cell — memberAlphaBeta holds no other role
        // on Beta-2 at this point, so the summary reads "Group" (not
        // "Direct and group"), and the actual named-group line lives
        // behind that summary's own click-to-open popover.
        const memberRow = page.locator("tr", { hasText: PERSONAS.memberAlphaBeta.name });
        await memberRow.getByRole("button", { name: "Group" }).click();
        await expect(
          page
            .getByRole("dialog", { name: `${PERSONAS.memberAlphaBeta.name}'s access sources` })
            .getByText(`Via group '${directGroupName}' (direct)`)
        ).toBeVisible();
        await page.keyboard.press("Escape");

        // Phase 6 (docs/platform-review-2026-09-plan.md): the grant just
        // made above is now also visible and manageable as the group's own
        // row — previously there was no way to see, edit, or remove it
        // except by reaching into a member's Source line above, or calling
        // the DELETE endpoint by hand (as this test's own `finally` cleanup
        // below used to be the only way to do).
        await test.step("the granting group gets its own row, editable and removable", async () => {
          const groupRow = page.getByRole("button", { name: `${directGroupName}'s roles` }).locator("xpath=ancestor::tr[1]");
          await expect(groupRow.getByText("Group", { exact: true })).toBeVisible();
          // A group row's Source cell just states "Direct" plainly, no
          // popover (platform review 2026-09 follow-up) — there's nothing
          // upstream of the group's own grant to disclose, and the Role
          // column (checked below via the trigger's own summary) already
          // names which roles it holds. `exact: true` matters here
          // specifically: this fixture's own group name contains the
          // literal word "Direct" ("E2E Direct Grant Group ..."), which a
          // substring match against the Name cell's combined "Group" badge
          // + name text would also satisfy.
          await expect(groupRow.getByText("Direct", { exact: true })).toBeVisible();
          const rolesButton = groupRow.getByRole("button", { name: `${directGroupName}'s roles` });
          await expect(rolesButton).toHaveAttribute("title", "Stakeholder");

          // The role dropdown is directly editable from this row — grant a
          // second role the same way `MembersTabGroupRowRoleToggleAndRemove`
          // (ProjectMembersTable.stories.tsx) covers in isolation.
          await rolesButton.click();
          const roleGroup = page.getByRole("group", { name: `${directGroupName}'s roles` });
          await roleGroup.getByRole("checkbox", { name: `Grant Member to ${directGroupName}` }).click();
          await page.keyboard.press("Escape");
          await expect(rolesButton).toHaveAttribute("title", "Stakeholder, Member");

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
      } finally {
        // Defensive backstop, not the primary cleanup any more — the step
        // above already removes both roles it grants (stakeholder, then
        // member) through the real "Remove group" UI. Revoking an
        // already-revoked (group, project, role) grant is a documented
        // no-op 204 (test_revoke_of_a_nonexistent_grant_is_a_no_op_204,
        // backend/tests/test_org_group_project_roles.py), so deleting both
        // unconditionally stays safe even when the step above already
        // removed them — this only matters if that step fails partway
        // through, which would otherwise leak a real stakeholder/member
        // grant on memberAlphaBeta into other specs sharing Beta-2.
        await Promise.all(
          ["stakeholder", "member"].map((role) =>
            page.request.delete(
              `http://localhost:8000/api/v1/projects/${projectId}/group-roles/${orgGroup.id}/${role}`,
              { headers: authHeaders },
            )
          )
        );
      }
    });

    await test.step("override and then revert a terminology term", async () => {
      // The revert at the end is wrapped in try/finally, with a direct API
      // call as the actual backstop (not just the UI steps below) — same
      // reasoning as the group-roles `finally` above. Beta-2 is shared and
      // persistent (this file's own docstring), so if any assertion in
      // this step throws before the UI-driven revert runs, this override
      // would otherwise stick around and break every *other* spec's
      // default-terminology nav-label assertions until someone notices and
      // resets it by hand — which is exactly what happened here once
      // already (found while verifying an unrelated dependency bump: this
      // step had thrown mid-run in an earlier session, leaving Beta-2's
      // `terminology` at `{"requirement": "Spec"}` and causing every
      // subsequent run — including a plain `getByRole("link", { name:
      // "Requirements" })` in this same file's own first test.step — to
      // fail immediately, with a symptom that looked unrelated to
      // terminology at all).
      try {
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
      } finally {
        const token = await page.evaluate(() => localStorage.getItem("reqtrack_token")).catch(() => null);
        if (token) {
          await page.request
            .put(`http://localhost:8000/api/v1/projects/${projectId}/terminology`, {
              headers: { Authorization: `Bearer ${token}` },
              data: { terminology: {} },
            })
            .catch(() => {});
        }
      }
    });
  });
});
