import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook, loginAs, logout, PASSWORD } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** The canvas marker of a comment thread (a button named with its author, count and state). */
const marker = (page: Page, count: number) => page.getByRole("button", { name: new RegExp(`Comment thread by .*, ${count} ${count === 1 ? "comment" : "comments"}`) });

/**
 * Job to be done: reviewers talk about a diagram on the diagram. Comment mode places a pinned thread on a box (or a free spot),
 * a second person replies, a thread is resolved and hidden, and none of it ever marks the layout as having unsaved changes.
 * The box's own page lists the threads pinned to it.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the element, diagram and second member are
 * created through the API as setup, every comment through the UI.
 */
test.describe("System Architecture: diagram comments", () => {
  test("a reviewer pins a thread on a box, a second person replies, the thread is resolved and hidden, and the layout stays saved", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "ArchCmt", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const gateway = `Gateway ${suffix}`;
    const types = await (await page.request.get(`${base}/element-types`, { headers: adminHeaders })).json();
    const element = await page.request.post(`${base}/elements`, { headers: adminHeaders, data: { name: gateway, element_type_id: types[0].id, activate: true } });
    expect(element.ok(), await element.text()).toBeTruthy();
    const gatewayId = (await element.json()).id;
    const created = await page.request.post(`${base}/diagrams`, { headers: adminHeaders, data: { name: `Review ${suffix}`, activate: true, populate: true } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    const placed = await page.request.get(`${base}/diagrams/${diagram.id}/view`, { headers: adminHeaders });
    expect((await placed.json()).nodes.length).toBeGreaterThan(0);

    const colleagueEmail = `e2e-cmt-colleague-${suffix}@example.com`;
    const user = await page.request.post(`${API}/api/v1/orgs/${org.id}/users`, {
      headers: adminHeaders, data: { email: colleagueEmail, display_name: "Casey Colleague", password: PASSWORD, role: "member" },
    });
    expect(user.ok(), await user.text()).toBeTruthy();
    const added = await page.request.post(`${API}/api/v1/projects/${project.id}/roles`, {
      headers: adminHeaders, data: { user_id: (await user.json()).user_id, role: "member" },
    });
    expect(added.status(), await added.text()).toBe(204);

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    const box = page.getByLabel(`${gateway}, node`, { exact: true });
    await expect(box).toBeVisible();

    await test.step("comment mode places a comment on a box and leaves a marker", async () => {
      await page.getByRole("button", { name: "Comment", exact: true }).click();
      await expect(page.getByRole("button", { name: "Comment", exact: true })).toHaveAttribute("aria-pressed", "true");
      const stored = page.waitForResponse((r) => r.url().endsWith(`/artefacts/architecture_diagram/${diagram.id}/comments`) && r.request().method() === "POST");
      await box.click();
      const composer = page.getByRole("dialog", { name: "New comment" });
      await composer.getByRole("textbox", { name: "New comment" }).fill("Does this box need a retry path?");
      await composer.getByRole("button", { name: "Comment", exact: true }).click();
      expect((await stored).ok()).toBeTruthy();
      await expect(marker(page, 1)).toBeVisible();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
      await expect(page.getByText("Unsaved changes.")).toHaveCount(0);
    });

    await test.step("a second person replies and the count shows", async () => {
      await logout(page);
      await loginAs(page, colleagueEmail);
      await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
      await marker(page, 1).click();
      const thread = page.getByRole("dialog", { name: "Comment thread" });
      await expect(thread.getByText("Does this box need a retry path?")).toBeVisible();
      await thread.getByRole("textbox", { name: "Reply" }).fill("Yes, add one.");
      await thread.getByRole("button", { name: "Reply", exact: true }).click();
      await expect(thread.getByText("Yes, add one.")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(marker(page, 2)).toBeVisible();
    });

    await test.step("a comment is edited and deleted from the keyboard, and the thread's buttons are a small part of the pop-over", async () => {
      await marker(page, 2).click();
      const thread = page.getByRole("dialog", { name: "Comment thread" });
      await thread.getByRole("textbox", { name: "Reply" }).fill("Temporary note");
      await thread.getByRole("button", { name: "Reply", exact: true }).click();
      const row = thread.locator(".comment-row", { hasText: "Temporary note" });
      await expect(row).toBeVisible();
      // The actions are icon buttons that keyboard focus reveals; none is a text button.
      const edit = row.getByRole("button", { name: "Edit", exact: true });
      await edit.focus();
      await expect(row.locator(".item-row__actions")).toHaveCSS("opacity", "1");
      await page.keyboard.press("Enter");
      await thread.getByRole("textbox", { name: "Edit" }).fill("Temporary note, edited");
      await thread.getByRole("button", { name: "Save", exact: true }).click();
      await expect(thread.getByText("Temporary note, edited")).toBeVisible();
      const share = await thread.evaluate((el) => {
        const area = (b: Element) => { const r = b.getBoundingClientRect(); return r.width * r.height; };
        const whole = el.getBoundingClientRect();
        return Array.from(el.querySelectorAll("button")).reduce((sum, b) => sum + area(b), 0) / (whole.width * whole.height);
      });
      expect(share).toBeLessThan(0.15);
      await row.getByRole("button", { name: "Delete comment", exact: true }).focus();
      await page.keyboard.press("Enter");
      await page.getByRole("dialog").last().getByRole("button", { name: "Delete comment", exact: true }).click();
      await expect(thread.getByText("Temporary note, edited")).toHaveCount(0);
      await page.keyboard.press("Escape");
      await expect(marker(page, 2)).toBeVisible();
    });

    await test.step("the thread is resolved, then hidden with Show resolved", async () => {
      await marker(page, 2).click();
      await page.getByRole("dialog", { name: "Comment thread" }).getByRole("button", { name: "Resolve" }).click();
      await expect(page.getByRole("dialog", { name: "Comment thread" }).getByRole("button", { name: "Reopen" })).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("button", { name: /Resolved comment thread/ })).toBeVisible();
      await page.getByRole("button", { name: /^Diagram settings/ }).click();
      await page.getByRole("switch", { name: "Show resolved" }).click();
      await expect(page.getByRole("button", { name: /comment thread/i })).toHaveCount(0);
    });

    await test.step("the Comments tab lists the thread, and the element's page lists it too", async () => {
      await page.keyboard.press("Escape");
      await page.getByRole("tab", { name: "Comments" }).click();
      await expect(page.getByText("Does this box need a retry path?")).toBeVisible();
      await expect(page.getByText("Pinned", { exact: true }).first()).toBeVisible();
      await page.goto(`/projects/${project.id}/modules/architecture/elements/${gatewayId}`);
      await expect(page.getByRole("heading", { name: "Pinned on diagrams" })).toBeVisible();
      await expect(page.getByText("Yes, add one.")).toBeVisible();
      await page.getByRole("link", { name: new RegExp(`Open .*Review ${suffix}`) }).click();
      await expect(page).toHaveURL(/\?pin=/);
      await expect(page.getByRole("dialog", { name: "Comment thread" })).toBeVisible();
    });
  });

  test("a comment on empty canvas is a free marker that stays where it was put, and an ordinary comment can be pinned later", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchCmtFree", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const types = await (await page.request.get(`${base}/element-types`, { headers: adminHeaders })).json();
    const element = await page.request.post(`${base}/elements`, { headers: adminHeaders, data: { name: `Core ${suffix}`, element_type_id: types[0].id, activate: true } });
    expect(element.ok(), await element.text()).toBeTruthy();
    const created = await page.request.post(`${base}/diagrams`, { headers: adminHeaders, data: { name: `Free ${suffix}`, activate: true, populate: true } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(`Core ${suffix}, node`, { exact: true })).toBeVisible();

    await test.step("a click on empty canvas places a free comment", async () => {
      await page.getByRole("button", { name: "Comment", exact: true }).click();
      const pane = page.locator(".react-flow__pane");
      const area = await pane.boundingBox();
      await page.mouse.click(area!.x + area!.width - 60, area!.y + area!.height - 60);
      const composer = page.getByRole("dialog", { name: "New comment" });
      await composer.getByRole("textbox", { name: "New comment" }).fill("A connection is missing here");
      await composer.getByRole("button", { name: "Comment", exact: true }).click();
      await expect(marker(page, 1)).toBeVisible();
      const thread = await (await page.request.get(`${API}/api/v1/projects/${project.id}/artefacts/architecture_diagram/${diagram.id}/comments`, { headers: adminHeaders })).json();
      expect(thread.pins).toMatchObject([{ anchor_kind: "none", anchor_key: null }]);
    });

    await test.step("an ordinary comment from the Comments tab is pinned to the drawing afterwards", async () => {
      await page.getByRole("button", { name: "Comment", exact: true }).click(); // comment mode off
      await page.getByRole("tab", { name: "Comments" }).click();
      await page.getByRole("textbox", { name: "Add a comment" }).fill("Write this up in the design");
      await page.getByRole("button", { name: "Add comment" }).click();
      await expect(page.getByText("Write this up in the design")).toBeVisible();
      await page.getByRole("button", { name: "Pin to diagram" }).click();
      await expect(page.getByRole("button", { name: "Comment", exact: true })).toHaveAttribute("aria-pressed", "true");
      const pane = page.locator(".react-flow__pane");
      const area = await pane.boundingBox();
      await page.mouse.click(area!.x + 80, area!.y + area!.height - 60);
      await expect(marker(page, 1)).toHaveCount(2);
    });
  });
});
