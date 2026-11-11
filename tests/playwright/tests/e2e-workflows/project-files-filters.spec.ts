import crypto from "node:crypto";

import { expect, test } from "@playwright/test";

import { apiHeaders, installCleanupHook, loginAs, onCleanup, openProject, PERSONAS, PROJECT_NAMES } from "./helpers";

const API = "http://localhost:8000/api/v1";
/** A 1 x 1 pixel PNG. */
const PIXEL = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

/**
 * Job to be done: find a file a project holds without scrolling a flat list: a picture in the project's report image
 * library shows on the Files page with a preview, and the page can be searched and filtered by source and type.
 *
 * The test adds its own uniquely named library picture to Alpha-1 and removes it afterwards, so it passes alone, in
 * any order and repeated; the seeded attachment "e2e-direct-attachment.txt" is only read.
 */
test.describe("project files: report image library, search and filters", () => {
  installCleanupHook();

  test("a library picture is listed with a preview, found by search, source and type, and the filters survive a visit to its origin", async ({ page, request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 6)}`;
    const picture = `e2e-library-${suffix}.png`;
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    const projectId = new URL(page.url()).pathname.split("/")[2];

    const headers = await apiHeaders(request, PERSONAS.orgAdminAlphaBeta.email);
    let uploadedId = "";
    onCleanup(async (req) => {
      if (!uploadedId) return;
      await req.delete(`${API}/projects/${projectId}/report-images/${uploadedId}`, { headers: await apiHeaders(req, PERSONAS.orgAdminAlphaBeta.email) });
    });
    const uploaded = await request.post(`${API}/projects/${projectId}/report-images`, {
      headers, multipart: { file: { name: picture, mimeType: "image/png", buffer: PIXEL } },
    });
    expect(uploaded.ok()).toBeTruthy();
    uploadedId = (await uploaded.json()).id;

    const searched: string[] = [];
    page.on("request", (req) => searched.push(req.url()));
    await page.getByRole("link", { name: "Files", exact: true }).and(page.locator('[href*="/projects/"]')).click();
    const row = page.locator("tr", { has: page.getByRole("link", { name: picture, exact: true }) });

    await test.step("the picture is listed as a report image library file, with a preview and its origin", async () => {
      await expect(row).toBeVisible();
      await expect(row.getByText("Report image library")).toBeVisible();
      await expect(row.getByRole("img", { name: picture })).toBeVisible();
      await expect(row.getByRole("link", { name: "Report setup" })).toHaveAttribute("href", `/projects/${projectId}/admin/reportSetup`);
    });

    await test.step("the filter panel is level with the title", async () => {
      const title = await page.getByRole("heading", { name: "Files", level: 1 }).boundingBox();
      const panel = await page.getByRole("heading", { name: "Filters", level: 2 }).boundingBox();
      expect(Math.abs((title?.y ?? 0) - (panel?.y ?? 99999))).toBeLessThan(40);
    });

    await test.step("searching by file name narrows the list, and the typed text is in no request URL", async () => {
      const search = page.getByRole("textbox", { name: "Search file names" });
      await search.fill(`library-${suffix}`);
      await expect(row).toBeVisible();
      await expect(page.getByRole("link", { name: "e2e-direct-attachment.txt" })).toBeHidden();
      await search.fill("no-such-file-name-anywhere");
      await expect(page.getByText("No files match these filters.")).toBeVisible();
      expect(searched.filter((url) => url.includes("no-such-file-name-anywhere") && url.includes("/api/"))).toEqual([]);
      await search.fill("");
      await expect(page.getByRole("link", { name: "e2e-direct-attachment.txt" })).toBeVisible();
    });

    await test.step("the Source and File type filters narrow by where a file hangs and what it is", async () => {
      await page.getByRole("combobox", { name: "Source" }).selectOption({ label: "Report image library" });
      await expect(row).toBeVisible();
      await expect(page.getByRole("link", { name: "e2e-direct-attachment.txt" })).toBeHidden();
      await expect(page).toHaveURL(/source=report_image/);

      await page.getByRole("combobox", { name: "Source" }).selectOption({ label: "All sources" });
      await page.getByRole("combobox", { name: "File type" }).selectOption({ label: "Document" });
      await expect(page.getByRole("link", { name: "e2e-direct-attachment.txt" })).toBeVisible();
      await expect(row).toBeHidden();
      await page.getByRole("combobox", { name: "File type" }).selectOption({ label: "Image" });
      await expect(row).toBeVisible();
    });

    await test.step("opening the origin and coming back keeps the filters", async () => {
      await page.getByRole("combobox", { name: "Source" }).selectOption({ label: "Report image library" });
      await row.getByRole("link", { name: "Report setup" }).click();
      await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/admin/reportSetup`));
      await page.goBack();
      await expect(page).toHaveURL(/source=report_image/);
      await expect(page.getByRole("combobox", { name: "Source" })).toHaveValue("report_image");
      await expect(row).toBeVisible();
    });
  });
});
