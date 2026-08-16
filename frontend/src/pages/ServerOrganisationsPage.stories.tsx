import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { withRouter } from "../testing/storybook-helpers";
import { ServerOrganisationsPage } from "./ServerOrganisationsPage";

function org(overrides: Partial<Organization>): Organization {
  return {
    id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
    default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
    disabled_at: null, accent_color_hex: null, header_title: null,
    email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
    ...overrides,
  };
}

const meta: Meta<typeof ServerOrganisationsPage> = {
  title: "Pages/ServerOrganisationsPage",
  component: ServerOrganisationsPage,
  decorators: [withRouter("/server/organisations")],
};
export default meta;

type Story = StoryObj<typeof ServerOrganisationsPage>;

export const ActiveOrganisations: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([
      org({ id: "org-1", name: "Acme Corp", is_active: true }),
      org({ id: "org-2", name: "Beta Inc", is_active: false }),
    ]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Defaults to the "active" filter — the disabled org is hidden.
    await expect(canvas.getByText("Acme Corp")).toBeInTheDocument();
    await expect(canvas.queryByText("Beta Inc")).not.toBeInTheDocument();
  },
};

export const ShowAllIncludesDisabled: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([
      org({ id: "org-1", name: "Acme Corp", is_active: true }),
      org({ id: "org-2", name: "Beta Inc", is_active: false }),
    ]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "All" }));
    await expect(canvas.getByText("Acme Corp")).toBeInTheDocument();
    await expect(canvas.getByText("Beta Inc")).toBeInTheDocument();
  },
};

export const CreateOrganisation: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([org({})]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New organisation/ }));
    await userEvent.type(canvas.getByPlaceholderText("Organisation name"), "New Co");
    await userEvent.click(canvas.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/orgs", { name: "New Co" }));
  },
};

/** Disable requires confirming via `window.confirm` — mocked to accept, so
 * the action proceeds through to the API call. */
export const DisableOrganisation: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([org({ id: "org-1", name: "Acme Corp", is_active: true })]);
    spyOn(api, "post").mockResolvedValue(undefined);
    spyOn(window, "confirm").mockReturnValue(true);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/orgs/org-1/disable"));
  },
};

/** Deleting requires typing the organisation's exact name — the confirm
 * button stays disabled until the typed text matches. */
export const DeleteRequiresTypedConfirmation: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([org({ id: "org-1", name: "Acme Corp", is_active: true })]);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Delete" }));
    const confirmButton = canvas.getByRole("button", { name: "Permanently delete" });
    await expect(confirmButton).toBeDisabled();
    await userEvent.type(canvas.getByPlaceholderText("Acme Corp"), "Acme Corp");
    await expect(confirmButton).toBeEnabled();
    await userEvent.click(confirmButton);
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/orgs/org-1", { confirm_name: "Acme Corp" }));
  },
};

export const LightTheme: Story = { ...ActiveOrganisations, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ActiveOrganisations, globals: { theme: "dark" } };
