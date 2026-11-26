import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { ENFORCED_PROFILE, ORG_ID, ORG_PROJECTS } from "./profileFixtures";
import { ProfileExemptionModal } from "./ProfileExemptionModal";

const meta: Meta<typeof ProfileExemptionModal> = {
  title: "Modules/Governance/ProfileExemptionModal",
  component: ProfileExemptionModal,
  args: { orgId: ORG_ID, profileId: ENFORCED_PROFILE.id, taken: new Set(["proj-2"]), onAdded: fn(), onClose: fn() },
  decorators: [withToast()],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ORG_PROJECTS);
  },
};
export default meta;

type Story = StoryObj<typeof ProfileExemptionModal>;

const dialog = () => within(document.body).findByRole("dialog", { name: "Add exemption" });

/** A project that is already exempt is not offered, and Add exemption needs a project. */
export const OffersOnlyProjectsNotYetExempt: Story = {
  play: async () => {
    const form = within(await dialog());
    await waitFor(() => expect(form.getByRole("option", { name: "HBR Harbour crossing" })).toBeInTheDocument());
    await expect(form.queryByRole("option", { name: "SIG Signalling upgrade" })).not.toBeInTheDocument();
    await expect(form.getByRole("button", { name: "Add exemption" })).toBeDisabled();
  },
};

/** The exemption is sent with its project, nested-projects choice and reason, and the updated profile is handed on. */
export const AddsTheExemption: Story = {
  play: async ({ args }) => {
    spyOn(api, "post").mockResolvedValue(ENFORCED_PROFILE);
    const form = within(await dialog());
    await waitFor(() => expect(form.getByRole("option", { name: "DEP Depot refit" })).toBeInTheDocument());
    await userEvent.selectOptions(form.getByRole("combobox", { name: "Project" }), "proj-3");
    await userEvent.click(form.getByRole("checkbox", { name: "Includes nested projects" }));
    await userEvent.type(form.getByRole("textbox", { name: "Reason" }), "Retiring in March.");
    await userEvent.click(form.getByRole("button", { name: "Add exemption" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/traceability/profiles/prof-1/exemptions`,
      { project_id: "proj-3", include_children: true, reason: "Retiring in March." },
    ));
    await waitFor(() => expect(args.onAdded).toHaveBeenCalledWith(ENFORCED_PROFILE));
    await expect(await within(document.body).findByText("Exemption added.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { globals: { theme: "dark" } };
