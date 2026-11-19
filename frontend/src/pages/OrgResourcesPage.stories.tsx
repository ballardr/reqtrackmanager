/**
 * Stories for `OrgResourcesPage`: sections arrive only through the module registry. A fixture module registered
 * directly into the real `installedModules` (the `OrgAdminPage.stories.tsx` convention) supplies an ordinary section,
 * a two-section group and a section tied to a sub-component, so the page is exercised without depending on any real
 * module. Nothing renders a fixture unless a story's mock reports its module as enabled.
 *
 * The router decorator mounts both the Org Resources route and the Organisation Overview route and prints the current
 * address, so a redirect is asserted by where the person ends up.
 */
import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { OrgModule, OrgModuleSubComponent, Organization } from "../api/types";
import { installedModules } from "../modules/registry";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { OrgOverviewPage } from "./OrgOverviewPage";
import { OrgResourcesPage } from "./OrgResourcesPage";

const ORG_ID = "org-1";
const FIXTURE_MODULE_KEY = "fake_org_resources_fixture_module";
const OTHER_MODULE_KEY = "fake_org_resources_other_module";
const GATED_SUB_COMPONENT = "gated";

const org: Organization = {
  id: ORG_ID, name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
  default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
  disabled_at: null, accent_color_hex: null, logo_band_color_hex: null, logo_band_text_color_hex: null, footer_position: null, report_accent_color_hex: null, report_include_logo: true, header_title: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
  code: "ACME", project_code_policy: { kind: "alphanumeric", min_length: 2, max_length: 6, assignment: "auto", locked: false }, enforce_code_everywhere: false,
  force_require_change_request_for_approved_links: false,
  allow_ai_approvals: false,
};

installedModules.push(
  {
    key: FIXTURE_MODULE_KEY,
    orgResourceSections: [
      { key: "fixture-plain", label: "Fixture records", render: ({ orgId }) => <div>Fixture records for org {orgId}</div> },
      {
        key: "fixture-group-a", label: "Group A", group: { key: "fixture-group", label: "Fixture group" },
        render: () => <div>Group A content</div>,
      },
      {
        key: "fixture-group-b", label: "Group B", group: { key: "fixture-group", label: "Fixture group" },
        render: () => <div>Group B content</div>,
      },
      {
        key: "fixture-gated", label: "Gated records", subComponent: GATED_SUB_COMPONENT,
        render: () => <div>Gated content</div>,
      },
    ],
  },
  {
    // Declares a key another module already uses, so the page must ignore it rather than shadow the first.
    key: OTHER_MODULE_KEY,
    orgResourceSections: [{ key: "fixture-plain", label: "Duplicate records", render: () => <div>Duplicate content</div> }],
  },
);

function orgModule(key: string, enabled = true): OrgModule {
  return {
    module_key: key, name: key, description: "Fixture module.", version: "0.1.0", implemented: true, entitled: true,
    enabled, default_project_enabled: true, default_enabled: true, frontend_manifest: null,
  };
}

function subComponent(enabled: boolean): OrgModuleSubComponent {
  return {
    module_key: FIXTURE_MODULE_KEY, subcomponent_key: GATED_SUB_COMPONENT, name: "Gated", default_enabled: true,
    enabled, default_project_enabled: true, has_org_override: false,
  };
}

function mockApis(options: { modules?: OrgModule[]; subComponents?: "on" | "off" | "forbidden"; siblingOrg?: boolean } = {}) {
  const modules = options.modules ?? [orgModule(FIXTURE_MODULE_KEY), orgModule(OTHER_MODULE_KEY)];
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/orgs/${ORG_ID}`) return org;
    if (path === `/api/v1/orgs/${ORG_ID}/modules`) return modules;
    if (path === `/api/v1/orgs/${ORG_ID}/modules/${FIXTURE_MODULE_KEY}/subcomponents`) {
      if (options.subComponents === "forbidden") throw new ApiError(403, "Forbidden");
      return [subComponent(options.subComponents !== "off")];
    }
    if (path === "/api/v1/orgs?mine=true") return options.siblingOrg ? [org, { ...org, id: "org-2", name: "Globex Corporation" }] : [org];
    // The Overview page mounted by the redirect story requests more before it redirects; nothing there is asserted.
    return [];
  });
  spyOn(api, "post").mockImplementation(async () => ({ results: {} }));
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

const withRoutes: Decorator = (Story, context) => (
  <MemoryRouter initialEntries={[(context.parameters.initialPath as string | undefined) ?? `/orgs/${ORG_ID}/resources`]}>
    <Routes>
      <Route path="/orgs/:orgId/resources/:group?/:section?" element={<Story />} />
      <Route path="/orgs/:orgId/overview/:group?" element={<OrgOverviewPage />} />
    </Routes>
    <LocationProbe />
  </MemoryRouter>
);

const meta: Meta<typeof OrgResourcesPage> = {
  title: "Pages/OrgResourcesPage",
  component: OrgResourcesPage,
  decorators: [withStatefulAuth(buildUser({ id: "user-1", is_server_admin: false })), withRoutes],
};
export default meta;

type Story = StoryObj<typeof OrgResourcesPage>;

const probe = (canvas: ReturnType<typeof within>) => canvas.getByTestId("location");

/** The menu lists the enabled modules' sections in module order, the first is open, and the title row names the
 * organisation with its switcher and a Settings link. */
export const ListsTheSectionsOfEnabledModules: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: "Acme Corp" })).toBeInTheDocument();
    const first = await canvas.findByRole("link", { name: "Fixture records" });
    await expect(first).toHaveAttribute("aria-current", "page");
    await expect(first).toHaveAttribute("href", `/orgs/${ORG_ID}/resources/fixture-plain`);
    await expect(canvas.getByText(`Fixture records for org ${ORG_ID}`)).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Organisation settings" })).toHaveAttribute("href", `/orgs/${ORG_ID}/admin`);
  },
};

/** With more than one organisation, the chevron beside the name lists the others as links to their own Org Resources. */
export const TheSwitcherOffersSiblingOrganisations: Story = {
  beforeEach: () => mockApis({ siblingOrg: true }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Switch organisation" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Switch organisation" });
    await expect(within(dialog).getByRole("link", { name: "Globex Corporation" })).toHaveAttribute("href", "/orgs/org-2/resources");
  },
};

/** A section declared twice is offered once, by the first module; the second is ignored, not shadowing it. */
export const ADuplicateSectionKeyIsIgnored: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(console, "error").mockImplementation(() => undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: "Fixture records" });
    await expect(canvas.queryByRole("link", { name: "Duplicate records" })).not.toBeInTheDocument();
  },
};

/** Choosing another section changes the address and the content. */
export const ChoosingASectionOpensIt: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: /Fixture group/ }));
    await userEvent.click(await canvas.findByRole("link", { name: "Group B" }));
    await expect(await canvas.findByText("Group B content")).toBeInTheDocument();
    await expect(probe(canvas)).toHaveTextContent(`/orgs/${ORG_ID}/resources/fixture-group/fixture-group-b`);
  },
};

/** A bare group address redirects to the group's first section. */
export const AGroupAddressOpensItsFirstSection: Story = {
  parameters: { initialPath: `/orgs/${ORG_ID}/resources/fixture-group` },
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Group A content")).toBeInTheDocument();
    await expect(probe(canvas)).toHaveTextContent(`/orgs/${ORG_ID}/resources/fixture-group/fixture-group-a`);
  },
};

/** An address naming no section (a module since switched off, a mistyped key) returns to the page. */
export const AnUnknownAddressReturnsToThePage: Story = {
  parameters: { initialPath: `/orgs/${ORG_ID}/resources/no-such-section` },
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: "Fixture records" });
    await waitFor(() => expect(probe(canvas)).toHaveTextContent(new RegExp(`^/orgs/${ORG_ID}/resources$`)));
  },
};

/** A module that is off contributes nothing, and with nothing to list the page says so. */
export const ADisabledModuleContributesNothing: Story = {
  beforeEach: () => mockApis({ modules: [orgModule(FIXTURE_MODULE_KEY, false), orgModule(OTHER_MODULE_KEY, false)] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/No organisation resources are available/)).toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: "Fixture records" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument();
  },
};

/** A section tied to a sub-component is left out while the organisation has that sub-component off. */
export const ASectionWhoseSubComponentIsOffIsHidden: Story = {
  beforeEach: () => mockApis({ subComponents: "off" }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: "Fixture records" });
    await expect(canvas.queryByRole("link", { name: "Gated records" })).not.toBeInTheDocument();
  },
};

/** The sub-component state is readable only by administrators; where the caller cannot read it the section is offered
 * and its own endpoints decide what the person may do. */
export const ASectionIsOfferedWhenSubComponentStateIsUnreadable: Story = {
  beforeEach: () => mockApis({ subComponents: "forbidden" }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("link", { name: "Gated records" })).toBeInTheDocument();
  },
};

/** The Organisation Overview address a section used to have redirects here, keeping the query string. */
export const AnEarlierOverviewAddressRedirectsKeepingTheQuery: Story = {
  parameters: { initialPath: `/orgs/${ORG_ID}/overview/fixture-plain?filter=open` },
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(`Fixture records for org ${ORG_ID}`)).toBeInTheDocument();
    await expect(probe(canvas)).toHaveTextContent(`/orgs/${ORG_ID}/resources/fixture-plain?filter=open`);
  },
};

export const LightTheme: Story = { ...ListsTheSectionsOfEnabledModules, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ListsTheSectionsOfEnabledModules, globals: { theme: "dark" } };
