import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, within } from "storybook/test";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { withToast } from "../testing/storybook-helpers";
import { ProjectCodePolicyPanel } from "./ProjectCodePolicyPanel";

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

const meta: Meta<typeof ProjectCodePolicyPanel> = {
  title: "Components/ProjectCodePolicyPanel",
  component: ProjectCodePolicyPanel,
  decorators: [withToast()],
  args: { org: ORG, onSaved: fn() },
};
export default meta;
type Story = StoryObj<typeof ProjectCodePolicyPanel>;

/** Saving sends the whole policy and the enforce switch in one call. */
export const SavesPolicy: Story = {
  play: async ({ canvasElement, args }) => {
    const put = spyOn(api, "put").mockResolvedValue({ ...ORG, enforce_code_everywhere: true });
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByLabelText("Assignment"), "manual");
    await userEvent.click(canvas.getByRole("checkbox", { name: "Always show the project code" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await expect(put).toHaveBeenCalledWith("/api/v1/orgs/org-1/code-policy", {
      kind: "alphanumeric", min_length: 2, max_length: 6, assignment: "manual", enforce_code_everywhere: true,
    });
    await expect(args.onSaved).toHaveBeenCalled();
  },
};

/** An inverted length range cannot be saved. */
export const InvalidLengthsDisableSave: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const longest = canvas.getByLabelText("Longest");
    await userEvent.clear(longest);
    await userEvent.type(longest, "1");
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
  },
};
