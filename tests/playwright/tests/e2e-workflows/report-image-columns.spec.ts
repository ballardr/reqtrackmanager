import crypto from "node:crypto";
import zlib from "node:zlib";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, openSetupReport, PASSWORD, saveNewVersion, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/** A 1 x 1 pixel PNG of one colour, so every picture has different bytes (a PDF stores a repeated picture once). */
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
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header), chunk("IDAT", zlib.deflateSync(Buffer.from([0, red, green, blue]))), chunk("IEND", Buffer.alloc(0)),
  ]);
}

/**
 * Job to be done: a table of Pain Points with an id and a column of the pictures attached to each (a photo, a diagram), sized as
 * a share of the column, arranged as chosen, and with the table's heading row repeating on each page unless switched off.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report image columns", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with Context & Strategy on, a project, two Pain Points with pictures and a table layout. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-image-columns-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Image Columns ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Image Columns Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const enabled = await request.put(`${API}/orgs/${org.id}/modules/context_strategy`, { headers, data: { enabled: true } });
    expect(enabled.ok(), await enabled.text()).toBeTruthy();
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Image columns ${suffix}`, summary: "" } })).json();
    const base = `${API}/projects/${project.id}/modules/context_strategy`;
    const types = await (await request.get(`${base}/pain-point-types`, { headers })).json();
    const attach = async (title: string, files: [string, Buffer][]) => {
      const created = await request.post(`${base}/pain-points`, { headers, data: { pain_point_type_id: types[0].id, title, description: "d" } });
      expect(created.ok(), await created.text()).toBeTruthy();
      const point = await created.json();
      for (const [name, buffer] of files) {
        const attached = await request.post(`${base}/pain-points/${point.id}/files`, {
          headers, multipart: { file: { name, mimeType: "application/octet-stream", buffer } },
        });
        expect(attached.ok(), await attached.text()).toBeTruthy();
      }
    };
    await attach(`Leaking gate ${suffix}`, [["site-1.png", pixel(200, 0, 0)], ["site-2.png", pixel(0, 200, 0)], ["notes.txt", Buffer.from("text")]]);
    await attach(`Cracked wall ${suffix}`, [["other.png", pixel(0, 0, 200)]]);
    const layoutName = `E2E image column ${suffix}`;
    const layout = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: {
        name: layoutName, description: "E2E layout", family: "document",
        tree: {
          schema_version: 1, family: "document", orientation: "portrait",
          nodes: [{ type: "table", source: { record_type: "pain_point" }, columns: [{ field: "code" }, { field: "title" }] }],
        },
      },
    });
    expect(layout.ok(), await layout.text()).toBeTruthy();
    return { headers, project, layoutId: (await layout.json()).id as string, layoutName };
  }

  async function runPdf(request: APIRequestContext, headers: Record<string, string>, projectId: string, layoutId: string) {
    const run = await request.get(`${API}/projects/${projectId}/custom-reports/${layoutId}/run`, { headers, params: { format: "pdf" } });
    expect(run.ok(), await run.text()).toBeTruthy();
    return (await run.body()).toString("latin1");
  }

  test("an images column is added in the designer, sized and arranged, previewed and printed", async ({ page, request }) => {
    const { headers, project, layoutId, layoutName } = await setup(page, request);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");
    await openSetupReport(page, layoutName);
    await page.getByRole("tab", { name: "Blocks" }).click();
    await page.locator(".blocklyText.rl-block-title", { hasText: /^Table$/ }).first().click();
    const inspector = page.getByLabel("Block details");

    await test.step("Add images column offers the shared settings, with the size a share of the column", async () => {
      await inspector.getByRole("button", { name: "Add images column" }).click();
      const column = inspector.getByRole("group", { name: "Column 3: images attached to the record" });
      await column.getByRole("textbox", { name: "Column 3 heading" }).fill("Photos");
      await column.getByRole("textbox", { name: "File names" }).fill("site-*");
      await column.getByRole("textbox", { name: "File names" }).press("Enter");
      await column.getByRole("spinbutton", { name: "Width" }).fill("60");
      await expect(column.getByRole("combobox", { name: "Width unit" }).locator("option", { hasText: "% of the column's width" })).toHaveCount(1);
      await column.getByRole("combobox", { name: "Arrangement" }).selectOption({ label: "Side by side, wrapping" });
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("the preview draws each row's matching pictures in its own cell", async () => {
      await page.getByRole("button", { name: "Preview", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Report preview" });
      await dialog.getByRole("button", { name: "Run preview" }).click();
      const frame = dialog.frameLocator('iframe[title="Report preview"]');
      await expect(frame.getByRole("columnheader", { name: "Photos" })).toBeVisible();
      await expect(frame.locator("td .cell-images.side img")).toHaveCount(2);
      await dialog.getByRole("button", { name: "Close" }).click();
    });

    await test.step("saved, the layout reads back as text and the PDF embeds the two pictures", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.getByRole("tab", { name: "Text" }).click();
      const text = await page.getByRole("textbox", { name: "Layout text" }).inputValue();
      expect(text).toContain('@images names "site-*" width 60 arrange side_by_side label "Photos"');
      const pdf = await runPdf(request, headers, project.id, layoutId);
      expect((pdf.match(/\/Subtype \/Image/g) ?? []).length).toBe(2);
    });
  });

  test("the text view writes an images column and the heading-row switch is a page setup option", async ({ page, request }) => {
    const { project, layoutName } = await setup(page, request);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");
    await openSetupReport(page, layoutName);
    const editor = page.getByRole("textbox", { name: "Layout text" });
    await editor.fill("@layout document\n\n@table pain_point\n  @column code\n  @images types png width 80 percent\n@end\n");
    await expect(page.getByText("The text is valid.")).toBeVisible();

    await test.step("Page setup has Repeat table header rows, on by default, written as a word on the first line", async () => {
      await page.getByRole("button", { name: /Page setup:/ }).click();
      const dialog = page.getByRole("dialog", { name: "Page setup" });
      const box = dialog.getByRole("checkbox", { name: "Repeat table header rows" });
      await expect(box).toBeChecked();
      await box.uncheck();
      await expect(editor).toHaveValue(/^@layout document norepeatheader\n/);
      await expect(page.getByText("The text is valid.")).toBeVisible();
      await box.check();
      await expect(editor).toHaveValue(/^@layout document\n/);
      await dialog.getByRole("button", { name: "Close" }).click();
    });

    await test.step("a bad images line is reported at its line", async () => {
      await editor.fill("@layout document\n\n@table pain_point\n  @column code\n  @images width\n@end\n");
      await expect(page.getByText(/Line 5/)).toBeVisible();
    });
  });

  test("the heading row repeats on each page by default and not when the layout switches it off", async ({ page, request }) => {
    const { headers, project, layoutId } = await setup(page, request);
    const get = await request.get(`${API}/projects/${project.id}/report-layouts/${layoutId}`, { headers });
    const detail = await get.json();
    const tree = { ...detail.current.tree, repeat_table_header: false };
    const saved = await request.put(`${API}/projects/${project.id}/report-layouts/${layoutId}/tree`, {
      headers, data: { tree, base_version: detail.current_version },
    });
    expect(saved.ok(), await saved.text()).toBeTruthy();
    const html = await request.get(`${API}/projects/${project.id}/custom-reports/${layoutId}/run`, { headers, params: { format: "html" } });
    expect(await html.text()).not.toContain("<thead>");
    const off = await request.put(`${API}/projects/${project.id}/report-layouts/${layoutId}/tree`, {
      headers, data: { tree: { ...tree, repeat_table_header: true }, base_version: detail.current_version + 1 },
    });
    expect(off.ok(), await off.text()).toBeTruthy();
    const again = await request.get(`${API}/projects/${project.id}/custom-reports/${layoutId}/run`, { headers, params: { format: "html" } });
    expect(await again.text()).toContain("<thead>");
  });

  test("an images column over a type that cannot hold attachments is refused with the reason", async ({ page, request }) => {
    const { headers, project } = await setup(page, request);
    const answer = await (await request.post(`${API}/projects/${project.id}/report-layouts/validate`, {
      headers, data: { tree: { schema_version: 1, family: "document", nodes: [{ type: "table", source: { record_type: "stakeholder" }, columns: [{ images: {} }] }] } },
    })).json();
    expect(answer.ok).toBe(false);
    expect(JSON.stringify(answer.errors)).toContain("identifiable person");
  });
});
