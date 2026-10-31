import crypto from "node:crypto";
import zlib from "node:zlib";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, openSetupReport, PASSWORD, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/** The text of one file of a zip (an XLSX or ODS is one), read from its central directory. */
function zipEntry(zip: Buffer, name: string): string {
  let end = zip.length - 22;
  while (end >= 0 && zip.readUInt32LE(end) !== 0x06054b50) end -= 1;
  let at = zip.readUInt32LE(end + 16);
  for (let n = zip.readUInt16LE(end + 10); n > 0; n -= 1) {
    const method = zip.readUInt16LE(at + 10);
    const size = zip.readUInt32LE(at + 20);
    const nameLength = zip.readUInt16LE(at + 28);
    const extraLength = zip.readUInt16LE(at + 30);
    const commentLength = zip.readUInt16LE(at + 32);
    const local = zip.readUInt32LE(at + 42);
    if (zip.toString("utf8", at + 46, at + 46 + nameLength) === name) {
      const start = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28);
      const body = zip.subarray(start, start + size);
      return (method === 8 ? zlib.inflateRawSync(body) : body).toString("utf8");
    }
    at += 46 + nameLength + extraLength + commentLength;
  }
  throw new Error(`${name} is not in the zip`);
}

/**
 * Job to be done: one Excel or OpenDocument workbook with a sheet of requirements and a sheet of pain points, where a pain
 * point's requirement opens that requirement's row on the Requirements sheet, and a Contents sheet that opens each sheet.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report sheet links", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with Context & Strategy on, a project, two requirements and a pain point linked to the second. */
  async function setup(page: Page, request: APIRequestContext, tree: (suffix: string) => Record<string, unknown>) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-sheet-links-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Sheet Links ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Sheet Links Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const enabled = await request.put(`${API}/orgs/${org.id}/modules/context_strategy`, { headers, data: { enabled: true } });
    expect(enabled.ok(), await enabled.text()).toBeTruthy();
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Sheet links ${suffix}`, summary: "" } })).json();
    const component = await (await request.post(`${API}/projects/${project.id}/components`, { headers, data: { name: "Core", prefix: "COR" } })).json();
    const category = await (await request.post(`${API}/projects/${project.id}/categories`, {
      headers, data: { name: "Functional", prefix: "FUNC", component_id: component.id },
    })).json();
    const requirement = async (name: string) => {
      const created = await request.post(`${API}/projects/${project.id}/requirements`, {
        headers, data: { name, component_id: component.id, category_id: category.id },
      });
      expect(created.ok(), await created.text()).toBeTruthy();
      return (await created.json()).id as string;
    };
    await requirement(`Alpha ${suffix}`);
    const second = await requirement(`Beta ${suffix}`);
    const base = `${API}/projects/${project.id}/modules/context_strategy`;
    const types = await (await request.get(`${base}/pain-point-types`, { headers })).json();
    const pain = await request.post(`${base}/pain-points`, { headers, data: { pain_point_type_id: types[0].id, title: `Late ${suffix}`, description: "d" } });
    expect(pain.ok(), await pain.text()).toBeTruthy();
    // Any link type the organisation allows between a requirement and a pain point will do.
    const linkTypes = await (await request.get(`${API}/orgs/${org.id}/link-types`, { headers })).json();
    let linked = false;
    for (const type of linkTypes) {
      const link = await request.post(`${API}/projects/${project.id}/artefacts/requirement/${second}/links`, {
        headers, data: { link_type_id: type.id, direction: "outgoing", other_type: "pain_point", other_id: (await pain.json()).id },
      });
      if (link.ok()) { linked = true; break; }
    }
    expect(linked, "no link type allows a requirement to link to a pain point").toBeTruthy();
    const layoutName = `E2E sheet links ${suffix}`;
    const layout = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: { name: layoutName, description: "E2E layout", family: "table", tree: tree(suffix) },
    });
    expect(layout.ok(), await layout.text()).toBeTruthy();
    return { headers, project, layoutId: (await layout.json()).id as string, layoutName, suffix };
  }

  const workbook = (contents: boolean) => (): Record<string, unknown> => ({
    schema_version: 1, family: "table", ...(contents ? { contents_sheet: true } : {}),
    nodes: [
      { type: "sheet", name: "Requirements", source: { record_type: "requirement", sort: [{ field: "title" }] }, columns: [{ field: "code" }, { field: "title" }] },
      {
        type: "sheet", name: "Owner's pain", as: "pain", source: { record_type: "pain_point" },
        joins: [{ as: "req", source: { record_type: "requirement", linked_from: "pain" } }],
        columns: [{ field: "title" }, { field: "title", from: "req", label: "Requirement", link: { sheet: "Requirements" } }],
      },
    ],
  });

  async function download(request: APIRequestContext, headers: Record<string, string>, projectId: string, layoutId: string, format: string) {
    const run = await request.get(`${API}/projects/${projectId}/custom-reports/${layoutId}/run`, { headers, params: { format } });
    expect(run.ok(), await run.text()).toBeTruthy();
    return run.body();
  }

  test("the Excel and OpenDocument files open the requirement's row on the Requirements sheet", async ({ page, request }) => {
    const { headers, project, layoutId } = await setup(page, request, workbook(false));

    await test.step("Excel: the cell is a link to row 3 (the second requirement), on the sheet with the apostrophe in its name", async () => {
      const xlsx = await download(request, headers, project.id, layoutId, "xlsx");
      const sheet = zipEntry(xlsx, "xl/worksheets/sheet2.xml");
      expect(sheet).toContain('<hyperlink ref="B2" location="\'Requirements\'!A3"');
    });

    await test.step("OpenDocument: the cell text is an internal link to the same row", async () => {
      const ods = await download(request, headers, project.id, layoutId, "ods");
      expect(zipEntry(ods, "content.xml")).toMatch(/<text:a xlink:type="simple" xlink:href="#&apos;Requirements&apos;\.A3">|xlink:href="#'Requirements'\.A3"/);
    });

    await test.step("CSV keeps the plain text of the cell", async () => {
      const zip = await download(request, headers, project.id, layoutId, "csv");
      expect(zipEntry(zip, "Owner_s pain.csv")).toMatch(/Requirement\r?\n.*Beta/s);
    });
  });

  test("a Contents sheet lists the sheets with links and row counts", async ({ page, request }) => {
    const { headers, project, layoutId } = await setup(page, request, workbook(true));
    const xlsx = await download(request, headers, project.id, layoutId, "xlsx");

    const contents = zipEntry(xlsx, "xl/worksheets/sheet1.xml");
    expect(contents).toContain('location="\'Requirements\'!A1"');
    expect(contents).toContain('location="\'Owner\'\'s pain\'!A1"');
    // With Contents first, the pain point's link still opens the right sheet.
    expect(zipEntry(xlsx, "xl/worksheets/sheet3.xml")).toContain('location="\'Requirements\'!A3"');
  });

  test("the designer offers Link to sheet only for sheets that list the same kind of record, and a bad link is refused", async ({ page, request }) => {
    const { headers, project, layoutName } = await setup(page, request, workbook(false));

    await test.step("a link to a sheet of another record type is refused with the reason", async () => {
      const tree = workbook(false)() as { nodes: { columns: Record<string, unknown>[] }[] };
      tree.nodes[1].columns[1].link = { sheet: "Owner's pain" };
      const answer = await (await request.post(`${API}/projects/${project.id}/report-layouts/validate`, { headers, data: { tree } })).json();
      expect(answer.ok).toBe(false);
      expect(JSON.stringify(answer.errors)).toContain("lists pain_point records, not requirement records");
    });

    await test.step("in the Blocks view each column offers only the sheets that list its own kind of record", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Report Setup");
      await openSetupReport(page, layoutName);
      await page.getByRole("tab", { name: "Blocks" }).click();
      const inspector = page.getByLabel("Block details");
      // Select the Pain sheet: the only one whose columns can read from a joined record.
      const titles = page.locator(".blocklyText.rl-block-title", { hasText: /^Sheet$/ });
      await titles.first().waitFor();
      for (let n = 0; n < (await titles.count()); n += 1) {
        await titles.nth(n).click();
        await expect(inspector).not.toContainText("Select a block");
        if ((await inspector.getByRole("combobox", { name: "Column 2 reads from" }).count()) > 0) break;
      }
      const link = inspector.getByRole("combobox", { name: "Column 2 links to sheet" });
      await expect(link.locator("option")).toHaveText(["No link", "Requirements"]);
      await expect(link).toHaveValue("Requirements");
      // The pain point column can only open pain point sheets: its own sheet is the one on offer, never Requirements.
      await expect(inspector.getByRole("combobox", { name: "Column 1 links to sheet" }).locator("option")).toHaveText(["No link", "Owner's pain"]);
    });

    await test.step("the text view writes the link and the layout setting", async () => {
      await page.getByRole("tab", { name: "Text" }).click();
      const text = await page.getByRole("textbox", { name: "Layout text" }).inputValue();
      expect(text).toContain('@column req.title "Requirement" link "Requirements"');
    });
  });
});
