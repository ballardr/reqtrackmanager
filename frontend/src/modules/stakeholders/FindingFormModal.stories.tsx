import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { FindingFormModal } from "./FindingFormModal";

const ENGAGEMENTS = [
  { value: "e-1", label: "ENG-001 Quarterly review" },
  { value: "e-2", label: "ENG-002 Site visit" },
];

const meta: Meta<typeof FindingFormModal> = {
  title: "Modules/Stakeholders/FindingFormModal",
  component: FindingFormModal,
  args: { error: null, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof FindingFormModal>;

// The modal portals to `document.body`.
const dialog = () => within(within(document.body).getByRole("dialog"));

/** An engagement's own panel fixes the engagement, so the form asks only for the finding. */
export const FixedEngagementNeedsOnlyATitle: Story = {
  play: async ({ args }) => {
    await expect(dialog().queryByLabelText("Engagement")).not.toBeInTheDocument();
    await expect(dialog().getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(dialog().getByLabelText("Finding title"), "Technicians skip the checklist");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      { title: "Technicians skip the checklist", description: "" }, { engagementId: "", quickLinks: [], tags: [] },
    );
  },
};

/** From another record's Links panel the engagement is chosen: Save stays unavailable until it is. */
export const ChoosingAnEngagementIsRequired: Story = {
  args: { engagementOptions: ENGAGEMENTS },
  play: async ({ args }) => {
    await userEvent.type(dialog().getByLabelText("Finding title"), "Technicians skip the checklist");
    await expect(dialog().getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.selectOptions(dialog().getByLabelText("Engagement"), "e-2");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      { title: "Technicians skip the checklist", description: "" }, expect.objectContaining({ engagementId: "e-2" }),
    );
  },
};

/** The engagement whose Links panel opened the form is selected already. */
export const PreselectsThePageEngagement: Story = {
  args: { engagementOptions: ENGAGEMENTS, defaultEngagementId: "e-1" },
  play: async () => {
    await expect(dialog().getByLabelText("Engagement")).toHaveValue("e-1");
  },
};
