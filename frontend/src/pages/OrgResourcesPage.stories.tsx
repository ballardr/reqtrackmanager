/**
 * Stories for `OrgResourcesPage`: sections arrive only through the module registry. A fixture module registered
 * into the real `installedModules` (as in `OrgAdminPage.stories.tsx`) supplies an ordinary section, a two-section
 * group and a section tied to a sub-component; it renders only when a story's mock reports its module as enabled.
 * The router decorator prints the current address, so a redirect is asserted by where the person ends up.
 */
import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgEnabledModule, Organization } from "../api/types";
import { installedModules } from "../modules/registry";
import { buildUsage, buildVocabulary } from "../testing/tagsFixtures";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { OrgResourcesPage } from "./OrgResourcesPage";

const ORG_ID = "org-1";
const FIXTURE_MODULE_KEY = "fake_org_resources_fixture_module";
const OTHER_MODULE_KEY = "fake_org_resources_other_module";
const SHADOWING_MODULE_KEY = "fake_org_resources_shadowing_module";
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
  {
    // Declares the key of a section core owns, so the page must ignore it.
    key: SHADOWING_MODULE_KEY,
    orgResourceSections: [{ key: "reports", label: "Shadow of Reports", render: () => <div>Shadow content</div> }],
  },
);

/** A module the organisation can use, with the sub-components that are off. */
function orgModule(key: string, disabledSubComponents: string[] = []): OrgEnabledModule {
  return { module_key: key, disabled_sub_components: disabledSubComponents };
}

/** Serves the member-readable `enabled-modules` list: a module that is off is simply absent from it. */
function mockApis(options: { modules?: OrgEnabledModule[]; subComponentOff?: boolean; siblingOrg?: boolean } = {}) {
  const modules = options.modules ?? [orgModule(FIXTURE_MODULE_KEY, options.subComponentOff ? [GATED_SUB_COMPONENT] : []), orgModule(OTHER_MODULE_KEY)];
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/orgs/${ORG_ID}`) return org;
    if (path === `/api/v1/orgs/${ORG_ID}/enabled-modules`) return modules;
    // The Reports section (core) is the landing section when no module contributes one.
    if (path.endsWith("/starters")) return { missing: [] };
    if (path === `/api/v1/orgs/${ORG_ID}/tags`) return buildVocabulary({ own_mode: null });
    if (path === `/api/v1/orgs/${ORG_ID}/tags/usage`) return buildUsage();
    if (path === "/api/v1/orgs?mine=true") return options.siblingOrg ? [org, { ...org, id: "org-2", name: "Globex Corporation" }] : [org];
    return [];
  });
  spyOn(api, "post").mockImplementation(async () => ({ results: {} }));
  spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

const withRoutes: Decorator = (Story, context) => (
  <MemoryRouter initialEntries={[(context.parameters.initialPath as string | undefined) ?? `/orgs/${ORG_ID}/resources`]}>
    <Routes>
      <Route path="/orgs/:orgId/resources/:group?/:section?" element={<Story />} />
    </Routes>
    <LocationProbe />
  </MemoryRouter>
);

const meta: Meta<typeof OrgResourcesPage> = {
  title: "Pages/OrgResourcesPage",
  component: OrgResourcesPage,
  // Routes first so the signed-in context wraps every route, not only the page under test.
  decorators: [withRoutes, withStatefulAuth(buildUser({ id: "user-1", is_server_admin: false }))],
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

/** A module that is off contributes nothing; the page still offers the sections core owns (Reports and Tags) and opens
 * on the first of them. */
export const ADisabledModuleContributesNothing: Story = {
  beforeEach: () => mockApis({ modules: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("link", { name: "Reports" })).toHaveAttribute("aria-current", "page");
    await expect(canvas.getByRole("link", { name: "Tags" })).toHaveAttribute("href", `/orgs/${ORG_ID}/resources/tags`);
    await expect(canvas.queryByRole("link", { name: "Fixture records" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument();
  },
};

/** Reports and Tags follow the modules' sections, whichever modules are enabled. */
export const CoreSectionsFollowTheModuleSections: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: "Fixture records" });
    const labels = canvas.getAllByRole("link").map((l) => l.textContent);
    await expect(labels.indexOf("Reports")).toBeGreaterThan(labels.indexOf("Fixture records"));
    await expect(labels.indexOf("Tags")).toBeGreaterThan(labels.indexOf("Reports"));
  },
};

/** A module section that reuses a core key is ignored, not shadowing Reports or Tags. */
export const AModuleSectionCannotShadowACoreSection: Story = {
  beforeEach: () => {
    mockApis({ modules: [orgModule(FIXTURE_MODULE_KEY), orgModule(SHADOWING_MODULE_KEY)] });
    spyOn(console, "error").mockImplementation(() => undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: "Fixture records" });
    await expect(canvas.queryByRole("link", { name: "Shadow of Reports" })).not.toBeInTheDocument();
    await expect(canvas.getAllByRole("link", { name: "Reports" })).toHaveLength(1);
  },
};

/** A section tied to a sub-component is left out while the organisation has that sub-component off. */
export const ASectionWhoseSubComponentIsOffIsHidden: Story = {
  beforeEach: () => mockApis({ subComponentOff: true }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: "Fixture records" });
    await expect(canvas.queryByRole("link", { name: "Gated records" })).not.toBeInTheDocument();
  },
};

/** The page reads the member-readable list only: it never asks for the administrator-only module list, so a person who
 * is not an administrator sees the same sections. */
export const ThePageNeverAsksForTheAdministratorOnlyModuleList: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("link", { name: "Gated records" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Reports" })).toBeInTheDocument();
    const paths = (api.get as unknown as { mock: { calls: string[][] } }).mock.calls.map((c) => c[0]);
    await expect(paths.some((p) => p.endsWith("/modules") || p.includes("/subcomponents"))).toBe(false);
    await expect(paths).toContain(`/api/v1/orgs/${ORG_ID}/enabled-modules`);
  },
};

export const LightTheme: Story = { ...ListsTheSectionsOfEnabledModules, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ListsTheSectionsOfEnabledModules, globals: { theme: "dark" } };
