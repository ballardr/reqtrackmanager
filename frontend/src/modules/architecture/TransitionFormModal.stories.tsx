import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../../testing/requiredMarkers";
import { buildStateMachineModel, buildTransition } from "./architectureFixtures";
import { TransitionFormModal } from "./TransitionFormModal";

const STATES = buildStateMachineModel().states;

const meta: Meta<typeof TransitionFormModal> = {
  title: "Modules/Architecture/TransitionFormModal",
  component: TransitionFormModal,
  args: { states: STATES, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof TransitionFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

/** Both ends are required; the same state at both ends is a loop and is allowed. */
export const BothEndsAreRequiredAndALoopIsAllowed: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(within(document.body).getByRole("dialog"))).toEqual(["From", "To"]);
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.selectOptions(d.getByLabelText(/^From/), "ste-2");
    await userEvent.selectOptions(d.getByLabelText(/^To/), "ste-2");
    await userEvent.type(d.getByLabelText("Event"), "tick");
    await userEvent.type(d.getByLabelText("Action"), "adjust");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith({
      source_state_id: "ste-2", target_state_id: "ste-2", event: "tick", guard: "", action: "adjust", description: "",
    });
  },
};

/** The ends drawn on the canvas arrive preselected, and a marker is named by its kind in the pickers. */
export const EndsFromTheCanvasArePreselected: Story = {
  args: { defaultSourceId: "ste-1", defaultTargetId: "ste-3" },
  play: async () => {
    const d = dialog();
    await expect(d.getByLabelText(/^From/)).toHaveValue("ste-1");
    await expect(d.getByLabelText(/^To/)).toHaveValue("ste-3");
    // Both pickers list it, so a marker is told from a state by its kind.
    await expect(d.getAllByRole("option", { name: "STE-003 Final state (Final state)" })).toHaveLength(2);
    await expect(d.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

export const EditShowsTheTransitionsValues: Story = {
  args: { initial: buildTransition({ event: "start", guard: "ready", action: "spin up" }) },
  play: async () => {
    const d = dialog();
    await expect(d.getByRole("heading", { name: "Edit transition" })).toBeInTheDocument();
    await expect(d.getByLabelText("Event")).toHaveValue("start");
    await expect(d.getByLabelText("Guard")).toHaveValue("ready");
    await expect(d.getByLabelText("Action")).toHaveValue("spin up");
  },
};
