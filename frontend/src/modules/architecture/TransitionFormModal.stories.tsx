import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../../testing/requiredMarkers";
import { buildStateMachineModel, buildTransition } from "./architectureFixtures";
import { TransitionFormModal } from "./TransitionFormModal";

const STATES = buildStateMachineModel().states;

const meta: Meta<typeof TransitionFormModal> = {
  title: "Modules/Architecture/TransitionFormModal",
  component: TransitionFormModal,
  args: { states: STATES, initial: buildTransition(), onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof TransitionFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

/** Both ends are required; the same state at both ends is a loop and is allowed. */
export const BothEndsAreRequiredAndALoopIsAllowed: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(within(document.body).getByRole("dialog"))).toEqual(["From", "To"]);
    await expect(d.getByRole("button", { name: "Save" })).toBeEnabled();
    await userEvent.selectOptions(d.getByLabelText(/^From/), "ste-2");
    await userEvent.selectOptions(d.getByLabelText(/^To/), "ste-2");
    await userEvent.clear(d.getByLabelText("Event"));
    await userEvent.type(d.getByLabelText("Event"), "tick");
    await userEvent.type(d.getByLabelText("Action"), "adjust");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith({
      source_state_id: "ste-2", target_state_id: "ste-2", event: "tick", guard: "", action: "adjust", description: "",
    });
  },
};

/** A marker is named by its kind in the end pickers, so it is told from a state. */
export const AMarkerIsNamedByItsKindInThePickers: Story = {
  play: async () => {
    const d = dialog();
    // Both pickers list it.
    await expect(d.getAllByRole("option", { name: "STE-003 Final state (Final state)" })).toHaveLength(2);
  },
};

export const EditShowsTheTransitionsValues: Story = {
  args: { initial: buildTransition({ event: "start", guard: "ready", action: "spin up" }) },
  play: async () => {
    const d = dialog();
    await expect(d.getByRole("heading", { name: "Edit transition" })).toBeInTheDocument();
    await expect(d.getByLabelText("Event")).toHaveValue("start");
    await expect(d.getByLabelText("Condition (guard)")).toHaveValue("ready");
    await expect(d.getByLabelText("Action")).toHaveValue("spin up");
  },
};
