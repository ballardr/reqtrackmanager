import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS } from "./helpers";

const API = "http://localhost:8000";

/**
 * Job to be done: a file shown in the app (an avatar, a logo, an attachment preview) is loaded by an
 * `<img src>`, which cannot send an Authorization header, so its URL carries a credential. That URL is written
 * to server logs and browser history, so the credential must be a short-lived media token that can load files
 * and nothing else — never the session token.
 */
test.describe("file URL credential", () => {
  test("an image URL carries a media token, not the session token", async ({ page }) => {
    await loginAs(page, PERSONAS.stakeholderAlpha.email);
    const session = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    expect(session).toBeTruthy();

    try {
      await test.step("the person has an avatar, so the app renders an <img> loaded from /api/v1/files", async () => {
        const upload = await page.request.post(`${API}/api/v1/auth/me/avatar`, {
          headers: { Authorization: `Bearer ${session}` },
          multipart: { file: { name: "avatar.png", mimeType: "image/png", buffer: Buffer.from("fake-png-bytes") } },
        });
        expect(upload.ok()).toBeTruthy();
        await page.goto("/preferences/profile");
        await expect(page.locator('img[src*="/api/v1/files/"]').first()).toBeAttached();
      });

      await test.step("the URL's token is not the session token, and it loads the file", async () => {
        const src = await page.locator('img[src*="/api/v1/files/"]').first().getAttribute("src");
        const url = new URL(src!);
        const urlToken = url.searchParams.get("token");
        expect(urlToken).toBeTruthy();
        expect(urlToken).not.toBe(session);
        expect((await page.request.get(src!)).status()).toBe(200);
      });

      await test.step("the session token in a URL is refused, and the media token is useless for the API", async () => {
        const src = await page.locator('img[src*="/api/v1/files/"]').first().getAttribute("src");
        const url = new URL(src!);
        const mediaToken = url.searchParams.get("token")!;
        url.searchParams.set("token", session!);
        expect((await page.request.get(url.toString())).status()).toBe(401);
        const me = await page.request.get(`${API}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${mediaToken}` } });
        expect(me.status()).toBe(401);
      });
    } finally {
      await page.request.delete(`${API}/api/v1/auth/me/avatar`, { headers: { Authorization: `Bearer ${session}` } });
    }
  });
});
