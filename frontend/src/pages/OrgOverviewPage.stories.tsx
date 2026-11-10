import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ReportCatalogueEntry } from "../api/reports";
import type { OrgDashboard, OrgDashboardLayout, OrgModule, OrgOverviewStats, Organization, OverviewMetricsResponse, OverviewWidget } from "../api/types";
import { installedModules } from "../modules/registry";
import { buildReportCatalogueEntry, buildReportResult } from "../testing/reportFixtures";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { OrgOverviewPage } from "./OrgOverviewPage";

const ORG_ID = "org-1";

const org: Organization = {
  id: ORG_ID, name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
  default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
  disabled_at: null, accent_color_hex: null, logo_band_color_hex: null, logo_band_text_color_hex: null, report_accent_color_hex: null, report_include_logo: true, header_title: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
  code: "ACME", project_code_policy: { kind: "alphanumeric", min_length: 2, max_length: 6, assignment: "auto", locked: false }, enforce_code_everywhere: false,
  force_require_change_request_for_approved_links: false,
  allow_ai_approvals: false,
};

const fullTotalStats: OrgOverviewStats = {
  project_count: 6, archived_project_count: 2, requirement_count: 148, member_count: 12, total_file_size_bytes: 4_500_000, is_full_org_total: true,
  storage_quota_bytes: null, uploads_enabled: true, storage_warning: false,
};

const scopedStats: OrgOverviewStats = {
  project_count: 1, archived_project_count: 0, requirement_count: 8, member_count: 12, total_file_size_bytes: 12_000, is_full_org_total: false,
  storage_quota_bytes: null, uploads_enabled: true, storage_warning: false,
};

function page(overrides: Partial<OrgDashboard> = {}): OrgDashboard {
  return { id: "overview", name: "Overview", is_default: true, restricted: false, viewers: [], can_manage: false, ...overrides };
}

function tile(id: string, metric: string): OverviewWidget {
  return { id, type: "metric_tile", title: null, width: 3, height: 2, scope: null, visible: true, config: { metric } };
}

/** The built-in layout: the four headline figures. */
const builtInWidgets: OverviewWidget[] = [
  tile("projects", "org_project_count"), tile("requirements", "org_requirement_count"),
  tile("members", "org_member_count"), tile("storage", "org_file_storage"),
];

const headlineFigures: OverviewMetricsResponse = {
  results: {
    projects: { state: "ok", unit: "count", label: "Projects", projects: 6, value: 6, breakdown: null },
    requirements: { state: "ok", unit: "count", label: "Requirements", projects: 6, value: 148, breakdown: null },
    members: { state: "ok", unit: "count", label: "Members", projects: 6, value: 12, breakdown: null },
    storage: { state: "ok", unit: "bytes", label: "File storage", projects: 6, value: 4_500_000, breakdown: null },
  },
};

function mockOrgOverviewApis(
  overrides: {
    org?: Organization; stats?: OrgOverviewStats; modules?: OrgModule[]; myOrgs?: Organization[];
    /** The dashboard pages the caller may see (default: the built-in Overview alone). */
    pages?: OrgDashboard[];
    /** The widgets every page shows (default: the four headline tiles). */
    widgets?: OverviewWidget[];
    /** Organisation-wide reports the caller can run (the Reports menu's catalogue). */
    reports?: ReportCatalogueEntry[];
  } = {}
) {
  spyOn(api, "post").mockImplementation(async () => headlineFigures);
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/orgs/${ORG_ID}/dashboards`) return overrides.pages ?? [page()];
    if (path.startsWith(`/api/v1/orgs/${ORG_ID}/dashboards/`)) {
      const id = path.split("/").pop();
      const found = (overrides.pages ?? [page()]).find((p) => p.id === id) ?? page();
      const layout: OrgDashboardLayout = { dashboard: found, scope: "this", widgets: overrides.widgets ?? builtInWidgets, built_in: true };
      return layout;
    }
    if (path === `/api/v1/orgs/${ORG_ID}/report-catalogue`) return overrides.reports ?? [];
    if (path.includes("/reports/")) return buildReportResult({ title: "Org fixture report", scope_label: "Acme Corp" });
    if (path.startsWith("/api/v1/report-runs")) return [];
    if (path === `/api/v1/orgs/${ORG_ID}`) return overrides.org ?? org;
    if (path.includes("/overview-stats")) return overrides.stats ?? fullTotalStats;
    if (path.includes("/modules")) return overrides.modules ?? [];
    // `EntitySwitcher`'s own sibling-org fetch — a single-org
    // default means every other story here renders no switcher chevron.
    if (path === "/api/v1/orgs?mine=true") return overrides.myOrgs ?? [org];
    throw new Error(`unmocked path: ${path}`);
  });
}

/**
 * A fixture module registered directly into the real `installedModules`
 * (mirroring `OrgAdminPage.stories.tsx`'s own `FIXTURE_ORG_MODULE_KEY`
 * convention) — proves the generic `orgOverviewSections`/`orgOverviewWidgets`
 * merge-and-render mechanisms `OrgOverviewPage.tsx` uses work for a module
 * other than Compliance, without this story file depending on Compliance's
 * own behaviour. Nothing renders it unless a story's own
 * `mockOrgOverviewApis({ modules: [...] })` explicitly reports this key as
 * enabled, so its permanent presence here causes no cross-story
 * interference (same reasoning `OrgAdminPage.stories.tsx` already
 * documents for its own permanently-pushed fixture).
 */
const FIXTURE_ORG_MODULE_KEY = "fake_org_overview_fixture_module";
const FIXTURE_ORG_OVERVIEW_SECTION_KEY = "fixture-overview-section";

installedModules.push({
  key: FIXTURE_ORG_MODULE_KEY,
  orgOverviewSections: [
    {
      key: FIXTURE_ORG_OVERVIEW_SECTION_KEY,
      label: "Fixture overview section",
      render: ({ orgId }) => <div>Fixture overview section content for org {orgId}</div>,
    },
  ],
  // A widget the module contributes to the organisation dashboards, drawn by the page without importing the module.
  orgOverviewWidgets: [
    { key: "card", render: ({ orgId }) => <div className="card stack">Fixture widget for org {orgId}</div> },
  ],
});

function fixtureOrgModule(overrides: Partial<OrgModule> = {}): OrgModule {
  return {
    module_key: FIXTURE_ORG_MODULE_KEY, name: "Fixture Org Module",
    description: "A fixture module used only by this story file's own org-overview-section assertions.",
    version: "0.1.0", implemented: true, entitled: true, enabled: true, default_project_enabled: true,
    default_enabled: true, frontend_manifest: null, ...overrides,
  };
}

const meta: Meta<typeof OrgOverviewPage> = {
  title: "Pages/OrgOverviewPage",
  component: OrgOverviewPage,
  decorators: [
    withStatefulAuth(buildUser({ id: "user-1", is_server_admin: false })),
    withRouter(`/orgs/${ORG_ID}/overview`, "/orgs/:orgId/overview/:group?"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof OrgOverviewPage>;

/** The built-in Overview page draws the four headline figures as widgets; with nothing else to switch to the menu chrome is hidden. */
export const DashboardShowsTheHeadlineFigures: Story = {
  beforeEach: () => mockOrgOverviewApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: "Acme Corp" })).toBeInTheDocument();
    await waitFor(() => expect(canvas.getByText("148")).toBeInTheDocument());
    await expect(canvas.getByText("Projects")).toBeInTheDocument();
    await expect(canvas.getByText("6")).toBeInTheDocument();
    await expect(canvas.getByText("12")).toBeInTheDocument();
    await expect(canvas.getByText("4.3 MB")).toBeInTheDocument();
    await expect(canvas.queryByText("Fixture overview section content for org org-1")).not.toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: "Overview" })).not.toBeInTheDocument();
    // Neither the Customise action nor the page list is offered to a plain member.
    await expect(canvas.queryByRole("button", { name: "Customise" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Manage dashboards" })).not.toBeInTheDocument();
  },
};

/** The dashboards the person may see are menu entries, the built-in Overview first; another page keeps its own address. */
export const ExtraDashboardPagesAreMenuEntries: Story = {
  beforeEach: () => mockOrgOverviewApis({ pages: [page(), page({ id: "page-2", name: "Risk board", is_default: false })] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    await expect(canvas.getByRole("link", { name: "Risk board" })).toHaveAttribute("href", `/orgs/${ORG_ID}/overview/dashboard-page-2`);
  },
};

/** An organisation administrator is offered Customise (title row) and Manage dashboards; a member is not. */
export const AdministratorsCanCustomiseAndManage: Story = {
  beforeEach: () => mockOrgOverviewApis({ pages: [page({ can_manage: true })] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Manage dashboards" }));
    await expect(await screen.findByRole("dialog", { name: "Dashboards" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Customise" })).toBeInTheDocument();
  },
};

export const ScopedTotalsForAPlainMember: Story = {
  beforeEach: () => mockOrgOverviewApis({ stats: scopedStats }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("These figures are scoped to what you can see, not this organisation's full totals.")).toBeInTheDocument();
  },
};

export const WithModuleContributedSection: Story = {
  beforeEach: () => mockOrgOverviewApis({
    modules: [fixtureOrgModule()],
    widgets: [...builtInWidgets, { id: "fixture", type: `${FIXTURE_ORG_MODULE_KEY}:card`, title: null, width: 12, height: 2, scope: null, visible: true, config: {} }],
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // "Overview" is the always-present, default-selected first group; a module's own section is an additional group, not
    // the default, so its content isn't shown until its link is clicked.
    await expect(await canvas.findByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    await expect(canvas.getByRole("link", { name: "Fixture overview section" })).toBeInTheDocument();
    await expect(canvas.queryByText("Fixture overview section content for org org-1")).not.toBeInTheDocument();
    // The module's widget is drawn by the page from the registry, beside the core figures.
    await expect(await canvas.findByText("Fixture widget for org org-1")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("link", { name: "Fixture overview section" }));
    await expect(canvas.getByText("Fixture overview section content for org org-1")).toBeInTheDocument();
    await expect(canvas.queryByText("Fixture widget for org org-1")).not.toBeInTheDocument();
  },
};

export const ModuleSectionHiddenWhenModuleDisabled: Story = {
  beforeEach: () => mockOrgOverviewApis({ modules: [fixtureOrgModule({ enabled: false })] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("link", { name: "Fixture overview section" })).not.toBeInTheDocument();
    await expect(canvas.queryByText("Fixture headline tile for org org-1")).not.toBeInTheDocument();
    // With the module disabled, "Overview" is once again the
    // only group, so the menu-strip chrome is hidden entirely.
    await expect(canvas.queryByRole("link", { name: "Overview" })).not.toBeInTheDocument();
  },
};

const orgReport = buildReportCatalogueEntry({
  scope: "organization", supports_include_children: false, params: [],
  path: `/api/v1/orgs/${ORG_ID}/modules/fixture_report_module/reports/fixture-report`,
});

/** The "Reports" button beside the title appears only when the organisation catalogue lists a report the caller can
 * run, and opens a dialog that lists it generically (no module is named here). */
export const ReportsButtonOpensTheReportsDialog: Story = {
  beforeEach: () => mockOrgOverviewApis({ reports: [orgReport] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Reports" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Reports" }));
    await expect(await dialog.findByText(/Acme Corp · generated/)).toBeInTheDocument();
  },
};

/** No runnable org report (module off, or no org report role): no Reports menu at all. */
export const ReportsMenuHiddenWithoutOrganisationReports: Story = {
  beforeEach: () => mockOrgOverviewApis({ reports: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Reports" })).not.toBeInTheDocument();
  },
};

/** The files icon link beside the title opens the organisation Files page for every member. */
export const FilesShortcutOpensOrganisationFiles: Story = {
  beforeEach: () => mockOrgOverviewApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await canvas.findByRole("link", { name: "Organisation files" });
    await expect(link).toHaveAttribute("href", expect.stringMatching(/\/orgs\/[^/]+\/files$/));
  },
};

/** The settings icon link beside the title opens the organisation admin page; it is named for the
 * organisation and shown whether or not a Reports menu is present. */
export const SettingsShortcutOpensOrganisationAdmin: Story = {
  beforeEach: () => mockOrgOverviewApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await canvas.findByRole("link", { name: "Organisation settings" });
    await expect(link).toHaveAttribute("href", `/orgs/${ORG_ID}/admin`);
    await expect(link).toHaveAttribute("title", "Organisation settings");
    await expect(canvas.queryByRole("button", { name: "Reports" })).not.toBeInTheDocument();
  },
};

/** With more than one organisation to switch between, a chevron
 * next to the org name opens a popover listing the others as plain links
 * to their own Organisation Overview page. */
export const EntitySwitcherOffersSiblingOrgs: Story = {
  beforeEach: () =>
    mockOrgOverviewApis({
      myOrgs: [org, { ...org, id: "org-2", name: "Globex Corporation" }],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument();

    const trigger = await canvas.findByRole("button", { name: "Switch organisation" });
    await userEvent.click(trigger);
    const dialog = within(document.body).getByRole("dialog", { name: "Switch organisation" });
    await expect(within(dialog).getByRole("link", { name: "Globex Corporation" })).toHaveAttribute(
      "href",
      "/orgs/org-2/overview"
    );
  },
};

export const LightTheme: Story = { ...DashboardShowsTheHeadlineFigures, globals: { theme: "light" } };
export const DarkTheme: Story = { ...DashboardShowsTheHeadlineFigures, globals: { theme: "dark" } };
