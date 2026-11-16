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

/** A marker takes a name and a symbol label: the actions go away when the kind is a marker, and the label when it is a state. */
export const AMarkerKindHidesTheActionsAndShowsTheSymbolLabel: Story = {
  args: { initial: buildState({ name: "Final state", kind: "final", label: "Landed" }) },
  play: async () => {
    const d = dialog();
    await expect(d.queryByLabelText("Entry action")).not.toBeInTheDocument();
    await expect(d.getByLabelText("Symbol label")).toHaveValue("Landed");
    await userEvent.selectOptions(d.getByLabelText("Kind"), "state");
    await expect(d.getByLabelText("Entry action")).toBeInTheDocument();
    await expect(d.queryByLabelText("Symbol label")).not.toBeInTheDocument();
  },
};

/** The label is limited to 256 characters in the field, so a longer entry cannot be typed; the count shows near the limit. */
export const TheSymbolLabelTakes256Characters: Story = {
  args: { initial: buildState({ name: "Choice", kind: "choice" }) },
  play: async () => {
    const field = dialog().getByLabelText("Symbol label");
    await expect(field).toHaveAttribute("maxlength", "256");
    await userEvent.type(field, "Battery low?");
    await expect(field).toHaveValue("Battery low?");
    await expect(dialog().queryByText(/of 256 characters/)).not.toBeInTheDocument();
    await userEvent.clear(field);
    await userEvent.click(field);
    await userEvent.paste("word ".repeat(40));
    await expect(dialog().getByText("200 of 256 characters.")).toBeInTheDocument();
  },
};

/** A word longer than the largest symbol holds is warned about on the field, and the warning goes when the label is changed. */
export const AWordTooLongForTheLargestSymbolIsWarnedAbout: Story = {
  args: { initial: buildState({ name: "Choice", kind: "choice", label: `before ${"x".repeat(60)} after` }) },
  play: async () => {
    const d = dialog();
    await expect(d.getByRole("alert")).toHaveTextContent("A word in this label is longer than the largest symbol holds");
    const field = d.getByLabelText("Symbol label");
    await userEvent.clear(field);
    await userEvent.type(field, "Fits?");
    await expect(d.queryByRole("alert")).not.toBeInTheDocument();
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
