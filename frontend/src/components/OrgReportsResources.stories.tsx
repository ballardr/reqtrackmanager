import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { OrgAdvancedSettings } from "../api/types";
import { buildLayoutSummary } from "../testing/reportLayoutFixtures";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { OrgReportsResources } from "./OrgReportsResources";

const ORG_ID = "org-1";

const advanced: OrgAdvancedSettings = {
  smtp_host: null, smtp_port: null, smtp_username: null, smtp_use_tls: true,
  pat_max_lifetime_days: null, report_output_retention_days: null, report_file_name: null, report_footer_text: null,
  report_include_cover_page: false, report_chapters_per_component: true, report_output_default_retention_days: 7,
  report_output_max_retention_days: 30, require_2fa: false, allow_self_signup: false, auto_accept_email_domain: null,
  external_user_policy: "disabled", allow_relaxed_child_project_creation: true,
  force_require_change_request_for_approved_links: false,
  allow_ai_approvals: false,
  allow_imported_approval_state: true,
};

/** Serves the organisation's report layouts and, unless `forbidden`, its administrator-only settings. */
function mockApis(options: { forbidden?: boolean } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/report-layouts")) return [buildLayoutSummary({ project_id: null, origin: "organization" })];
    // Report Setup merges these lists with the layouts: empty is a valid answer for each.
    if (path.endsWith("/report-packs") || path.endsWith("/report-placements") || path.endsWith("/report-folders")) return [];
    if (path.endsWith("/report-snippets")) return [];
    if (path.includes("/advanced-settings")) {
      if (options.forbidden) throw new ApiError(403, "Forbidden");
      return advanced;
    }
    throw new Error(`unmocked path: ${path}`);
  });
}

/**
 * The Reports section of Org Resources: the organisation's report layouts, packs, snippets and configuration. Only
 * administrators can read the configuration; everyone else sees the layouts, packs and snippets, whose own calls
 * enforce the report-layout permission.
 */
const meta: Meta<typeof OrgReportsResources> = {
  title: "Components/OrgReportsResources",
  component: OrgReportsResources,
  args: { orgId: ORG_ID },
  decorators: [withStatefulAuth(buildUser({ id: "user-1", is_server_admin: false })), withRouter("/"), withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgReportsResources>;

/** Reports lists the organisation's report layouts, shared with every project. */
export const ListsTheReportLayouts: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const grid = within(await canvas.findByRole("treegrid", { name: "Reports, packs and tables" }));
    await userEvent.click(grid.getByRole("button", { name: "Expand Custom reports" }));
    await expect(grid.getByRole("button", { name: /^Requirements by component/ })).toBeInTheDocument();
  },
};

/** Report templates are gone: the organisation has one look, set on Branding and Configuration. */
export const NoReportTemplatesSectionRemains: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("treegrid", { name: "Reports, packs and tables" });
    await expect(canvas.queryByRole("button", { name: "Report templates section" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "New template" })).not.toBeInTheDocument();
  },
};

/** Reports opens on the Report layouts list with every other section closed (Report layouts itself is open). */
export const OpensOnTheReportLayouts: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("treegrid", { name: "Reports, packs and tables" });
    await expect(canvas.getByRole("button", { name: "Report layouts section" })).toHaveAttribute("aria-expanded", "true");
    for (const title of ["Report snippets", "Configuration"]) {
      await waitFor(() => expect(canvas.getByRole("button", { name: `${title} section` })).toHaveAttribute("aria-expanded", "false"));
    }
  },
};

/** Configuration holds the background-report retention (with the platform default and ceiling), the default report
 * file name and the report look's footer text, cover page and chapter layout; one Save sends only those five fields
 * (an emptied file name is saved as none), so the sign-in, email and token settings that share the endpoint are
 * untouched. */
export const ConfigurationIsSavedWithOneButton: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "put").mockResolvedValue(advanced);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Configuration section" }));
    const retention = await canvas.findByLabelText("Keep background report files for (days)");
    await expect(canvas.getByText(/platform default of 7 days/)).toBeInTheDocument();
    await userEvent.type(retention, "3");
    const fileName = await canvas.findByRole("textbox", { name: "Default report file name" });
    await userEvent.type(fileName, "{{{{project_name}}-{{{{report_title}}", { delay: null });
    await userEvent.type(canvas.getByRole("textbox", { name: "Default footer text" }), "Confidential");
    await userEvent.click(canvas.getByRole("checkbox", { name: "Include cover page" }));
    await userEvent.click(canvas.getByRole("checkbox", { name: /Chapter per/ }));
    await expect(canvas.getAllByRole("button", { name: "Save configuration" })).toHaveLength(1);
    await userEvent.click(canvas.getByRole("button", { name: "Save configuration" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/advanced-settings`, {
        report_output_retention_days: 3, report_file_name: "{{project_name}}-{{report_title}}",
        report_footer_text: "Confidential", report_include_cover_page: true, report_chapters_per_component: false,
      })
    );
  },
};

/** A person who is not an administrator cannot read the settings; the layouts stay and the Configuration section is
 * not offered. */
export const ConfigurationIsHiddenWithoutAdministratorAccess: Story = {
  beforeEach: () => mockApis({ forbidden: true }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("treegrid", { name: "Reports, packs and tables" });
    await expect(canvas.queryByRole("button", { name: "Configuration section" })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsTheReportLayouts, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ListsTheReportLayouts, globals: { theme: "dark" } };
