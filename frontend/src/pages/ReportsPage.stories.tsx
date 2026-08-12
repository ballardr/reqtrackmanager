import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ProjectReportConfig, ReportTemplate } from "../api/types";
import { buildProject, buildUser, withRouter, withStatefulAuth } from "../testing/storybook-helpers";
import { ReportsPage } from "./ReportsPage";

const PROJECT_ID = "project-1";

const reportConfig: ProjectReportConfig = {
  intro: "This project delivers the Atlas platform.",
  chapters: [{ title: "Scope", body: "What this covers." }],
  appendices: [],
  intro_is_organisation_default: false,
  chapters_is_organisation_default: true,
  appendices_is_organisation_default: true,
  default_report_template_id: null,
};

const template: ReportTemplate = {
  id: "tpl-1", organization_id: "org-1", name: "Branded template", accent_color_hex: "#475569",
  include_cover_page: true, include_logo: true, footer_text: null,
  intro: "Template-provided introduction.", chapters: [{ title: "Overview", body: "Template chapter body." }],
  appendices: [], chapters_per_component: false,
};

function mockReportsApis(opts: { templates?: ReportTemplate[]; resources?: unknown[] } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/components")) return [];
    if (path.includes("/categories")) return [];
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return buildProject({ id: PROJECT_ID, organization_id: "org-1", name: "Atlas Platform" });
    if (path.includes("/resources")) return opts.resources ?? [];
    if (path.includes("/report-templates")) return opts.templates ?? [template];
    if (path.includes("/report-config")) return reportConfig;
    throw new Error(`unmocked path: ${path}`);
  });
}

const meta: Meta<typeof ReportsPage> = {
  title: "Pages/ReportsPage",
  component: ReportsPage,
  decorators: [withStatefulAuth(buildUser()), withRouter(`/projects/${PROJECT_ID}/reports`, "/projects/:projectId/reports")],
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
        `/api/v1/projects/${PROJECT_ID}/reports/pdf`,
        expect.objectContaining({ pre_markdown: expect.stringContaining("Atlas platform") })
      )
    );
  },
};

/** Selecting a report template swaps the intro/chapters editors to the
 * template's own content (`effectiveContentFor`) — a documented, deliberate
 * mirror of `resolve_report_config_with_template`'s server-side precedence
 * (see docs/decisions.md and ReportsPage.tsx's own docstring); this story
 * pins that precedence so a future backend change to the fallback order is
 * caught here too. */
export const SelectingTemplateSwapsIntroContent: Story = {
  beforeEach: () => mockReportsApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Template & layout section" }));
    await waitFor(() => expect(canvas.getByLabelText("Report template")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Report template"), "tpl-1");
    await userEvent.click(canvas.getByRole("button", { name: "Introduction section" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Template-provided introduction.")).toBeInTheDocument());
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

export const LightTheme: Story = { ...GeneratePdf, globals: { theme: "light" } };
export const DarkTheme: Story = { ...GeneratePdf, globals: { theme: "dark" } };
