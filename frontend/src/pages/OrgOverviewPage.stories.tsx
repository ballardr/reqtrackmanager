import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgModule, OrgOverviewStats, Organization } from "../api/types";
import { installedModules } from "../modules/registry";
import { buildUser, withRouter, withStatefulAuth } from "../testing/storybook-helpers";
import { OrgOverviewPage } from "./OrgOverviewPage";

const ORG_ID = "org-1";

const org: Organization = {
  id: ORG_ID, name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
  default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
  disabled_at: null, accent_color_hex: null, header_title: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
};

const fullTotalStats: OrgOverviewStats = {
  project_count: 6, requirement_count: 148, member_count: 12, total_file_size_bytes: 4_500_000, is_full_org_total: true,
};

const scopedStats: OrgOverviewStats = {
  project_count: 1, requirement_count: 8, member_count: 12, total_file_size_bytes: 12_000, is_full_org_total: false,
};

function mockOrgOverviewApis(overrides: { org?: Organization; stats?: OrgOverviewStats; modules?: OrgModule[] } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/orgs/${ORG_ID}`) return overrides.org ?? org;
    if (path.includes("/overview-stats")) return overrides.stats ?? fullTotalStats;
    if (path.includes("/modules")) return overrides.modules ?? [];
    throw new Error(`unmocked path: ${path}`);
  });
}

/**
 * A fixture module registered directly into the real `installedModules`
 * (mirroring `OrgAdminPage.stories.tsx`'s own `FIXTURE_ORG_MODULE_KEY`
 * convention) — proves the generic `orgOverviewSections`/`orgOverviewTiles`
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
  // Phase 25b — a module's headline stat tile in the page's own
  // always-visible stats header (`orgOverviewTiles`), distinct from the
  // `orgOverviewSections` group above which only renders once a group is
  // selected.
  orgOverviewTiles: [
    {
      key: "fixture-tile",
      render: ({ orgId }) => <div className="card stack">Fixture headline tile for org {orgId}</div>,
    },
  ],
});

function fixtureOrgModule(overrides: Partial<OrgModule> = {}): OrgModule {
  return {
    module_key: FIXTURE_ORG_MODULE_KEY, name: "Fixture Org Module",
    description: "A fixture module used only by this story file's own org-overview-section assertions.",
    version: "0.1.0", implemented: true, entitled: true, enabled: true, default_enabled: true,
    frontend_manifest: null, ...overrides,
  };
}

const meta: Meta<typeof OrgOverviewPage> = {
  title: "Pages/OrgOverviewPage",
  component: OrgOverviewPage,
  decorators: [
    withStatefulAuth(buildUser({ id: "user-1", is_server_admin: false })),
    withRouter(`/orgs/${ORG_ID}/overview`, "/orgs/:orgId/overview/:group?"),
  ],
};
export default meta;

type Story = StoryObj<typeof OrgOverviewPage>;

export const StatsOnlyNoModuleSections: Story = {
  beforeEach: () => mockOrgOverviewApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument();
    await expect(canvas.getByText("6")).toBeInTheDocument();
    await expect(canvas.getByText("148")).toBeInTheDocument();
    await expect(canvas.getByText("12")).toBeInTheDocument();
    await expect(canvas.getByText("4.3 MB")).toBeInTheDocument();
    await expect(canvas.queryByText("Fixture overview section content for org org-1")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Fixture headline tile for org org-1")).not.toBeInTheDocument();
  },
};

/** Phase 25c — the core project/requirement/member/file-storage stats
 * render as one `.grid.grid-metrics` grid, the same equal-size-cells
 * utility `ProjectOverviewPage.tsx`'s own metric tiles use, rather than a
 * `flex-wrap` row. */
export const CoreStatsRenderAsAGrid: Story = {
  beforeEach: () => mockOrgOverviewApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const projectsCard = await waitFor(() => canvas.getByText("Projects").closest(".card"));
    await expect(projectsCard?.closest(".grid.grid-metrics")).not.toBeNull();
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
  beforeEach: () => mockOrgOverviewApis({ modules: [fixtureOrgModule()] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Fixture overview section" })).toBeInTheDocument();
    await expect(canvas.getByText("Fixture overview section content for org org-1")).toBeInTheDocument();
    // Phase 25b — the module's headline tile renders directly in the
    // always-visible stats header, alongside the core Projects/Requirements/
    // Members/File storage tiles, not gated behind selecting a group.
    await expect(canvas.getByText("Fixture headline tile for org org-1")).toBeInTheDocument();
  },
};

export const ModuleSectionHiddenWhenModuleDisabled: Story = {
  beforeEach: () => mockOrgOverviewApis({ modules: [fixtureOrgModule({ enabled: false })] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("link", { name: "Fixture overview section" })).not.toBeInTheDocument();
    await expect(canvas.queryByText("Fixture headline tile for org org-1")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...StatsOnlyNoModuleSections, globals: { theme: "light" } };
export const DarkTheme: Story = { ...StatsOnlyNoModuleSections, globals: { theme: "dark" } };
