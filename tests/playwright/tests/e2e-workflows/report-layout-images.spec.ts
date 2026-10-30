import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, saveNewVersion, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

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
    await selectProjectAdminGroup(page, "Report Setup");
    await newLayout(page, name);
    const fileName = `logo-${suffix}.png`;
    let inspector = await addPicture(page, fileName);

    await test.step("an image needs alternative text unless it is decorative", async () => {
      await expect(inspector.getByText("Describe the image for someone who cannot see it, or mark it decorative.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save new version" })).toBeDisabled();
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
      await page.getByRole("button", { name: "Preview", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Report preview" });
      await dialog.getByRole("button", { name: "Run preview" }).click();
      const frame = dialog.frameLocator('iframe[title="Report preview"]');
      await expect(frame.locator("figure.image.align-right img[alt='The company logo']")).toBeVisible();
      await expect(frame.locator("figure.image img")).toHaveAttribute("style", /width:8\.5cm/);
      await expect(frame.getByText(`Figure 1: The logo of ${project.name}`)).toBeVisible();
      await dialog.getByRole("button", { name: "Close" }).click();
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

  test("text wraps beside a picture only when it says which side it is on, and a layered picture has no alignment", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");
    await newLayout(page, `E2E placement ${suffix}`);
    const inspector = await addPicture(page, `placed-${suffix}.png`);
    await inspector.getByRole("textbox", { name: "Alternative text" }).fill("A mark");
    await inspector.getByRole("spinbutton", { name: "Width", exact: true }).fill("4");

    async function previewFrame() {
      await page.getByRole("button", { name: "Preview", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Report preview" });
      await dialog.getByRole("button", { name: "Run preview" }).click();
      return { dialog, frame: dialog.frameLocator('iframe[title="Report preview"]') };
    }

    await test.step("text wraps only beside a picture that says which side it is on", async () => {
      await inspector.getByRole("combobox", { name: "Placement" }).selectOption({ label: "Text wraps beside it" });
      await expect(inspector.getByText("Text wraps beside a picture aligned left or right: choose which side the picture is on.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save new version" })).toBeDisabled();
      await inspector.getByRole("combobox", { name: "Alignment" }).selectOption("right");
      await expect(page.getByText("No problems.")).toBeVisible();
      const { dialog, frame } = await previewFrame();
      await expect(frame.locator("figure.image.wrap-right img[alt='A mark']")).toBeVisible();
      await dialog.getByRole("button", { name: "Close" }).click();
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
    await selectProjectAdminGroup(page, "Report Setup");
    await newLayout(page, `E2E layered ${suffix}`);
    const inspector = await addPicture(page, `layered-${suffix}.png`);
    await inspector.getByRole("textbox", { name: "Alternative text" }).fill("A watermark");
    await inspector.getByRole("combobox", { name: "Placement" }).selectOption({ label: "Behind the text" });
    await inspector.getByRole("combobox", { name: "Position from" }).selectOption({ label: "The corner of the page" });
    await inspector.getByRole("spinbutton", { name: "Across (cm)" }).fill("2");
    await inspector.getByRole("spinbutton", { name: "Down (cm)" }).fill("3");
    await expect(page.getByText("No problems.")).toBeVisible();

    await test.step("the preview lays it under the text at its offsets", async () => {
      await page.getByRole("button", { name: "Preview", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Report preview" });
      await dialog.getByRole("button", { name: "Run preview" }).click();
      const frame = dialog.frameLocator('iframe[title="Report preview"]');
      await expect(frame.locator("div.layer-anchor.behind figure.image[style*='left:2cm'][style*='top:3cm'] img[alt='A watermark']")).toBeVisible();
      await dialog.getByRole("button", { name: "Close" }).click();
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
    await selectOrgAdminGroup(page, "Templates & reports");
    await ensureExpanded(page, "Report Setup");
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
      await selectProjectAdminGroup(page, "Report Setup");
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
