import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, within } from "storybook/test";

import { api } from "../../api/client";
import { requiredCaptions } from "../../testing/requiredMarkers";
import { buildState, PROJECT_ID } from "./architectureFixtures";
import { StateFormModal } from "./StateFormModal";

const meta: Meta<typeof StateFormModal> = {
  title: "Modules/Architecture/StateFormModal",
  component: StateFormModal,
  args: { projectId: PROJECT_ID, onCancel: fn(), onSave: fn() },
  beforeEach: () => { spyOn(api, "get").mockResolvedValue({ members: [], external: null } as never); },
};
export default meta;

type Story = StoryObj<typeof StateFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

/** Only the name is required; the rest of the fields, quick links and tags are optional on a new state. */
export const CreateNeedsOnlyAName: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(within(document.body).getByRole("dialog"))).toEqual(["Name"]);
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(d.getByLabelText(/^Name/), "  Idle ");
    await userEvent.type(d.getByLabelText("Entry action"), "stop motor");
    await userEvent.type(d.getByLabelText("Exit action"), "log");
    await userEvent.type(d.getByLabelText("Activity"), "wait");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      { name: "Idle", description: "", kind: "state", entry_action: "stop motor", exit_action: "log", activity: "wait" },
      { quickLinks: [], tags: [] },
    );
  },
};

/** A marker takes a name only: the actions go away when the kind is a marker, and the name is preset to the kind. */
export const AMarkerKindHidesTheActions: Story = {
  args: { defaultKind: "final" },
  play: async () => {
    const d = dialog();
    await expect(d.getByLabelText(/^Name/)).toHaveValue("Final state");
    await expect(d.queryByLabelText("Entry action")).not.toBeInTheDocument();
    await userEvent.selectOptions(d.getByLabelText("Kind"), "state");
    await expect(d.getByLabelText("Entry action")).toBeInTheDocument();
  },
};

/** Editing starts from the state's values and offers no quick links or tags. */
export const EditShowsTheStatesValues: Story = {
  args: { initial: buildState({ name: "Idle", entry_action: "stop motor" }) },
  play: async () => {
    const d = dialog();
    await expect(d.getByLabelText(/^Name/)).toHaveValue("Idle");
    await expect(d.getByLabelText("Entry action")).toHaveValue("stop motor");
    await expect(d.queryByText("Quick links")).not.toBeInTheDocument();
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
