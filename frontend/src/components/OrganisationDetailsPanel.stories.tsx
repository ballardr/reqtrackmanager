import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { Organization, ServerSettings } from "../api/types";
import { OrganisationDetailsPanel } from "./OrganisationDetailsPanel";

const org = {
  id: "org-1", name: "Acme Corp", logo_file_id: null, email_footer_company_name: "Acme Ltd", email_footer_website: null,
  email_footer_address: null,
} as unknown as Organization;
const platform = { default_logo_file_id: null, email_footer_company_name: "Platform Co" } as unknown as ServerSettings;

const meta: Meta<typeof OrganisationDetailsPanel> = {
  title: "Components/OrganisationDetailsPanel",
  component: OrganisationDetailsPanel,
  args: { org, platformBranding: platform, onOrgChange: fn() },
  render: (args) => <div style={{ width: 640 }}><OrganisationDetailsPanel {...args} /></div>,
};
export default meta;

type Story = StoryObj<typeof OrganisationDetailsPanel>;

/** Save is unavailable until a change; clearing a company field sends null for that field only. */
export const ClearingAFieldSendsNullForThatFieldOnly: Story = {
  beforeEach: () => {
    spyOn(api, "put").mockResolvedValue({ ...org, email_footer_company_name: null });
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
    await expect(canvas.getByLabelText("Company name")).toHaveValue("Acme Ltd");
    await userEvent.clear(canvas.getByLabelText("Company name"));
    await expect(canvas.getByLabelText("Company name")).toHaveAttribute("placeholder", "Platform Co");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/orgs/org-1/branding", { email_footer_company_name: null }));
    await expect(args.onOrgChange).toHaveBeenCalled();
  },
};
