import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, within } from "storybook/test";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { withToast } from "../testing/storybook-helpers";
import { OrganizationCodePanel } from "./OrganizationCodePanel";

const ORG: Organization = {
  id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
  default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
  disabled_at: null, accent_color_hex: null, header_title: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
  code: "ACME", project_code_policy: { kind: "alphanumeric", min_length: 2, max_length: 6, assignment: "auto" },
  enforce_code_everywhere: false,
  force_require_change_request_for_approved_links: false,
  allow_ai_approvals: false,
};

const meta: Meta<typeof OrganizationCodePanel> = {
  title: "Components/OrganizationCodePanel",
  component: OrganizationCodePanel,
  decorators: [withToast()],
  args: { org: ORG, onSaved: fn() },
};
export default meta;
type Story = StoryObj<typeof OrganizationCodePanel>;

/** Nothing to save until the code differs from the current one. */
export const SaveNeedsAChange: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(canvas.getByLabelText("Code"), "X");
    await expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

/** A hyphen (or any non-alphanumeric character) cannot be saved: a qualified code splits on its first hyphen. */
export const RejectsAHyphen: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const field = canvas.getByLabelText("Code");
    await userEvent.clear(field);
    await userEvent.type(field, "AC-ME");
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

/** Saving warns that written-down qualified codes stop matching, then sends the upper-cased code. */
export const ConfirmsThenSaves: Story = {
  play: async ({ canvasElement, args }) => {
    const put = spyOn(api, "put").mockResolvedValue({ ...ORG, code: "ZULU" });
    const canvas = within(canvasElement);
    const field = canvas.getByLabelText("Code");
    await userEvent.clear(field);
    await userEvent.type(field, "zulu");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    const dialog = within(document.body);
    await expect(dialog.getByText(/ACME becomes ZULU/)).toBeInTheDocument();
    await expect(put).not.toHaveBeenCalled();
    await userEvent.click(dialog.getByRole("button", { name: "Change code" }));
    await expect(put).toHaveBeenCalledWith("/api/v1/orgs/org-1/code", { code: "ZULU" });
    await expect(args.onSaved).toHaveBeenCalledWith({ ...ORG, code: "ZULU" });
  },
};

/** Cancelling the confirmation changes nothing. */
export const CancelLeavesTheCode: Story = {
  play: async ({ canvasElement }) => {
    const put = spyOn(api, "put");
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Code"), "Z");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Cancel" }));
    await expect(put).not.toHaveBeenCalled();
  },
};
