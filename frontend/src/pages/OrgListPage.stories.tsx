import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, spyOn, within } from "storybook/test";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { withRouter } from "../testing/storybook-helpers";
import { OrgListPage } from "./OrgListPage";

function org(overrides: Partial<Organization>): Organization {
  return {
    id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
    default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
    disabled_at: null, accent_color_hex: null, header_title: null,
    email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
    ...overrides,
  };
}

const meta: Meta<typeof OrgListPage> = {
  title: "Pages/OrgListPage",
  component: OrgListPage,
};
export default meta;

type Story = StoryObj<typeof OrgListPage>;

// `mine=true` is asserted, not just supplied, in every story below (the
// mock only returns data for that exact path): `OrgListPage` backs the nav
// rail's "My organisations" link, a *personal* membership list, not the
// server-admin platform-wide directory `GET /orgs` (no `mine`) returns —
// a regression back to the bare path would leave these mocks unmatched and
// the assertions below failing, rather than silently passing against the
// wrong endpoint.
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

const withOrgsAndAdminRoutes: Decorator = (Story) => (
  <MemoryRouter initialEntries={["/orgs"]}>
    <Routes>
      <Route path="/orgs" element={<Story />} />
      <Route path="/orgs/:id/admin" element={<div>Org admin page</div>} />
    </Routes>
  </MemoryRouter>
);

/** A user in exactly one organisation skips the list and lands straight on
 * that org's admin page — rendered here with a matching `<Route>` so the
 * `<Navigate>` target is observable. */
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
    await expect(canvas.getByText("You don't belong to any organisations yet.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...MultipleOrganisations, globals: { theme: "light" } };
export const DarkTheme: Story = { ...MultipleOrganisations, globals: { theme: "dark" } };
