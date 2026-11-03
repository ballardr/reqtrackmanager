import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { closeDesignerPreview, deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, openDesignerPreview, PASSWORD, saveNewVersion, selectOrgAdminGroup, selectProjectAdminGroup, designerPreviewPanel } from "./helpers";

const API = "http://localhost:8000/api/v1";
/** A 1 x 1 pixel PNG. */
const PIXEL = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

/**
 * Job to be done: put a picture in a report (a logo, a diagram) with a size, an alignment and a caption, choosing it
 * from the library of the project (or the organisation) the layout belongs to.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout images", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with an admin and a project; the page is left logged in as the admin. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-layout-images-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Layout Images ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Images Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Images project ${suffix}`, summary: "" } })).json();
    return { org, headers, project, suffix };
  }

  async function newLayout(page: Page, name: string) {
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
    const dialog = page.getByRole("dialog", { name: "New report layout" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();
  }

  /** Adds an Image block, uploads a picture in the library dialog and chooses it. */
  async function addPicture(page: Page, fileName: string) {
    await page.getByRole("tab", { name: "Blocks" }).click();
    await page.getByRole("button", { name: "Add block" }).click();
    await page.getByRole("menuitem", { name: "Image", exact: true }).click();
    const inspector = page.getByLabel("Block details");
    await inspector.getByRole("button", { name: "Choose image…" }).click();
    const library = page.getByRole("dialog", { name: "Image library" });
    await library.locator('input[type="file"]').setInputFiles({ name: fileName, mimeType: "image/png", buffer: PIXEL });
    // An uploaded picture is selected, so its details are already showing.
    await expect(library.getByRole("button", { name: `Select ${fileName}` })).toHaveAttribute("aria-pressed", "true");
    await expect(library.getByLabel("Image details").getByText("1 × 1 px")).toBeVisible();
    await expect(library.getByLabel("Image details").getByText("This file records no camera details.")).toBeVisible();
    await library.getByRole("button", { name: "Use image" }).click();
    await expect(library).toBeHidden();
    await expect(inspector.getByText(fileName)).toBeVisible();
    return inspector;
  }

  test("a project layout shows a library picture with its size, alignment and numbered caption, saved and read back", async ({ page, request }) => {
    const { project, suffix, headers } = await setup(page, request);
    const name = `E2E picture layout ${suffix}`;
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await newLayout(page, name);
    const fileName = `logo-${suffix}.png`;
    let inspector = await addPicture(page, fileName);

    await test.step("an image needs alternative text unless it is decorative", async () => {
      await expect(inspector.getByText("Describe the image for someone who cannot see it, or mark it decorative.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save new version" }).first()).toBeDisabled();
      await inspector.getByRole("textbox", { name: "Alternative text" }).fill("The company logo");
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("size, alignment and caption are set on the block", async () => {
      await inspector.getByRole("spinbutton", { name: "Width", exact: true }).fill("85");
      await inspector.getByRole("combobox", { name: "Width unit" }).selectOption({ label: "Millimetres (mm)" });
      await inspector.getByRole("combobox", { name: "Alignment" }).selectOption("right");
      await inspector.getByRole("textbox", { name: "Caption" }).fill("The logo of {{project_name}}");
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("the preview draws the picture in its figure, aligned, with a numbered caption", async () => {
      await openDesignerPreview(page);
      const dialog = designerPreviewPanel(page);
      await dialog.getByRole("button", { name: "Run preview" }).click();
      const frame = dialog.frameLocator('iframe[title="Report preview"]');
      await expect(frame.locator("figure.image.align-right img[alt='The company logo']")).toBeVisible();
      await expect(frame.locator("figure.image img")).toHaveAttribute("style", /width:8\.5cm/);
      await expect(frame.getByText(`Figure 1: The logo of ${project.name}`)).toBeVisible();
      await closeDesignerPreview(page);
    });

    await test.step("saving and reloading keep the picture, and the text view names its file", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@image "[0-9a-f-]{36}" alt "The company logo" width 85 mm align right caption/);
      await page.getByRole("tab", { name: "Blocks" }).click();
      inspector = page.getByLabel("Block details");
      await page.locator(".blocklyText.rl-block-title", { hasText: /Image/ }).first().click();
      await expect(inspector.getByText(fileName)).toBeVisible();
    });

    await test.step("an organisation layout cannot use the project's picture, even by id", async () => {
      const library = (await (await request.get(`${API}/projects/${project.id}/report-images`, { headers })).json()).images;
      const own = library.find((image: { filename: string }) => image.filename === fileName);
      expect(own.used_by).toEqual([name]);
      const refused = await request.post(`${API}/orgs/${project.organization_id}/report-layouts`, {
        headers, data: {
          name: `Leaky ${suffix}`, description: "", family: "document",
          tree: { schema_version: 1, family: "document", nodes: [{ type: "image", file: own.id, alt: "x" }] },
        },
      });
      expect(refused.status()).toBeGreaterThanOrEqual(400);
      expect(await refused.text()).toContain("organisation");
    });

    await test.step("a picture that is in use is deleted from the library after a confirmation naming the layout", async () => {
      await page.getByRole("tab", { name: "Blocks" }).click();
      await page.getByLabel("Block details").getByRole("button", { name: "Change image…" }).click();
      const library = page.getByRole("dialog", { name: "Image library" });
      await library.getByRole("button", { name: `Delete ${fileName}` }).click();
      const confirm = page.getByRole("dialog", { name: "Delete this image?" });
      await expect(confirm.getByText(new RegExp(`${name}.* use`))).toBeVisible();
      await confirm.getByRole("button", { name: "Delete" }).click();
      await expect(page.getByText(`Deleted ${fileName}.`)).toBeVisible();
      await expect(library.getByText("No images yet.")).toBeVisible();
    });
  });

  test("an empty Width or Height says Auto, one Auto size keeps the picture's shape, and stretching it is warned about", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await newLayout(page, `E2E auto size ${suffix}`);
    const inspector = await addPicture(page, `square-${suffix}.png`);
    const width = inspector.getByRole("spinbutton", { name: "Width", exact: true });
    const height = inspector.getByRole("spinbutton", { name: "Height", exact: true });
    const stretched = inspector.getByRole("status").filter({ hasText: "will print stretched" });
    await inspector.getByRole("textbox", { name: "Alternative text" }).fill("A square picture");

    await test.step("both sizes start as Auto", async () => {
      await expect(width).toHaveAttribute("placeholder", "Auto");
      await expect(height).toHaveAttribute("placeholder", "Auto");
      await expect(stretched).toBeHidden();
    });

    await test.step("a width alone keeps the shape: no warning, and the preview scales the height with it", async () => {
      await width.fill("6");
      await expect(stretched).toBeHidden();
      await openDesignerPreview(page);
      const dialog = designerPreviewPanel(page);
      await dialog.getByRole("button", { name: "Run preview" }).click();
      await expect(dialog.frameLocator('iframe[title="Report preview"]').locator("figure.image img")).toHaveAttribute("style", /width:6cm;[^"]*height:auto/);
      await closeDesignerPreview(page);
    });

    await test.step("a height that stretches this 1:1 picture is warned about, and emptying it clears the warning", async () => {
      await height.fill("2");
      await expect(stretched).toContainText("3.00:1");
      await expect(stretched).toContainText("1.00:1");
      await height.fill("");
      await expect(stretched).toBeHidden();
    });

    await test.step("the text view accepts auto and writes nothing for it", async () => {
      await page.getByRole("tab", { name: "Text" }).click();
      const text = page.getByRole("textbox", { name: "Layout text" });
      const written = await text.inputValue();
      await text.fill(written.replace(/width 6/, "width auto height 3"));
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(text).toHaveValue(/@image "[0-9a-f-]{36}" alt "A square picture" height 3/);
      await expect(text).not.toHaveValue(/auto/);
    });
  });

  test("unused pictures are filtered and several are deleted together, leaving a picture a layout uses", async ({ page, request }) => {
    const { headers, project, suffix } = await setup(page, request);
    const base = `${API}/projects/${project.id}`;
    const png = (name: string) => ({ multipart: { file: { name, mimeType: "image/png", buffer: PIXEL } } });
    const upload = async (name: string) => (await (await request.post(`${base}/report-images`, { headers, ...png(name) })).json()) as { id: string };
    const names = { used: `used-${suffix}.png`, a: `spare-a-${suffix}.png`, b: `spare-b-${suffix}.png` };
    const used = await upload(names.used);
    await upload(names.a);
    await upload(names.b);
    const made = await request.post(`${base}/report-layouts`, {
      headers, data: {
        name: `Uses a picture ${suffix}`, description: "", family: "document",
        tree: { schema_version: 1, family: "document", nodes: [{ type: "image", file: used.id, alt: "A picture" }] },
      },
    });
    expect(made.ok(), await made.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
    const dialog = page.getByRole("dialog", { name: "New report layout" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(`Designer ${suffix}`);
    await dialog.getByRole("button", { name: "Create" }).click();
    await page.getByRole("tab", { name: "Blocks" }).click();
    await page.getByRole("button", { name: "Add block" }).click();
    await page.getByRole("menuitem", { name: "Image", exact: true }).click();
    await page.getByLabel("Block details").getByRole("button", { name: "Choose image…" }).click();
    const library = page.getByRole("dialog", { name: "Image library" });

    await test.step("the unused filter lists only pictures no layout uses", async () => {
      await library.getByRole("checkbox", { name: /Unused only/ }).check();
      await expect(library.getByRole("button", { name: `Select ${names.a}` })).toBeVisible();
      await expect(library.getByRole("button", { name: `Select ${names.b}` })).toBeVisible();
      await expect(library.getByRole("button", { name: `Select ${names.used}` })).toHaveCount(0);
    });

    await test.step("mark all shown, confirm once, and only the spare pictures go", async () => {
      await library.getByRole("button", { name: "Delete several…" }).click();
      await library.getByRole("button", { name: "Mark all shown" }).click();
      await library.getByRole("button", { name: "Delete 2 pictures…" }).click();
      await page.getByRole("dialog", { name: "Delete 2 pictures?" }).getByRole("button", { name: "Delete" }).click();
      await expect(page.getByText("Deleted 2 pictures.")).toBeVisible();
      await library.getByRole("checkbox", { name: /Unused only/ }).uncheck();
      await expect(library.getByRole("button", { name: `Select ${names.used}` })).toBeVisible();
      await expect(library.getByRole("button", { name: `Select ${names.a}` })).toHaveCount(0);
      const left = (await (await request.get(`${base}/report-images`, { headers })).json()).images as { filename: string }[];
      expect(left.map((i) => i.filename)).toEqual([names.used]);
    });
  });

  test("an EPS or PDF logo uploaded in the library is stored as an SVG and a damaged one is refused with a reason", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await newLayout(page, `EPS ${suffix}`);
    await page.getByRole("tab", { name: "Blocks" }).click();
    await page.getByRole("button", { name: "Add block" }).click();
    await page.getByRole("menuitem", { name: "Image", exact: true }).click();
    await page.getByLabel("Block details").getByRole("button", { name: "Choose image…" }).click();
    const library = page.getByRole("dialog", { name: "Image library" });
    await expect(library.locator('input[type="file"]')).toHaveAttribute("accept", /\.eps.*\.pdf/);

    await test.step("a real EPS is converted on upload and listed as <name>.eps.svg", async () => {
      const eps = "%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 50\n1 0 0 setrgbcolor 10 10 80 30 rectfill\nshowpage\n";
      await library.locator('input[type="file"]').setInputFiles({ name: `logo-${suffix}.eps`, mimeType: "application/postscript", buffer: Buffer.from(eps) });
      await expect(library.getByRole("button", { name: `Select logo-${suffix}.eps.svg` })).toHaveAttribute("aria-pressed", "true");
    });

    await test.step("the first page of a real PDF is converted on upload and listed as <name>.pdf.svg", async () => {
      const content = "1 0 0 rg 10 10 80 30 re f";
      const objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 50] /Contents 4 0 R >>",
        `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
      ];
      let pdf = "%PDF-1.4\n";
      const offsets: number[] = [];
      objects.forEach((body, i) => { offsets.push(pdf.length); pdf += `${i + 1} 0 obj\n${body}\nendobj\n`; });
      const xref = pdf.length;
      pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`;
      pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
      await library.locator('input[type="file"]').setInputFiles({ name: `brand-${suffix}.pdf`, mimeType: "application/pdf", buffer: Buffer.from(pdf) });
      await expect(library.getByRole("button", { name: `Select brand-${suffix}.pdf.svg` })).toHaveAttribute("aria-pressed", "true");
    });

    await test.step("a damaged PDF is refused with the converter's reason", async () => {
      await library.locator('input[type="file"]').setInputFiles({ name: `broken-${suffix}.pdf`, mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nbroken") });
      await expect(library.getByText(/could not be read|Export an SVG or PNG instead/)).toBeVisible();
      await expect(library.getByRole("button", { name: `Select broken-${suffix}.pdf.svg` })).toHaveCount(0);
    });

    await test.step("a file that is not PostScript is refused as an unusable picture", async () => {
      await library.locator('input[type="file"]').setInputFiles({ name: `fake-${suffix}.eps`, mimeType: "application/postscript", buffer: Buffer.from("not a picture") });
      await expect(library.getByText(/Only PNG, JPEG, GIF, WebP and plain SVG|can be used in a report/)).toBeVisible();
      await expect(library.getByRole("button", { name: `Select fake-${suffix}.eps.svg` })).toHaveCount(0);
    });
  });

  test("text wraps beside a picture only when it says which side it is on, and a layered picture has no alignment", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await newLayout(page, `E2E placement ${suffix}`);
    const inspector = await addPicture(page, `placed-${suffix}.png`);
    await inspector.getByRole("textbox", { name: "Alternative text" }).fill("A mark");
    await inspector.getByRole("spinbutton", { name: "Width", exact: true }).fill("4");

    async function previewFrame() {
      await openDesignerPreview(page);
      const dialog = designerPreviewPanel(page);
      await dialog.getByRole("button", { name: "Run preview" }).click();
      return { dialog, frame: dialog.frameLocator('iframe[title="Report preview"]') };
    }

    await test.step("text wraps only beside a picture that says which side it is on", async () => {
      await inspector.getByRole("combobox", { name: "Placement" }).selectOption({ label: "Text wraps beside it" });
      await expect(inspector.getByText("Text wraps beside a picture aligned left or right: choose which side the picture is on.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save new version" }).first()).toBeDisabled();
      await inspector.getByRole("combobox", { name: "Alignment" }).selectOption("right");
      await expect(page.getByText("No problems.")).toBeVisible();
      const { dialog, frame } = await previewFrame();
      await expect(frame.locator("figure.image.wrap-right img[alt='A mark']")).toBeVisible();
      await closeDesignerPreview(page);
    });

    await test.step("a picture over the page has a position from a corner, in the text view and the preview", async () => {
      await inspector.getByRole("combobox", { name: "Alignment" }).selectOption("center");
      await inspector.getByRole("combobox", { name: "Placement" }).selectOption({ label: "Behind the text" });
      await expect(inspector.getByText(/A picture behind the text is placed by its anchor and offsets/)).toBeVisible();
    });
  });

  test("a picture behind the text takes its position from the page corner", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await newLayout(page, `E2E layered ${suffix}`);
    const inspector = await addPicture(page, `layered-${suffix}.png`);
    await inspector.getByRole("textbox", { name: "Alternative text" }).fill("A watermark");
    await inspector.getByRole("combobox", { name: "Placement" }).selectOption({ label: "Behind the text" });
    await inspector.getByRole("combobox", { name: "Position from" }).selectOption({ label: "The corner of the page" });
    await inspector.getByRole("spinbutton", { name: "Across (cm)" }).fill("2");
    await inspector.getByRole("spinbutton", { name: "Down (cm)" }).fill("3");
    await expect(page.getByText("No problems.")).toBeVisible();

    await test.step("the preview lays it under the text at its offsets", async () => {
      await openDesignerPreview(page);
      const dialog = designerPreviewPanel(page);
      await dialog.getByRole("button", { name: "Run preview" }).click();
      const frame = dialog.frameLocator('iframe[title="Report preview"]');
      // The page has no pages on screen, so the position across is a share of the page width (2 cm of an A4's 21 cm).
      await expect(frame.locator("div.layer-anchor.behind figure.image[style*='left:9.52%'][style*='top:3cm'] img[alt='A watermark']")).toBeVisible();
      // The layout holds no title block, so the preview prints no title of its own.
      await expect(frame.locator("h1")).toHaveCount(0);
      await closeDesignerPreview(page);
    });

    await test.step("saving and reading the text view show the placement clauses", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/placement behind anchor page x 2 y 3/);
    });

    await test.step("a picture in line has no position, and the problem says so", async () => {
      await page.getByRole("tab", { name: "Blocks" }).click();
      await page.locator(".blocklyText.rl-block-title", { hasText: /Image/ }).first().click();
      await page.getByLabel("Block details").getByRole("combobox", { name: "Placement" }).selectOption({ label: "In line" });
      await expect(page.getByLabel("Block details").getByText(/Only a picture placed behind or in front of the text has a position/).first()).toBeVisible();
    });
  });

  test("an organisation layout draws an organisation picture for every project", async ({ page, request }) => {
    const { org, project, suffix } = await setup(page, request);
    const name = `E2E org picture ${suffix}`;
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Reports");
    await ensureExpanded(page, "Report layouts");
    await newLayout(page, name);
    const fileName = `wordmark-${suffix}.png`;
    const inspector = await addPicture(page, fileName);
    await inspector.getByRole("checkbox", { name: "Decorative" }).check();
    await expect(page.getByText("No problems.")).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await saveNewVersion(page);
    await expect(page.getByText("Saved as version 2.")).toBeVisible();

    await test.step("the project's library lists the organisation's picture, which the project cannot delete", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Reports");
      await newLayout(page, `E2E project picture ${suffix}`);
      await page.getByRole("tab", { name: "Blocks" }).click();
      await page.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "Image", exact: true }).click();
      await page.getByLabel("Block details").getByRole("button", { name: "Choose image…" }).click();
      const library = page.getByRole("dialog", { name: "Image library" });
      await expect(library.getByText(fileName)).toBeVisible();
      await expect(library.getByText("Organisation", { exact: true })).toBeVisible();
      await expect(library.getByRole("button", { name: `Delete ${fileName}` })).toHaveCount(0);
    });
  });
});
