import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../../testing/requiredMarkers";
import { buildState } from "./architectureFixtures";
import { StateFormModal } from "./StateFormModal";

const meta: Meta<typeof StateFormModal> = {
  title: "Modules/Architecture/StateFormModal",
  component: StateFormModal,
  args: { initial: buildState({ name: "Idle", entry_action: "stop motor" }), onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof StateFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

/** Editing starts from the state's values; only the name is required and a blank name cannot be saved. */
export const EditShowsTheStatesValuesAndNeedsAName: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(within(document.body).getByRole("dialog"))).toEqual(["Name"]);
    await expect(d.getByLabelText(/^Name/)).toHaveValue("Idle");
    await expect(d.getByLabelText("Entry action")).toHaveValue("stop motor");
    await expect(d.queryByText("Quick links")).not.toBeInTheDocument();
    await userEvent.clear(d.getByLabelText(/^Name/));
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(d.getByLabelText(/^Name/), "  Standby ");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ name: "Standby", kind: "state", entry_action: "stop motor" }));
  },
};

/** A marker takes a name only: the actions go away when the kind is a marker. */
export const AMarkerKindHidesTheActions: Story = {
  args: { initial: buildState({ name: "Final state", kind: "final" }) },
  play: async () => {
    const d = dialog();
    await expect(d.queryByLabelText("Entry action")).not.toBeInTheDocument();
    await userEvent.selectOptions(d.getByLabelText("Kind"), "state");
    await expect(d.getByLabelText("Entry action")).toBeInTheDocument();
  },
};

/** A state that holds other states cannot be made a marker, which has no inside. */
export const AStateThatHoldsOthersCannotBecomeAMarker: Story = {
  args: { initial: buildState(), holdsStates: true },
  play: async () => {
    const options = within(dialog().getByLabelText("Kind")).getAllByRole("option").map((o) => o.textContent);
    await expect(options).toEqual(["State"]);
  },
};
