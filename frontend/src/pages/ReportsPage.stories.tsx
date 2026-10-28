import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { ReportCatalogueEntry } from "../api/reports";
import type { ReportTemplate } from "../api/types";
import { buildReportCatalogueEntry, buildReportResult } from "../testing/reportFixtures";
import { buildProject, buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ReportsPage } from "./ReportsPage";

const PROJECT_ID = "project-1";

const template: ReportTemplate = {
  id: "tpl-1", organization_id: "org-1", name: "Branded template", accent_color_hex: "#475569",
  include_cover_page: true, include_logo: true, footer_text: null,
  chapters_per_component: false,
};

function mockReportsApis(opts: { templates?: ReportTemplate[]; resources?: unknown[]; catalogue?: ReportCatalogueEntry[] } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/report-catalogue")) return opts.catalogue ?? [];
    if (path.startsWith("/api/v1/report-runs") || path.includes("/report-placements")) return [];
    if (path.includes("/modules/")) return buildReportResult();
    if (path.includes("/components")) return [];
    if (path.includes("/categories")) return [];
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return buildProject({ id: PROJECT_ID, organization_id: "org-1", name: "Atlas Platform" });
    if (path.includes("/resources")) return opts.resources ?? [];
    if (path.includes("/report-templates")) return opts.templates ?? [template];
    throw new Error(`unmocked path: ${path}`);
  });
}

const meta: Meta<typeof ReportsPage> = {
  title: "Pages/ReportsPage",
  component: ReportsPage,
  decorators: [withStatefulAuth(buildUser()), withRouter(`/projects/${PROJECT_ID}/reports`, "/projects/:projectId/reports"), withToast()],
};
export default meta;

type Story = StoryObj<typeof ReportsPage>;

export const GeneratePdf: Story = {
  beforeEach: () => {
    mockReportsApis();
    spyOn(api, "postForBlob").mockResolvedValue(new Blob(["pdf"], { type: "application/pdf" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Generate PDF" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Generate PDF" }));
    await waitFor(() =>
      expect(api.postForBlob).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/reports`,
        expect.objectContaining({ format: "pdf", report_template_id: null })
      )
    );
  },
};

/** The Word download sits under "More formats" and posts the same request as the PDF with `format: "docx"`,
 * including the selected template and layout (only CSV omits them). */
export const GenerateWord: Story = {
  beforeEach: () => {
    mockReportsApis();
    spyOn(api, "postForBlob").mockResolvedValue(new Blob(["docx"], { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "More formats" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download Word report" }));
    await waitFor(() =>
      expect(api.postForBlob).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/reports`,
        expect.objectContaining({ format: "docx" })
      )
    );
  },
};

/** The selected branding template is sent with the PDF request; the page carries no introduction or chapter
 * editors (those are written in a report layout). */
export const SelectedTemplateIsSentWithTheRequest: Story = {
  beforeEach: () => {
    mockReportsApis();
    spyOn(api, "postForBlob").mockResolvedValue(new Blob(["pdf"], { type: "application/pdf" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Template & layout section" }));
    await waitFor(() => expect(canvas.getByLabelText("Report template")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Report template"), "tpl-1");
    await expect(canvas.queryByRole("button", { name: "Introduction section" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Generate PDF" }));
    await waitFor(() =>
      expect(api.postForBlob).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/reports`,
        expect.objectContaining({ format: "pdf", report_template_id: "tpl-1" })
      )
    );
  },
};

export const FiltersSection: Story = {
  beforeEach: () => mockReportsApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Filters section" }));
    await waitFor(() => expect(canvas.getByText("Include archived requirements")).toBeInTheDocument());
    await userEvent.type(canvas.getByPlaceholderText("Keyword"), "safety");
    await expect(canvas.getByPlaceholderText("Keyword")).toHaveValue("safety");
  },
};

/** A failed generation now surfaces an error toast (sixth-pass audit — this
 * used to be a `try`/`finally` with no `catch` at all, so a failed request
 * had literally zero visible feedback beyond the button re-enabling). */
export const GenerateFailureShowsToast: Story = {
  beforeEach: () => {
    mockReportsApis();
    spyOn(api, "postForBlob").mockRejectedValue(new ApiError(500, "Report generation failed."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Generate PDF" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Generate PDF" }));
    await waitFor(() => expect(within(document.body).getByText("Report generation failed.")).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Generate PDF" })).toBeEnabled();
  },
};

export const NoResourcesHidesResourceSection: Story = {
  beforeEach: () => mockReportsApis({ resources: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Generate PDF" })).toBeInTheDocument());
    await expect(canvas.queryByText("Resource sections")).not.toBeInTheDocument();
  },
};

export const NoTemplatesHidesTemplatePicker: Story = {
  beforeEach: () => mockReportsApis({ templates: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Template & layout section" }));
    await waitFor(() => expect(canvas.getByText("Chapter layout")).toBeInTheDocument());
    await expect(canvas.queryByLabelText("Report template")).not.toBeInTheDocument();
  },
};

/** Catalogue reports are offered in the same picker as the requirement report
 * (which stays first and the default); picking one runs it. */
export const CatalogueReportsAppearBesideTheRequirementReport: Story = {
  beforeEach: () => mockReportsApis({ catalogue: [buildReportCatalogueEntry()] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("button", { name: "Report: Requirements report" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Generate PDF" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Report: Requirements report" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Choose a report" }));
    await userEvent.click(dialog.getByRole("button", { name: "Expand Fixture Module" }));
    await userEvent.click(dialog.getByRole("button", { name: /^Fixture report/ }));
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Generate PDF" })).not.toBeInTheDocument();
  },
};

/** With no catalogue reports (module off) there is no picker: the page is the requirement report alone. */
export const NoCatalogueReportsHidesThePicker: Story = {
  beforeEach: () => mockReportsApis({ catalogue: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Generate PDF" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: /^Report:/ })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...GeneratePdf, globals: { theme: "light" } };
export const DarkTheme: Story = { ...GeneratePdf, globals: { theme: "dark" } };
