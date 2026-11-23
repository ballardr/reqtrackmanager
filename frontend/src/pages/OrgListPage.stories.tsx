import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, spyOn, userEvent, within } from "storybook/test";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { expectHeaderSorts } from "../testing/sortHelpers";
import { withRouter } from "../testing/storybook-helpers";
import { OrgListPage } from "./OrgListPage";

function org(overrides: Partial<Organization>): Organization {
  return {
    id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
    default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
    disabled_at: null, accent_color_hex: null, logo_band_color_hex: null, logo_band_text_color_hex: null, footer_position: null, report_accent_color_hex: null, report_include_logo: true, header_title: null,
    email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
  code: "ACME", project_code_policy: { kind: "alphanumeric", min_length: 2, max_length: 6, assignment: "auto", locked: false }, enforce_code_everywhere: false,
  force_require_change_request_for_approved_links: false,
  allow_ai_approvals: false,
    ...overrides,
  };
}

const meta: Meta<typeof OrgListPage> = {
  title: "Pages/OrgListPage",
  component: OrgListPage,
};
export default meta;

type Story = StoryObj<typeof OrgListPage>;

// The mocks answer only the exact `mine=true` path: the page is the personal membership list, not the
// platform-wide directory `GET /orgs` returns, so a request to the bare path fails the assertions.
export const MultipleOrganisations: Story = {
  decorators: [withRouter("/orgs")],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/orgs?mine=true") {
        return [org({ id: "org-1", name: "Acme Corp" }), org({ id: "org-2", name: "Beta Inc" })];
      }
      throw new Error(`Unexpected api.get(${path})`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Acme Corp")).toBeInTheDocument();
    await expect(canvas.getByText("Beta Inc")).toBeInTheDocument();
  },
};

/** A refused request shows what failed with Retry, not a spinner that never ends; Retry loads the list again. */
export const FailedLoadOffersRetry: Story = {
  decorators: [withRouter("/orgs")],
  beforeEach: () => {
    let calls = 0;
    spyOn(api, "get").mockImplementation(async () => {
      calls += 1;
      if (calls === 1) throw new Error("The server is down.");
      return [org({ id: "org-1", name: "Acme Corp" }), org({ id: "org-2", name: "Beta Inc" })];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("alert")).toHaveTextContent("The organisation list could not be loaded.");
    await userEvent.click(canvas.getByRole("button", { name: "Retry" }));
    await expect(await canvas.findByText("Beta Inc")).toBeInTheDocument();
  },
};

const withOrgsAndAdminRoutes: Decorator = (Story) => (
  <MemoryRouter initialEntries={["/orgs"]}>
    <Routes>
      <Route path="/orgs" element={<Story />} />
      <Route path="/orgs/:id/admin" element={<div>Org admin page</div>} />
    </Routes>
  </MemoryRouter>
);

/** A user in exactly one organisation skips the list and lands on that organisation's admin page (a matching `<Route>` makes the target observable). */
export const SingleOrganisationRedirects: Story = {
  decorators: [withOrgsAndAdminRoutes],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/orgs?mine=true") return [org({ id: "org-1", name: "Acme Corp" })];
      throw new Error(`Unexpected api.get(${path})`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Org admin page")).toBeInTheDocument();
  },
};

export const NoOrganisations: Story = {
  decorators: [withRouter("/orgs")],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/orgs?mine=true") return [];
      throw new Error(`Unexpected api.get(${path})`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("You do not belong to any organisations yet.")).toBeInTheDocument();
  },
};

const withOrgOverviewRoutes: Decorator = (Story) => (
  <MemoryRouter initialEntries={["/org-overview"]}>
    <Routes>
      <Route path="/org-overview" element={<Story />} />
      <Route path="/orgs/:id/overview" element={<div>Org overview page</div>} />
    </Routes>
  </MemoryRouter>
);

/** `target="overview"` (`/org-overview`) redirects to `/orgs/:id/overview` instead of `/orgs/:id/admin`. */
export const SingleOrganisationRedirectsToOverview: Story = {
  args: { target: "overview" },
  decorators: [withOrgOverviewRoutes],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/orgs?mine=true") return [org({ id: "org-1", name: "Acme Corp" })];
      throw new Error(`Unexpected api.get(${path})`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Org overview page")).toBeInTheDocument();
  },
};

const withOrgFilesRoutes: Decorator = (Story) => (
  <MemoryRouter initialEntries={["/org-files"]}>
    <Routes>
      <Route path="/org-files" element={<Story />} />
      <Route path="/orgs/:id/files" element={<div>Org files page</div>} />
    </Routes>
  </MemoryRouter>
);

/** `target="files"` — `/org-files` (the navigation rail entry) redirects straight to the one organisation's Files page. */
export const SingleOrganisationRedirectsToFiles: Story = {
  args: { target: "files" },
  decorators: [withOrgFilesRoutes],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/orgs?mine=true") return [org({ id: "org-1", name: "Acme Corp" })];
      throw new Error(`Unexpected api.get(${path})`);
    });
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Org files page")).toBeInTheDocument();
  },
};

/** With several organisations the entry lists them, each linking to its own Files page. */
export const MultipleOrganisationsListForFiles: Story = {
  args: { target: "files" },
  decorators: [withOrgFilesRoutes],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/orgs?mine=true") {
        return [org({ id: "org-1", name: "Acme Corp" }), org({ id: "org-2", name: "Beta Inc" })];
      }
      throw new Error(`Unexpected api.get(${path})`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Beta Inc" })).toHaveAttribute("href", "/orgs/org-2/files");
  },
};

/** Typing in the client-side search narrows the table to matching organisation names and `ResultCount` shows the narrowed count. */
export const SearchFiltersTheTable: Story = {
  decorators: [withRouter("/orgs")],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/orgs?mine=true") {
        return [
          org({ id: "org-1", name: "Acme Corp" }),
          org({ id: "org-2", name: "Beta Inc" }),
          org({ id: "org-3", name: "Acme Subsidiary" }),
        ];
      }
      throw new Error(`Unexpected api.get(${path})`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Beta Inc")).toBeInTheDocument();

    await userEvent.type(canvas.getByPlaceholderText("Search organisations"), "acme");
    await expect(canvas.getByText("Acme Corp")).toBeInTheDocument();
    await expect(canvas.getByText("Acme Subsidiary")).toBeInTheDocument();
    await expect(canvas.queryByText("Beta Inc")).not.toBeInTheDocument();
    await expect(canvas.getByText("Showing 2 matching · 3 total")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...MultipleOrganisations, globals: { theme: "light" } };
export const DarkTheme: Story = { ...MultipleOrganisations, globals: { theme: "dark" } };

/** The Name header orders the organisations, ascending then descending. */
export const NameHeaderSortsTheOrganisations: Story = {
  decorators: [withRouter("/orgs")],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/orgs?mine=true") return [org({ id: "org-2", name: "Beta Inc" }), org({ id: "org-1", name: "Acme Corp" })];
      throw new Error(`Unexpected api.get(${path})`);
    });
  },
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Org Management" });
    await expectHeaderSorts(table, "Name", ["Acme Corp", "Beta Inc"]);
  },
};