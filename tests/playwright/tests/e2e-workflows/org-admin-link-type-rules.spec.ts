import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an org admin decides which kinds of record each link type
 * may join ("Can link from" / "Can link to"), which link types each artefact
 * type may use ("By artefact type"), and can delete a link type that is still
 * in use without losing track of its links: move them to another type, or
 * delete them too behind a type-the-name confirmation.
 *
 * Covers: restriction pickers show artefact-type *labels* (never the raw
 * `pain_point` key), save at once with a Toast, persist across a reload and
 * clear back to "Any artefact"; the rules tab limits an artefact type (starting
 * from every link type ticked), refuses to empty a rule, enforces the rule on a
 * new link, and removes it after a confirmation; the delete dialog states what
 * depends on the type, disables a replacement that cannot take the links with
 * its reason, and both exits report what happened.
 *
 * Each test builds its own organisation, so none depends on state left by
 * another test or an earlier run.
 */

const apiBaseUrl = "http://localhost:8000";

function inputWithValue(page: Page, value: string) {
  return page.locator(`input.input[value="${value}"]:not([placeholder])`);
}

function rowOf(page: Page, linkTypeName: string) {
  return inputWithValue(page, linkTypeName).locator("xpath=ancestor::div[contains(@class,'stack')][1]");
}

interface World {
  orgId: string;
  adminEmail: string;
  headers: { Authorization: string };
}

/** A disposable org with an org admin and the Decisions and Context & Strategy modules on. */
async function createWorld(request: APIRequestContext, label: string): Promise<World> {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const adminEmail = `e2e-${label}-admin-${suffix}@example.com`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `E2E Link Rules ${label} ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Link Rules Admin", password: PASSWORD, role: "org_admin" },
  });
  const token = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
  ).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  for (const module of ["decisions", "context_strategy"]) {
    await request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/modules/${module}`, { headers, data: { enabled: true } });
  }
  return { orgId: org.id, adminEmail, headers };
}

async function openLinkTypes(page: Page, world: World) {
  await loginAs(page, world.adminEmail, PASSWORD);
  await page.goto(`/orgs/${world.orgId}/admin`);
  await selectOrgAdminGroup(page, "Projects & workflow");
  await ensureExpanded(page, "Link types");
  await expect(inputWithValue(page, "Depends on")).toBeVisible();
}

async function linkTypesByName(request: APIRequestContext, world: World): Promise<Record<string, { id: string }>> {
  const rows = await (await request.get(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/link-types`, { headers: world.headers })).json();
  return Object.fromEntries(rows.map((row: { forward_name: string; id: string }) => [row.forward_name, row]));
}

test.describe("org admin: link type restrictions, artefact rules and deleting a type in use", () => {
  test("restrictions show labels, save at once, persist and clear back to any", async ({ page }) => {
    const world = await createWorld(page.request, "restrict");
    const name = `E2E Narrow ${Date.now()}`;
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/link-types`, {
      headers: world.headers, data: { forward_name: name, reverse_name: `${name} reverse` },
    });
    await openLinkTypes(page, world);

    await test.step("a module-seeded type shows its restriction as labels, a plain one says Any artefact", async () => {
      await expect(page.getByRole("button", { name: "Can link from: Addresses" })).toHaveText(/Decision/);
      await expect(page.getByRole("button", { name: "Can link to: Addresses" })).toHaveText(/Pain point/);
      await expect(page.getByRole("button", { name: `Can link from: ${name}` })).toHaveText(/Any artefact/);
      await expect(page.getByText("pain_point", { exact: true })).toHaveCount(0);
    });

    await test.step("ticking a kind of record saves at once with a Toast and survives a reload", async () => {
      await page.getByRole("button", { name: `Can link from: ${name}` }).click();
      // `click`, not `check`: the box is controlled and only flips once the save round-trips.
      await page.getByRole("checkbox", { name: `Can link from: ${name}: Requirement` }).click();
      await expect(page.getByText("Link type restriction updated.")).toBeVisible();
      await page.keyboard.press("Escape");
      await page.reload();
      await selectOrgAdminGroup(page, "Projects & workflow");
      await ensureExpanded(page, "Link types");
      await expect(page.getByRole("button", { name: `Can link from: ${name}` })).toHaveText(/Requirement/);
    });

    await test.step("unticking the last kind clears the restriction back to Any artefact", async () => {
      await page.getByRole("button", { name: `Can link from: ${name}` }).click();
      await page.getByRole("checkbox", { name: `Can link from: ${name}: Requirement` }).click();
      await expect(page.getByRole("button", { name: `Can link from: ${name}` })).toHaveText(/Any artefact/);
    });

    await test.step("a type with its own action (Supersedes) offers no restriction pickers", async () => {
      await expect(page.getByText(/Made with its own action/).first()).toBeVisible();
      await expect(page.getByRole("button", { name: "Can link from: Supersedes" })).toHaveCount(0);
    });
  });

  test("by artefact type: limit a type, keep one, enforce it on a new link, remove it after a confirmation", async ({ page }) => {
    const world = await createWorld(page.request, "rules");
    const types = await linkTypesByName(page.request, world);
    await openLinkTypes(page, world);
    await page.getByRole("tab", { name: "By artefact type" }).click();

    await test.step("an unrestricted artefact type reads Any link type", async () => {
      await expect(page.getByRole("button", { name: "Link types allowed for Requirement" })).toHaveText(/Derives from/);
      await expect(page.getByRole("button", { name: "Allow any link type" })).toHaveCount(0);
    });

    await test.step("unticking one link type limits the rule to all the others, with a Toast", async () => {
      await page.getByRole("button", { name: "Link types allowed for Requirement" }).click();
      await page.getByRole("checkbox", { name: "Requirement: Mitigates" }).click();
      await expect(page.getByText("Link rule updated.")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("button", { name: "Allow any link type" })).toHaveCount(1);
      await expect(page.getByRole("button", { name: "Link types allowed for Requirement" })).not.toHaveText(/Mitigates/);
    });

    await test.step("the rule is enforced when a link is made", async () => {
      const project = await (
        await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
          headers: world.headers, data: { organization_id: world.orgId, name: `E2E Rules Project ${Date.now()}`, summary: "" },
        })
      ).json();
      const component = await (
        await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/components`, {
          headers: world.headers, data: { name: "Software", prefix: "SW" },
        })
      ).json();
      const category = await (
        await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/categories`, {
          headers: world.headers, data: { name: "Functional", prefix: "FN", component_id: component.id },
        })
      ).json();
      const make = async (reqName: string) =>
        (
          await (
            await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements`, {
              headers: world.headers,
              data: { name: reqName, reasoning: "e2e", component_id: component.id, category_id: category.id, keywords: [] },
            })
          ).json()
        ).id;
      const [a, b] = [await make("A"), await make("B")];
      const refused = await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements/${a}/links`, {
        headers: world.headers, data: { target_requirement_id: b, link_type_id: types["Mitigates"].id },
      });
      expect(refused.status()).toBe(400);
      expect((await refused.json()).detail).toContain("limited to specific link types");
    });

    await test.step("a rule cannot be emptied: its last link type stays ticked", async () => {
      await page.request.put(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/artefact-link-rules/decision`, {
        headers: world.headers, data: { link_type_ids: [types["Implements"].id] },
      });
      await page.reload();
      await selectOrgAdminGroup(page, "Projects & workflow");
      await ensureExpanded(page, "Link types");
      await page.getByRole("tab", { name: "By artefact type" }).click();
      await page.getByRole("button", { name: "Link types allowed for Decision" }).click();
      await expect(page.getByRole("checkbox", { name: "Decision: Implements" })).toBeDisabled();
      await page.keyboard.press("Escape");
    });

    await test.step("removing a rule asks first, then allows any link type again", async () => {
      await page.getByRole("button", { name: "Allow any link type" }).first().click();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByText(/Existing links are not changed/)).toBeVisible();
      await dialog.getByRole("button", { name: "Remove rule" }).click();
      await expect(page.getByText("Link rule removed.")).toBeVisible();
    });
  });

  test("deleting a link type in use: move its links, or delete them too", async ({ page }) => {
    const world = await createWorld(page.request, "delete");
    const suffix = Date.now();
    const moveName = `E2E Move ${suffix}`;
    const removeName = `E2E Remove ${suffix}`;
    const narrowName = `E2E Dec only ${suffix}`;
    for (const [forward, extra] of [[moveName, {}], [removeName, {}], [narrowName, { allowed_source_types: ["decision"] }]] as const) {
      const created = await page.request.post(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/link-types`, {
        headers: world.headers, data: { forward_name: forward, reverse_name: `${forward} reverse`, ...extra },
      });
      expect(created.status()).toBe(201);
    }
    const types = await linkTypesByName(page.request, world);

    const project = await (
      await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
        headers: world.headers, data: { organization_id: world.orgId, name: `E2E Delete Project ${suffix}`, summary: "" },
      })
    ).json();
    const component = await (
      await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/components`, {
        headers: world.headers, data: { name: "Software", prefix: "SW" },
      })
    ).json();
    const category = await (
      await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/categories`, {
        headers: world.headers, data: { name: "Functional", prefix: "FN", component_id: component.id },
      })
    ).json();
    const ids: string[] = [];
    for (const reqName of ["A", "B", "C"]) {
      const created = await (
        await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements`, {
          headers: world.headers,
          data: { name: reqName, reasoning: "e2e", component_id: component.id, category_id: category.id, keywords: [] },
        })
      ).json();
      ids.push(created.id);
    }
    const link = async (from: string, to: string, typeId: string) =>
      (
        await (
          await page.request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements/${from}/links`, {
            headers: world.headers, data: { target_requirement_id: to, link_type_id: typeId },
          })
        ).json()
      ).id as string;
    const moveLink = await link(ids[0], ids[1], types[moveName].id);
    await link(ids[1], ids[2], types[removeName].id);

    await openLinkTypes(page, world);

    await test.step("the dialog states what depends on the type and disables a replacement that cannot take its links", async () => {
      await rowOf(page, moveName).getByTitle("Delete this link type").click();
      const dialog = page.getByRole("dialog", { name: `Delete “${moveName}”?` });
      await expect(dialog.getByText(/1 link\(s\) in 1 project\(s\) use this link type/)).toBeVisible();
      await expect(dialog.getByRole("option", { name: new RegExp(`${narrowName} \\(cannot be used: .*cannot start from a requirement`) })).toBeDisabled();
      await expect(dialog.getByRole("button", { name: "Confirm delete" })).toBeDisabled();
    });

    await test.step("moving the links converts them to the chosen type and reports it", async () => {
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("combobox", { name: "Reassign existing items to" }).selectOption({ label: "Related to" });
      await dialog.getByRole("button", { name: "Confirm delete" }).click();
      await expect(page.getByText("Link type deleted: 1 link(s) moved.")).toBeVisible();
      await expect(inputWithValue(page, moveName)).toHaveCount(0);
      const links = await (
        await page.request.get(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements/${ids[0]}/links`, { headers: world.headers })
      ).json();
      expect(links.find((l: { id: string }) => l.id === moveLink).link_type_id).toBe(types["Related to"].id);
    });

    await test.step("deleting the links too needs the type's name typed, then removes them", async () => {
      await rowOf(page, removeName).getByTitle("Delete this link type").click();
      await page.getByRole("dialog").getByRole("button", { name: "Delete the links too…" }).click();
      const confirm = page.getByRole("button", { name: "Delete links and link type" });
      await expect(confirm).toBeDisabled();
      await page.getByLabel(`Type "${removeName}" to confirm`).fill(removeName);
      await confirm.click();
      await expect(page.getByText("Link type deleted along with 1 link(s).")).toBeVisible();
      await expect(inputWithValue(page, removeName)).toHaveCount(0);
      const links = await (
        await page.request.get(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements/${ids[1]}/links`, { headers: world.headers })
      ).json();
      expect(links.some((l: { link_type_id: string }) => l.link_type_id === types[removeName].id)).toBe(false);
    });
  });
});
