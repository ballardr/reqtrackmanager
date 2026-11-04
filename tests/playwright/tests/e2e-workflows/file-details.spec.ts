import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

const API = "http://localhost:8000/api/v1";
/** A 60 x 30 JPEG whose EXIF names a camera, a description, a time and a position. */
const PHOTO = Buffer.from(
  "/9j/4AAQSkZJRgABAQAAAQABAAD/4QEKRXhpZgAATU0AKgAAAAgABQEOAAIAAAAXAAAASgEPAAIAAAAGAAAAYgEQAAIAAAANAAAAaIdpAAQAAAABAAAAdoglAAQAAAABAAAAnAAAAABOb3J0aCBnYXRlLCBwdW1wIGhvdXNlAABDYW5vbgBDYW5vbiBFT1MgNUQAAAABkAMAAgAAABQAAACIAAAAADIwMjY6MTA6MTIgMTQ6MDM6MTEAAAQAAQACAAAAAlMAAAAAAgAFAAAAAwAAANIAAwACAAAAAkUAAAAABAAFAAAAAwAAAOoAAAAAAAAAIQAAAAEAAAA0AAAAAQAAAAAAAAABAAAAlwAAAAEAAAAMAAAAAQAAACQAAAAB/9sAQwAIBgYHBgUIBwcHCQkICgwUDQwLCwwZEhMPFB0aHx4dGhwcICQuJyAiLCMcHCg3KSwwMTQ0NB8nOT04MjwuMzQy/9sAQwEJCQkMCwwYDQ0YMiEcITIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy/8AAEQgAHgA8AwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/aAAwDAQACEQMRAD8A4qiiivmj48KKKKACiiigAooooAKKKKACiiigAooooAKKKKAP/9k=",
  "base64",
);

/**
 * Job to be done: tell photographs apart in a file list when their names say nothing, by seeing when each was taken, the
 * camera, its description and where, on the project's Files page and in an organisation's shared resources.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("File details (EXIF)", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-file-details-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E File Details ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Details Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Details project ${suffix}`, summary: "" } })).json();
    return { org, headers, project, suffix };
  }

  test("the project's Files page shows a photograph's EXIF behind an info button, and none for other files", async ({ page, request }) => {
    const { org, headers, project, suffix } = await setup(page, request);
    const component = await (await request.post(`${API}/projects/${project.id}/components`, { headers, data: { name: "Hardware", prefix: "HW" } })).json();
    const category = await (await request.post(`${API}/projects/${project.id}/categories`, {
      headers, data: { name: "Functional", prefix: "FN", component_id: component.id },
    })).json();
    const requirement = await (await request.post(`${API}/projects/${project.id}/requirements`, {
      headers, data: { name: `Gate check ${suffix}`, component_id: component.id, category_id: category.id },
    })).json();
    for (const [name, buffer, mimeType] of [["IMG_0042.jpg", PHOTO, "image/jpeg"], ["notes.txt", Buffer.from("plain notes"), "text/plain"]] as const) {
      const uploaded = await request.post(`${API}/projects/${project.id}/requirements/${requirement.id}/files`, {
        headers, multipart: { file: { name, mimeType, buffer } },
      });
      expect(uploaded.ok(), await uploaded.text()).toBeTruthy();
    }
    expect(org.id).toBeTruthy();

    await page.goto(`/projects/${project.id}/files`);
    await expect(page.getByRole("link", { name: "IMG_0042.jpg" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Details of notes.txt" })).toHaveCount(0);

    await page.getByRole("button", { name: "Details of IMG_0042.jpg" }).click();
    const details = page.getByRole("dialog", { name: "Details of IMG_0042.jpg" });
    await expect(details.getByText("60 × 30 px")).toBeVisible();
    await expect(details.getByText("2026-10-12 14:03:11")).toBeVisible();
    await expect(details.getByText("Canon EOS 5D")).toBeVisible();
    await expect(details.getByText("North gate, pump house")).toBeVisible();
    await expect(details.getByText("-33.86667, 151.21000")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(details).toBeHidden();
  });

  test("an organisation's shared resources show the same details", async ({ page, request }) => {
    const { org, headers } = await setup(page, request);
    const uploaded = await request.post(`${API}/orgs/${org.id}/resources`, {
      headers, multipart: { file: { name: "site-photo.jpg", mimeType: "image/jpeg", buffer: PHOTO } },
    });
    expect(uploaded.ok(), await uploaded.text()).toBeTruthy();

    await page.goto(`/orgs/${org.id}/admin`);
    await page.getByRole("button", { name: /Shared resources/ }).click();
    await page.getByRole("button", { name: "Details of site-photo.jpg" }).click();
    const details = page.getByRole("dialog", { name: "Details of site-photo.jpg" });
    await expect(details.getByText("Canon EOS 5D")).toBeVisible();
    await expect(details.getByText("2026-10-12 14:03:11")).toBeVisible();
  });
});
