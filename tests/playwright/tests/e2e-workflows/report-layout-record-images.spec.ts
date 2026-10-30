import crypto from "node:crypto";
import zlib from "node:zlib";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, openSetupReport, PASSWORD, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/** A 1 x 1 pixel PNG of one colour, built here so that every picture has different bytes (the PDF stores a repeated picture once). */
function pixel(red: number, green: number, blue: number): Buffer {
  const chunk = (type: string, data: Buffer) => {
    const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const length = Buffer.alloc(4);
    length.writeUInt32BE(data.length);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(zlib.crc32(body));
    return Buffer.concat([length, body, crc]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(1, 0);
  header.writeUInt32BE(1, 4);
  header.set([8, 2, 0, 0, 0], 8);
  const scanline = Buffer.from([0, red, green, blue]);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header), chunk("IDAT", zlib.deflateSync(scanline)), chunk("IEND", Buffer.alloc(0)),
  ]);
}

/**
 * Job to be done: print the pictures attached to each record in a report (the photos on a Pain Point), choosing which by
 * their file name and type, and keep a confidential photo out of it.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout record images", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with Context & Strategy on, a project, one Pain Point with four attachments, and a layout. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-record-images-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Record Images ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Record Images Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const enabled = await request.put(`${API}/orgs/${org.id}/modules/context_strategy`, { headers, data: { enabled: true } });
    expect(enabled.ok(), await enabled.text()).toBeTruthy();
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Record images ${suffix}`, summary: "" } })).json();
    const base = `${API}/projects/${project.id}/modules/context_strategy`;
    const types = await (await request.get(`${base}/pain-point-types`, { headers })).json();
    const created = await request.post(`${base}/pain-points`, {
      headers, data: { pain_point_type_id: types[0].id, title: `Leaking gate ${suffix}`, description: "Water gets in." },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const painPoint = await created.json();
    const files = [
      ["site-photo-1.png", pixel(200, 0, 0)], ["site-secret.png", pixel(0, 200, 0)], ["overview.png", pixel(0, 0, 200)],
      ["notes.txt", Buffer.from("not a picture")],
    ] as const;
    for (const [name, buffer] of files) {
      const attached = await request.post(`${base}/pain-points/${painPoint.id}/files`, {
        headers, multipart: { file: { name, mimeType: "application/octet-stream", buffer } },
      });
      expect(attached.ok(), await attached.text()).toBeTruthy();
    }
    const layoutName = `E2E record images ${suffix}`;
    const layout = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: {
        name: layoutName, description: "E2E layout", family: "document",
        tree: {
          schema_version: 1, family: "document", orientation: "portrait",
          nodes: [{
            type: "each", source: { record_type: "pain_point" }, as: "pp",
            children: [{ type: "record_images", names: ["site-*"], types: ["png"], caption_source: "none" }],
          }],
        },
      },
    });
    expect(layout.ok(), await layout.text()).toBeTruthy();
    return { headers, project, painPoint, layoutId: (await layout.json()).id as string, layoutName, suffix };
  }

  /** The number of picture objects in a PDF the layout produces. */
  async function pdfPictures(request: APIRequestContext, headers: Record<string, string>, projectId: string, layoutId: string) {
    const run = await request.get(`${API}/projects/${projectId}/custom-reports/${layoutId}/run`, { headers, params: { format: "pdf" } });
    expect(run.ok(), await run.text()).toBeTruthy();
    return (((await run.body()).toString("latin1")).match(/\/Subtype \/Image/g) ?? []).length;
  }

  test("the rules choose the pictures, and a picture marked confidential never prints", async ({ page, request }) => {
    const { headers, project, painPoint, layoutId, layoutName } = await setup(page, request);

    await test.step("a picture on the record can be marked confidential, and the page says what that affects", async () => {
      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points/${painPoint.id}`);
      await expect(page.getByText("A picture marked confidential is left out of reports. It does not change who can open it.")).toBeVisible();
      await expect(page.getByRole("button", { name: /confidential/ })).toHaveCount(3);
      await expect(page.getByRole("button", { name: "Mark notes.txt confidential" })).toHaveCount(0);
      await page.getByRole("button", { name: "Mark site-secret.png confidential" }).click();
      await expect(page.getByText("site-secret.png is marked confidential.")).toBeVisible();
      await expect(page.getByText("Confidential", { exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByRole("button", { name: "Clear the confidential mark on site-secret.png" })).toHaveAttribute("aria-pressed", "true");
    });

    await test.step("the layout's rules are shown in the block's details and drive the preview", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Report Setup");
      await openSetupReport(page, layoutName);
      await page.getByRole("tab", { name: "Blocks" }).click();
      await page.locator(".blocklyText", { hasText: /Record\s+images/ }).first().click();
      const inspector = page.getByLabel("Block details");
      await expect(inspector.getByRole("textbox", { name: "File names" })).toHaveValue("site-*");
      await expect(page.getByText("No problems.")).toBeVisible();

      const preview = async () => {
        await page.getByRole("button", { name: "Preview", exact: true }).click();
        const dialog = page.getByRole("dialog", { name: "Report preview" });
        await dialog.getByRole("button", { name: "Run preview" }).click();
        const frame = dialog.frameLocator('iframe[title="Report preview"]');
        return { dialog, frame };
      };
      let { dialog, frame } = await preview();
      await expect(frame.locator("img")).toHaveCount(1);
      await dialog.getByRole("button", { name: "Close" }).click();

      await inspector.getByRole("textbox", { name: "File names" }).fill("*");
      ({ dialog, frame } = await preview());
      await expect(frame.locator("img")).toHaveCount(2);
      await dialog.getByRole("button", { name: "Close" }).click();
    });

    await test.step("the downloaded PDF embeds only the pictures the rules chose", async () => {
      expect(await pdfPictures(request, headers, project.id, layoutId)).toBe(1);
    });

    await test.step("clearing the mark brings the picture back", async () => {
      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points/${painPoint.id}`);
      await page.getByRole("button", { name: "Clear the confidential mark on site-secret.png" }).click();
      await expect(page.getByText("site-secret.png is no longer marked confidential.")).toBeVisible();
      expect(await pdfPictures(request, headers, project.id, layoutId)).toBe(2);
    });
  });

  test("a block outside a For each record block, or naming an unknown file type, is refused with the reason", async ({ page, request }) => {
    const { headers, project, suffix } = await setup(page, request);
    const bad = await request.post(`${API}/projects/${project.id}/report-layouts/validate`, {
      headers, data: { tree: { schema_version: 1, family: "document", orientation: "portrait", nodes: [{ type: "record_images", types: ["exe"] }] } },
    });
    const answer = await bad.json();
    expect(answer.ok, suffix).toBe(false);
    expect(JSON.stringify(answer.errors)).toContain("inside a For each record block");
  });
});
