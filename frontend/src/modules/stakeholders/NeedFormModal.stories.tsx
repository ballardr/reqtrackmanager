import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildNeed } from "./fixtures";
import { NeedFormModal } from "./NeedFormModal";

const meta: Meta<typeof NeedFormModal> = {
  title: "Modules/Stakeholders/NeedFormModal",
  component: NeedFormModal,
  args: { onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof NeedFormModal>;

// The modal portals to `document.body`.
const dialog = () => within(within(document.body).getByRole("dialog"));

export const CreateNeedsAName: Story = {
  play: async () => {
    await expect(within(document.body).getByRole("heading", { name: "New Stakeholder Need" })).toBeInTheDocument();
    await expect(dialog().getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(dialog().getByLabelText("Need name"), "Diagnose faults quickly");
    await expect(dialog().getByRole("button", { name: "Save" })).toBeEnabled();
    await expect(dialog().queryByLabelText("Change note")).not.toBeInTheDocument();
  },
};

export const SavesEnteredValues: Story = {
  play: async ({ args }) => {
    await userEvent.type(dialog().getByLabelText("Need name"), "Diagnose faults quickly");
    await userEvent.type(dialog().getByLabelText("Need", { selector: "textarea" }), "Fix it on site");
    await userEvent.type(dialog().getByLabelText("Rationale"), "Each delay costs an hour");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith({
      name: "Diagnose faults quickly", description: "Fix it on site", rationale: "Each delay costs an hour", change_note: "",
    });
  },
};

export const EditPrefillsAndOffersAChangeNote: Story = {
  args: { initial: buildNeed() },
  play: async ({ args }) => {
    await expect(dialog().getByLabelText("Need name")).toHaveValue("Diagnose faults quickly");
    await userEvent.type(dialog().getByLabelText("Change note"), "Clarified");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ change_note: "Clarified" }));
  },
};

export const ShowsTheServerError: Story = {
  args: { error: "Could not create Need." },
  play: async () => {
    await expect(dialog().getByText("Could not create Need.")).toBeInTheDocument();
  },
};
